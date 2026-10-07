"""Serial request/feedback UDP source using unchanged ICD and explicit endpoints."""

from collections import OrderedDict
import hashlib
import math
import socket
import threading
import time

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize
from icd_runtime.reassembly import Reassembler
from icd_runtime.resource_budget import ResourceBudget
from icd_runtime.wire import WireCodec
from icd_gateway.config import endpoint


class UDPSource:
    def __init__(self, contract, *, source_bind, feedback_bind, receiver_endpoint, channel):
        self.contract = contract
        self.channel = channel
        if channel not in {f"ETH_{i}" for i in range(4)}:
            raise ICDError("SCHEMA", "declared Ethernet channel required")
        self.receiver_endpoint = endpoint(receiver_endpoint)
        self.wire = WireCodec(contract)
        self.assembler = Reassembler(contract, retain_completed=False)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.feedback_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(endpoint(source_bind, allow_ephemeral=True))
            self.feedback_socket.bind(endpoint(feedback_bind, allow_ephemeral=True))
        except Exception:
            self.socket.close()
            self.feedback_socket.close()
            raise
        self.source_endpoint = self.socket.getsockname()
        self.feedback_endpoint = self.feedback_socket.getsockname()
        self.dropped_feedback = 0
        self._feedback_highwater = {}
        self._feedback_cache = OrderedDict()
        self._policy = contract.catalogue["policy"]
        self._resource_budget = ResourceBudget(contract)
        self._resource_group_ns = contract.catalogue["codecs"]["UDP"]["reassembly_timeout_ms"] * 1_000_000
        self._session_owner = None
        self._owner_lock = threading.Lock()
        self._highest_transaction_sent = 0
        self._fragment_due = {}
        self._transmissions = {}
        self._last_resource_actual_ns = None
        self._evidence_inbox = None

    def claim_session_owner(self, owner):
        with self._owner_lock:
            if owner is None or self._session_owner is not None or self.socket.fileno() < 0 or self.feedback_socket.fileno() < 0:
                raise ICDError("STATE", "transport lifetime already owned or closed")
            self._session_owner = owner
            return self._highest_transaction_sent + 1

    def _check_owner(self, owner):
        if (self._session_owner is not None and owner is not self._session_owner
                or self._session_owner is None and owner is not None):
            raise ICDError("STATE", "only the claimed session owner may use this transport")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._evidence_inbox is not None:
            self._evidence_inbox.close()
        self.socket.close()
        self.feedback_socket.close()
        self._feedback_cache.clear()
        self._feedback_highwater.clear()
        self._fragment_due.clear()
        self._transmissions.clear()

    def prepare_transmission(self, message, *, owner=None):
        with self._owner_lock:
            self._check_owner(owner)
        if len(self._transmissions) >= 64:
            raise ICDError("BUFFER_FULL", "bounded prepared transmission capacity full")
        self.contract.validate_message(message, direction="TO_36")
        packets = self.wire.encode(message, "UDP")
        token = object()
        self._transmissions[token] = (message["message_id"], dict(message["header"]), packets)
        return token

    def transmit_fragment(self, token, index, *, owner=None):
        with self._owner_lock:
            self._check_owner(owner)
        if token not in self._transmissions:
            raise ICDError("STATE", "actual prepared transmission required")
        mid, h, packets = self._transmissions[token]
        if type(index) is not int or not 0 <= index < len(packets):
            raise ICDError("SCHEMA", "actual encoded fragment index required")
        if owner is not None:
            from .session import SourceSession
            if isinstance(owner,SourceSession):
                owner._check_target_guard(mid,h,packet=packets[index])
        packet = packets[index]
        key = (token, index)
        with self._owner_lock:
            self._check_owner(owner)
            self._highest_transaction_sent = max(self._highest_transaction_sent, h["transaction_id"])
        if mid == 34:
            now = time.perf_counter_ns()
            previous = self._fragment_due.get(key)
            if previous is None:
                if len(self._fragment_due) >= 64:
                    raise ICDError("BUFFER_FULL", "bounded fragment pacing reservations full")
                previous = (packet, self._resource_budget.reserve((packet,), now_ns=now))
                self._fragment_due[key] = previous
            if previous[0] != packet:
                raise ICDError("DUPLICATE", "reserved resource fragment changed bytes")
            duration = (ResourceBudget.wire_bits((packet,)) * 1_000_000_000
                        + self._resource_budget.bits_per_second - 1) // self._resource_budget.bits_per_second
            actual_due = previous[1] if self._last_resource_actual_ns is None else max(previous[1], self._last_resource_actual_ns + duration)
            if now < actual_due:
                return False
        self._emit_packet(packet, owner=owner)
        if mid == 34:
            self._last_resource_actual_ns = time.perf_counter_ns()
        self._fragment_due.pop(key, None)
        return True

    def discard_transmission(self, token, *, owner=None):
        with self._owner_lock:
            self._check_owner(owner)
        for key in tuple(self._fragment_due):
            if key[0] is token:
                del self._fragment_due[key]
        self._transmissions.pop(token, None)

    def _emit_packet(self, packet, *, owner=None):
        return self.socket.sendto(packet, self.receiver_endpoint)

    def _check_feedback_sequence(self, reply, now_ns):
        for key, (_, deadline) in list(self._feedback_cache.items()):
            if now_ns >= deadline:
                del self._feedback_cache[key]
        sid, sequence = int(reply["header"]["session_id"]), int(reply["header"]["sequence"])
        key = (sid, sequence)
        digest = hashlib.sha256(canonicalize(reply)).digest()
        previous = self._feedback_cache.get(key)
        if previous:
            if previous[0] != digest:
                raise ICDError("DUPLICATE", "feedback sequence reused for different logical content")
            return False
        if sequence <= self._feedback_highwater.get(sid, 0):
            raise ICDError("OUT_OF_ORDER", "feedback sequence stale after cache expiry/eviction")
        if sid not in self._feedback_highwater and len(self._feedback_highwater) >= 64:
            raise ICDError("BUFFER_FULL", "source session tracking capacity reached; close and reauthorize")
        self._feedback_highwater[sid] = sequence
        self._feedback_cache[key] = (digest, now_ns + self._policy["duplicate_retention_ms"] * 1_000_000)
        while len(self._feedback_cache) > self._policy["duplicate_cache_messages"]:
            self._feedback_cache.popitem(last=False)
        return True

    def send(self, message, *, owner=None):
        with self._owner_lock:
            self._check_owner(owner)
        self.contract.validate_message(message, direction="TO_36")
        packets = self.wire.encode(message, "UDP")
        # Reserve before TX, including failed TX, so opening correlation never reuses it.
        with self._owner_lock:
            self._check_owner(owner)
            self._highest_transaction_sent = max(self._highest_transaction_sent, message["header"]["transaction_id"])
        resource = message["message_id"] == 34
        first_sent = None
        for packet in packets:
            if resource:
                # A high-resolution monotonic clock is local to pacing, never mixed with receiver timestamps.
                due = self._resource_budget.reserve((packet,), now_ns=time.perf_counter_ns())
                while True:
                    remaining = due - time.perf_counter_ns()
                    if remaining <= 0:
                        break
                    time.sleep(remaining / 1_000_000_000)
                actual = time.perf_counter_ns()
                if first_sent is not None and actual - first_sent >= self._resource_group_ns:
                    raise ICDError("TIMEOUT", "paced resource group exceeded unchanged UDP reassembly deadline")
                if first_sent is None:
                    first_sent = actual
            self._emit_packet(packet, owner=owner)
            if resource:
                self._last_resource_actual_ns = time.perf_counter_ns()
        return len(packets)

    def receive_for(self, request, *, timeout=0.2, owner=None):
        return self.receive_matching((request,), timeout=timeout, owner=owner)[1]

    def receive_matching(self, requests, *, timeout=0.2, owner=None):
        with self._owner_lock:
            self._check_owner(owner)
        inbox = self._evidence_inbox
        if type(requests) is not tuple or not (0 if inbox is not None else 1) <= len(requests) <= 64:
            raise ICDError("SCHEMA", "one to64 distinct outstanding requests required")
        keys = set()
        for request in requests:
            self.contract.validate_message(request, direction="TO_36")
            h = request["header"]
            key = (request["message_id"], h["session_id"], h["sequence"], h["transaction_id"])
            if key in keys:
                raise ICDError("SCHEMA", "duplicate outstanding request identity")
            keys.add(key)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 10:
            raise ICDError("SCHEMA", "finite bounded feedback timeout required")
        deadline = time.monotonic() + timeout
        for _ in range(256):
            remaining = deadline - time.monotonic()
            self.assembler.expire(now_ns=time.monotonic_ns())
            if timeout != 0 and remaining <= 0:
                raise ICDError("TIMEOUT", "matching feedback not received before deadline")
            self.feedback_socket.settimeout(0 if timeout == 0 else min(remaining, 0.02))
            if inbox is not None:
                inbox._preflight_receive()
            try:
                packet, actual_peer = self.feedback_socket.recvfrom(65536 if inbox is not None else 1201)
            except socket.timeout:
                continue
            except BlockingIOError:
                break
            received_ns = time.monotonic_ns()
            if inbox is not None:
                inbox._datagram(packet, actual_peer, received_ns)
            if actual_peer != self.receiver_endpoint:
                self.dropped_feedback += 1
                continue
            try:
                fragment = self.wire.decode(packet, "UDP", direction="FROM_36")
                if inbox is not None and fragment.message_id == 140:
                    reply = inbox._push(fragment,received_ns)
                    if reply is not None:
                        if inbox._complete(reply,actual_peer,received_ns,self._check_feedback_sequence):
                            inbox.session._last_rx_sequence = max(inbox.session.last_rx_sequence,reply['header']['sequence'])
                        else:
                            self.dropped_feedback += 1
                    continue
                candidates = [(i, request) for i, request in enumerate(requests)
                              if fragment.header.transaction_id == request["header"]["transaction_id"]
                              and (request["message_id"] == 1 or fragment.header.session_id == request["header"]["session_id"])]
                if not candidates:
                    raise ICDError("STATE", "feedback session/transaction differs from outstanding request")
                result = self.assembler.push(fragment, channel=self.channel, direction="FROM_36",
                                             authorized=True, now_ns=time.monotonic_ns())
                if result is None:
                    continue
                reply = result.message
                matched = []
                for index, request in candidates:
                    try:
                        self._correlate(request, reply)
                        matched.append(index)
                    except ICDError:
                        pass
                if len(matched) != 1:
                    raise ICDError("STATE", "feedback must identify exactly one outstanding request")
                self._check_feedback_sequence(reply, time.monotonic_ns())
                return matched[0], reply
            except ICDError as error:
                if error.code == "BUFFER_FULL":
                    raise
                self.dropped_feedback += 1
        raise ICDError("TIMEOUT", "no matching feedback in bounded receive work")

    def _correlate(self, request, reply):
        mid, payload, header = reply["message_id"], reply["payload"], request["header"]
        if mid == 130:
            if payload["request_sequence"] != header["sequence"] or payload["request_message_id"] != request["message_id"]:
                raise ICDError("STATE", "ACK names another request")
        elif mid == 141:
            self.contract.validate_resource_feedback(request, reply)
        elif mid == 131:
            if request["message_id"] != 2:
                raise ICDError("STATE", "Status is not a response to this request")
        elif mid == 142:
            if request["message_id"] != 33 or payload["nonce"] != request["payload"]["nonce"]:
                raise ICDError("STATE", "ClockStatus differs from measurement nonce/request")
        elif mid != 129 or request["message_id"] != 1 or payload["session_id"] != reply["header"]["session_id"]:
            raise ICDError("UNSUPPORTED", "feedback is outside implemented request exchange")

    def request(self, message, *, owner=None):
        with self._owner_lock:
            self._check_owner(owner)
        self.contract.validate_message(message, direction="TO_36")
        reliable = self.contract.entry(message["message_id"])["period_ms"] == 0
        attempts = 4 if reliable else 1
        final_resource = message["message_id"] == 34 and message["payload"]["final"]
        commit_deadline = time.monotonic() + self._policy["resource_commit_timeout_ms"] / 1000
        for attempt in range(attempts):
            self.send(message, owner=owner)
            deadline = time.monotonic() + self.contract.catalogue["policy"]["ack_timeout_ms"] / 1000
            while time.monotonic() < deadline:
                try:
                    reply = self.receive_for(message, timeout=max(0, deadline - time.monotonic()), owner=owner)
                except ICDError as error:
                    if error.code != "TIMEOUT":
                        raise
                    break
                if reply["message_id"] != 130 or reply["payload"]["stage"] in ("FAILED", "APPLIED", "CONSUMED"):
                    return reply
        if final_resource:
            while time.monotonic() < commit_deadline:
                reply = self.receive_for(message, timeout=max(0, commit_deadline - time.monotonic()), owner=owner)
                if reply["message_id"] != 130 or reply["payload"]["stage"] in ("FAILED", "APPLIED", "CONSUMED"):
                    return reply
        raise ICDError("TIMEOUT", "request exhausted original retries and bounded completion wait")
