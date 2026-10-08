"""Bounded monotonic reassembly. Callers must serialize access and enforce ACLs."""

from collections import OrderedDict
from dataclasses import asdict, dataclass, field
import hashlib
import time

from .errors import ICDError
from .video import VideoCodec, VideoFragment, VideoHeader
from .wire import Fragment, WireCodec


@dataclass(frozen=True, slots=True)
class CompletedMessage:
    message: dict
    data: bytes


@dataclass(frozen=True, slots=True)
class CompletedVideo:
    header: VideoHeader
    data: bytes
    sha256: str


@dataclass(slots=True)
class _Group:
    first: object
    deadline_ns: int
    reserved: int
    pieces: dict = field(default_factory=dict)


class Reassembler:
    def __init__(self, contract, *, retain_completed=True):
        if type(retain_completed) is not bool:
            raise ICDError("SCHEMA", "completed-group retention must be explicit boolean")
        self.contract = contract
        self._retain_completed = retain_completed
        self.wire = WireCodec(contract)
        self.video = VideoCodec(contract)
        self._policy = contract.catalogue["policy"]
        self._rules = contract.catalogue["codecs"]
        self._channels = {c["id"]: c["type"] for c in contract.catalogue["channels"]}
        self._groups = {}
        self._terminal = OrderedDict()
        self._reserved = 0
        self._last_now = -1

    @property
    def reserved_bytes(self):
        return self._reserved

    @property
    def pending_count(self):
        return len(self._groups)

    @property
    def terminal_count(self):
        return len(self._terminal)

    def _clock(self, now_ns):
        now = time.monotonic_ns() if now_ns is None else now_ns
        self.check_clock(now)
        self._last_now = now
        return now

    def check_clock(self, now):
        if type(now) is not int or now < 0 or now < self._last_now:
            raise ICDError("SCHEMA", "reassembly clock must be nondecreasing monotonic nanoseconds")
        return now

    def _remember(self, key, code, now):
        self._terminal[key] = (now + self._policy["duplicate_retention_ms"] * 1_000_000, code)
        self._terminal.move_to_end(key)
        while len(self._terminal) > self._policy["duplicate_cache_messages"]:
            self._terminal.popitem(last=False)

    def _drop(self, key):
        self._reserved -= self._groups.pop(key).reserved

    def discard_session(self, session_id):
        if type(session_id) is not int or not 0 <= session_id <= 0xffffffff:
            raise ICDError("SCHEMA", "session cleanup requires a uint32 identity")
        for key in list(self._groups):
            if key[3] == session_id:
                self._drop(key)
        for key in list(self._terminal):
            if key[3] == session_id:
                del self._terminal[key]

    def discard_inactive_sessions(self, active_sessions):
        if (type(active_sessions) is not tuple or any(
                type(sid) is not int or not 1 <= sid <= 0xffffffff for sid in active_sessions)):
            raise ICDError("SCHEMA", "explicit nonzero uint32 active session identities required")
        live = set(active_sessions)
        stale = {key[3] for key in self._groups.keys() | self._terminal.keys()
                 if key[3] != 0 and key[3] not in live}
        for sid in stale:
            self.discard_session(sid)
        return tuple(sorted(stale))

    def clear(self):
        self._groups.clear()
        self._terminal.clear()
        self._reserved = 0

    def expire(self, *, now_ns=None):
        now = self._clock(now_ns)
        expired = []
        for key, group in list(self._groups.items()):
            if now >= group.deadline_ns:
                self._drop(key)
                self._remember(key, "TIMEOUT", group.deadline_ns)
                expired.append(key)
        for key, (deadline, _) in list(self._terminal.items()):
            if now >= deadline:
                del self._terminal[key]
        return expired

    def _check(self, fragment, direction):
        if isinstance(fragment, Fragment):
            if fragment.direction != direction:
                raise ICDError("AUTHORIZATION", "fragment direction mismatch")
            entry = self.wire._entry(fragment.message_id, fragment.transport, direction)
            if (type(fragment.payload) is not bytes or type(fragment.index) is not int
                    or type(fragment.count) is not int):
                raise ICDError("FRAGMENT", "invalid decoded fragment value types")
            checked = self.wire._fragment(fragment.transport, entry, fragment.header,
                                          fragment.index, fragment.count, fragment.payload)
            if checked != fragment:
                raise ICDError("FRAGMENT", "fragment reservation/layout not decoder-derived")
            h = fragment.header
            identity = (h.session_id, fragment.message_id, h.sequence, h.transaction_id)
            return identity, fragment.reservation_bytes
        if isinstance(fragment, VideoFragment):
            if direction != "TO_36":
                raise ICDError("AUTHORIZATION", "video injection direction must be TO_36")
            self.video.validate_header(fragment.header)
            size = self._rules["VIDEO"]["chunk_bytes"]
            total = fragment.frame_bytes
            if type(total) is not int or not 1 <= total <= self._rules["VIDEO"]["max_frame_bytes"]:
                raise ICDError("CAPACITY", "invalid decoded video reservation")
            if (fragment.transport != "VIDEO" or type(fragment.count) is not int or type(fragment.index) is not int
                    or type(fragment.payload) is not bytes or fragment.count != (total + size - 1) // size
                    or not 0 <= fragment.index < fragment.count
                    or len(fragment.payload) != min(size, total - fragment.index * size)):
                raise ICDError("FRAGMENT", "invalid decoded video fragment layout")
            if fragment.header.codec == "RAW" and total != 921600:
                raise ICDError("SCHEMA", "decoded RAW frame size mismatch")
            h = fragment.header
            return (h.session_id, h.stream_numeric_id, h.frame_index), total
        raise ICDError("SCHEMA", "only verified business/video fragment types are accepted")

    def push(self, fragment, *, channel: str, direction: str, authorized: bool, now_ns=None,
             pre_session_namespace=None):
        if authorized is not True or direction not in ("TO_36", "FROM_36"):
            raise ICDError("AUTHORIZATION", "ACL decision and recognized direction required before allocation")
        if type(channel) is not str or not 1 <= len(channel) <= 128:
            raise ICDError("SCHEMA", "explicit bounded interface/channel identity required")
        medium = "CANFD" if isinstance(fragment, Fragment) and fragment.transport == "CANFD" else "ETH"
        if channel not in self._channels or self._channels[channel] != medium:
            raise ICDError("AUTHORIZATION", "channel not declared for this transport in the common catalogue")
        identity, reservation = self._check(fragment, direction)
        if pre_session_namespace is not None and (
                type(pre_session_namespace) is not int or not 0 <= pre_session_namespace < 64
                or not isinstance(fragment, Fragment) or fragment.message_id != 1 or identity[0] != 0):
            raise ICDError("SCHEMA", "local grant namespace is only for pre-session SessionOpen")
        now = self._clock(now_ns)
        self.expire(now_ns=now)
        key = (channel, direction, fragment.transport, *identity)
        if pre_session_namespace is not None:
            key += (pre_session_namespace,)
        if key in self._terminal:
            raise ICDError(self._terminal[key][1], "group already completed, rejected or expired")
        group = self._groups.get(key)
        if group is None:
            same_channel = sum(k[0] == channel for k, g in self._groups.items() if g.first.transport != "VIDEO")
            videos = sum(g.first.transport == "VIDEO" for g in self._groups.values())
            if (self._reserved + reservation > self._policy["total_reassembly_limit_bytes"]
                    or fragment.transport != "VIDEO" and same_channel >= self._policy["reassembly_slots_per_channel"]
                    or fragment.transport == "VIDEO" and videos >= self._rules["VIDEO"]["queue_frames"]):
                raise ICDError("BUFFER_FULL", "reassembly quota exceeded; existing groups not evicted")
            deadline = now + self._rules[fragment.transport]["reassembly_timeout_ms"] * 1_000_000
            group = _Group(fragment, deadline, reservation)
            self._groups[key] = group
            self._reserved += reservation
        first = group.first
        if (first.header != fragment.header or first.count != fragment.count or group.reserved != reservation):
            self._drop(key)
            self._remember(key, "FRAGMENT", now)
            raise ICDError("FRAGMENT", "group header/count/size conflict")
        if fragment.index in group.pieces:
            if group.pieces[fragment.index] != fragment.payload:
                self._drop(key)
                self._remember(key, "FRAGMENT", now)
                raise ICDError("FRAGMENT", "conflicting duplicate invalidates whole group")
            return None
        group.pieces[fragment.index] = fragment.payload
        if len(group.pieces) != fragment.count:
            return None
        data = b"".join(group.pieces[i] for i in range(fragment.count))
        self._drop(key)
        try:
            if isinstance(fragment, VideoFragment):
                if len(data) != fragment.frame_bytes:
                    raise ICDError("FRAGMENT", "assembled video length mismatch")
                self.video.validate_frame(data, fragment.header)
                result = CompletedVideo(fragment.header, data, hashlib.sha256(data).hexdigest())
            else:
                payload = self.wire.payload_codec.decode(fragment.message_id, data)
                message = {"message_id": fragment.message_id, "header": asdict(fragment.header), "payload": payload}
                self.contract.validate_message(message, direction=direction)
                result = CompletedMessage(message, data)
        except ICDError as exc:
            self._remember(key, exc.code, now)
            raise
        if self._retain_completed:
            self._remember(key, "DUPLICATE", now)
        return result
