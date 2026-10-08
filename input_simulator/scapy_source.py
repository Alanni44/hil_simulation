"""Original ETHGEN Scapy transport; local TX is not hardware qualification."""

from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, replace
import ipaddress
import re
import threading
import time

from scapy.all import conf
from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether
from scapy.packet import Raw
from scapy.supersocket import SuperSocket

from icd_gateway.config import endpoint
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from .replay_export import ExportBinding
from .session import SourceSession
from .tools import ChannelReservations
from .udp_source import UDPSource


@dataclass(frozen=True, slots=True)
class L2Transmission:
    interface: str
    ethernet_data: bytes
    udp_data: bytes
    started_ns: int
    completed_ns: int | None = None
    sent_bytes: int | None = None
    error: str | None = None
    qualification_status: str = 'NOT_EVALUATED'


class ScapySource(UDPSource):
    def __init__(self, contract, *, source_bind, feedback_bind, receiver_endpoint,
                 binding, reservations, reservation, l2socket=None,
                 max_l2_records=4096, max_l2_bytes=16 * 1024 * 1024):
        if (type(max_l2_records) is not int or not 1 <= max_l2_records <= 65536
                or type(max_l2_bytes) is not int or not 1 <= max_l2_bytes <= 128 * 1024 * 1024):
            raise ICDError('CAPACITY', 'bounded L2 attempt count and byte capacities required')
        if type(reservations) is not ChannelReservations:
            raise ICDError('STATE', 'original local reservation book required')
        token = reservations.validate(reservation)
        if (type(binding) is not ExportBinding or binding.channel_id not in {f'ETH_{i}' for i in range(4)}
                or token.branch_id != 'ETHGEN' or token.mode != 'SEND'
                or token.interfaces != (binding.interface,)):
            raise ICDError('SCHEMA', 'single original ETHGEN sender and formal Ethernet mapping required')
        for mac in (binding.source_mac, binding.destination_mac):
            if type(mac) is not str or re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', mac) is None:
                raise ICDError('SCHEMA', 'explicit unicast source and destination MAC required')
            octets = bytes.fromhex(mac.replace(':', ''))
            if octets == bytes(6) or octets[0] & 1:
                raise ICDError('SCHEMA', 'nonzero unicast MAC required')
        for value, ephemeral in ((source_bind, True), (feedback_bind, True), (receiver_endpoint, False)):
            host, _ = endpoint(value, allow_ephemeral=ephemeral)
            addr = ipaddress.IPv4Address(host)
            if addr.is_unspecified or addr.is_multicast or int(addr) == 0xffffffff:
                raise ICDError('SCHEMA', 'explicit unicast IPv4 endpoint required')
        if l2socket is not None and (not isinstance(l2socket, SuperSocket) or l2socket.closed):
            raise ICDError('STATE', 'actual live Scapy socket required')
        self.binding = binding
        self.reservations = reservations
        self.reservation = token
        self._l2_lock = threading.Lock()
        self._l2_records = []
        self._l2_bytes = 0
        self._max_l2_records = max_l2_records
        self._max_l2_bytes = max_l2_bytes
        self._closing = False
        self._close_retry = ()
        self._l2 = None
        super().__init__(contract, source_bind=source_bind, feedback_bind=feedback_bind,
                         receiver_endpoint=receiver_endpoint, channel=binding.channel_id)
        try:
            if l2socket is None:
                factory = conf.L2socket
                if not callable(factory):
                    raise ICDError('TARGET_MISSING', 'original Scapy L2 backend unavailable; no UDP fallback')
                try:
                    l2socket = factory(iface=binding.interface)
                except Exception as error:
                    raise ICDError('TARGET_MISSING', 'original Scapy L2 backend could not open') from error
                if not isinstance(l2socket, SuperSocket) or l2socket.closed:
                    if callable(getattr(l2socket, 'close', None)):
                        l2socket.close()
                    raise ICDError('TARGET_MISSING', 'factory did not open an actual live Scapy L2 socket')
            self._l2 = l2socket
        except Exception:
            super().close()
            raise

    @property
    def execution_ready(self):
        return False

    @property
    def safety_verified(self):
        return False

    @property
    def l2_records(self):
        return tuple(self._l2_records)

    @contextmanager
    def _source_operation(self, owner, *, closed_ok=False):
        self._check_owner(owner)
        if type(owner) is not SourceSession:
            if owner is not None:
                raise ICDError('AUTHORIZATION', 'actual original source owner required')
            yield
        elif owner._operation_thread == threading.get_ident():
            yield
        else:
            with owner._operation(closed_ok=closed_ok):
                yield

    def send(self, message, *, owner=None):
        with self._source_operation(owner):
            return super().send(message, owner=owner)

    def request(self, message, *, owner=None):
        with self._source_operation(owner):
            return super().request(message, owner=owner)

    def prepare_transmission(self, message, *, owner=None):
        with self._source_operation(owner):
            self.contract.validate_message(message, direction='TO_36')
            for packet in self.wire.encode(message, 'UDP'):
                self._authorize_packet(packet, owner)
            return super().prepare_transmission(message, owner=owner)

    def transmit_fragment(self, token, index, *, owner=None):
        with self._source_operation(owner):
            return super().transmit_fragment(token, index, owner=owner)

    def discard_transmission(self, token, *, owner=None):
        with self._source_operation(owner, closed_ok=True):
            return super().discard_transmission(token, owner=owner)

    def receive_matching(self, requests, *, timeout=0.2, owner=None):
        with self._source_operation(owner):
            return super().receive_matching(requests, timeout=timeout, owner=owner)

    def _authorize_packet(self, packet, owner):
        self._check_owner(owner)
        if self._closing or self._l2 is None or self._l2.closed:
            raise ICDError('STATE', 'original Scapy transport permanently closed')
        self.reservations.validate(self.reservation)
        if type(owner) is not SourceSession or owner.transport is not self or owner._closed:
            raise ICDError('AUTHORIZATION', 'actual owning source session required for Scapy TX')
        fragment = self.wire.decode(packet, 'UDP', direction='TO_36')
        h, mid = fragment.header, fragment.message_id
        if mid == 1:
            if (owner._state != 'OPENING' or h.session_id != 0 or h.sequence != 1
                    or h.transaction_id != owner._next_transaction - 1):
                raise ICDError('STATE', 'only the original in-progress standard opening may precede a grant')
            return
        now = owner._now()
        owner._check_target_guard(mid,asdict(h),packet=packet)
        if owner._state != 'LIVE' or h.session_id != owner.session_id or now >= owner._deadline_ns:
            raise ICDError('STALE_SESSION', 'original source grant absent, different or expired')
        entry = self.contract.entry(mid)
        if loads(owner._identity_json)['model_id'] not in entry['model_ids']:
            raise ICDError('MODEL', 'input belongs to another model')
        if entry['role'] != 'ANY_SESSION_ROLE' and entry['role'] not in owner.roles:
            raise ICDError('AUTHORIZATION', 'original grant does not authorize this input role')
        if mid not in owner.capabilities['implemented_message_ids']:
            raise ICDError('TARGET_MISSING', 'receiver did not publish this implementation')
        if not 2 <= h.sequence < owner._next_sequence or h.transaction_id >= owner._next_transaction:
            raise ICDError('STATE', 'source-owned allocated sequence and transaction required')
        allocated = owner._last_allocation == (mid, h)
        prepared = any(item.transport == 'UDP' and packet in item.frames
                       for item, _ in owner._inputs.values())
        transmitted = any(stored_mid == mid and packet in packets
                          for stored_mid, _, packets in self._transmissions.values())
        if not (allocated or prepared or transmitted):
            raise ICDError('STATE', 'actual allocated header association or original owned bytes required')

    def _emit_packet(self, packet, *, owner=None):
        if not self._l2_lock.acquire(blocking=False):
            raise ICDError('STATE', 'Scapy TX, drain and close require a single owner')
        try:
            self._authorize_packet(packet, owner)
            frame = Ether(src=self.binding.source_mac, dst=self.binding.destination_mac) / IP(
                src=self.source_endpoint[0], dst=self.receiver_endpoint[0], ttl=64) / UDP(
                sport=self.source_endpoint[1], dport=self.receiver_endpoint[1]) / Raw(packet)
            raw = bytes(frame)
            self._authorize_packet(packet,owner)
            size = len(raw) + len(packet) + 512
            if (len(self._l2_records) >= self._max_l2_records or self._l2_bytes + size > self._max_l2_bytes):
                raise ICDError('BUFFER_FULL', 'drain original bounded L2 attempts before another TX')
            # Reserve the complete immutable attempt before the actual backend call.
            index = len(self._l2_records)
            record = L2Transmission(self.binding.interface, raw, packet, time.monotonic_ns())
            self._l2_records.append(record)
            self._l2_bytes += size
            sent, error = None, None
            try:
                sent = self._l2.send(frame)
                if type(sent) is not int or not 0 <= sent <= len(raw):
                    sent = None
                    raise ICDError('RESOURCE', 'Scapy backend returned an invalid byte count')
                if sent != len(raw):
                    raise ICDError('RESOURCE', 'Scapy backend did not write the complete original frame')
                self._authorize_packet(packet, owner)
                return sent
            except ICDError as failure:
                error = failure.code
                raise
            except Exception as failure:
                error = 'RESOURCE'
                raise ICDError('RESOURCE', 'actual Scapy frame write failed; original attempt retained') from failure
            finally:
                self._l2_records[index] = replace(record, sent_bytes=sent, error=error,
                                                   completed_ns=time.monotonic_ns())
        finally:
            self._l2_lock.release()

    def drain_l2_records(self):
        with ExitStack() as stack:
            session = self._session_owner
            if session is not None:
                dispatcher = session._dispatcher
                if dispatcher is not None:
                    stack.enter_context(dispatcher._operation(closed_ok=True))
                stack.enter_context(session._operation(owner=dispatcher))
                if session._observation_recorder is not None:
                    raise ICDError('STATE', 'attached evidence recorder owns record draining')
            if not self._l2_lock.acquire(blocking=False):
                raise ICDError('STATE', 'Scapy record drain cannot overlap actual TX or close')
            try:
                records = tuple(self._l2_records)
                self._l2_records.clear()
                self._l2_bytes = 0
                return records
            finally:
                self._l2_lock.release()

    def close(self):
        with self._source_operation(self._session_owner, closed_ok=True):
            self._close_transport()

    def _close_transport(self):
        if not self._l2_lock.acquire(blocking=False):
            raise ICDError('STATE', 'Scapy close cannot overlap actual TX or drain')
        try:
            self._closing = True
            super().close()
            if self._l2 is not None:
                # SuperSocket marks itself closed before closing its native handles.
                # Retain those exact handles so a failed close can be retried.
                if not self._close_retry and not self._l2.closed:
                    handles = {}
                    for name in ('ins', 'outs', 'pcap_fd'):
                        handle = getattr(self._l2, name, None)
                        if handle is not None:
                            handles[id(handle)] = handle
                    self._close_retry = tuple(handles.values())
                    try:
                        self._l2.close()
                    except Exception as error:
                        raise ICDError('RESOURCE', 'original Scapy close failed; same handles retained') from error
                    self._close_retry = ()
                for handle in self._close_retry:
                    try:
                        handle.close()
                    except Exception as error:
                        raise ICDError('RESOURCE', 'original Scapy handle close retry failed') from error
                self._close_retry = ()
        finally:
            self._l2_lock.release()
