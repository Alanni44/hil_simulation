"""Original CANT library sender and standard CAN feedback, not qualification."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
import math
import struct
import threading
import time

import can

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import CANFrame
from .live_tool_input import LiveToolInputBuilder
from .replay_export import ExportBinding
from .session import MAX_REPLY_BYTES
from .udp_source import UDPSource
from ._native_scope import _admit


@dataclass(frozen=True, slots=True)
class CANObservation:
    kind: str
    channel_id: str
    interface: str
    started_ns: int
    arbitration_id: int | None = None
    data: bytes | None = None
    is_fd: bool | None = None
    bitrate_switch: bool | None = None
    is_extended_id: bool | None = None
    is_remote_frame: bool | None = None
    is_error_frame: bool | None = None
    error_state_indicator: bool | None = None
    is_rx: bool | None = None
    dlc: int | None = None
    actual_channel: str | int | None = None
    library_timestamp: float | None = None
    completed_ns: int | None = None
    send_completed: bool | None = None
    error: str | None = None
    reply_json: bytes | None = None
    request_json: bytes | None = None
    library_timestamp_bits: bytes | None = None
    qualification_status: str = 'NOT_EVALUATED'


@dataclass
class _SentGroup:
    plan: object
    started_ns: int
    size: int
    complete: bool = False
    feedback: tuple = ()


class CANSignalSender:
    def __init__(self, builder, reservation, binding, *, bus=None,
                 max_records=4096, max_bytes=16 * 1024 * 1024, max_pending=64):
        if (type(max_records) is not int or not 1 <= max_records <= 65536
                or type(max_bytes) is not int or not 1 <= max_bytes <= 128 * 1024 * 1024
                or type(max_pending) is not int or not 1 <= max_pending <= 64):
            raise ICDError('CAPACITY', 'bounded CAN observation and pending capacities required')
        if type(builder) is not LiveToolInputBuilder or not isinstance(builder.session.transport, UDPSource):
            raise ICDError('STATE', 'original builder and standard session feedback owner required')
        with builder._operation(), builder.session._operation():
            token = builder.book.validate(reservation)
            if token.branch_id != 'CANT' or token.mode != 'SEND':
                raise ICDError('AUTHORIZATION', 'original CANT sender reservation required')
            if type(binding) is not ExportBinding or builder._binding(token, binding)[0] != 'CANFD':
                raise ICDError('SCHEMA', 'original formal CAN FD binding required')
        if bus is not None and (not isinstance(bus, can.BusABC) or bus._is_shutdown):
            raise ICDError('STATE', 'actual live original python-can bus required')
        builder.book._claim_can_backend(token, self, bus)
        if bus is None:
            try:
                bus = can.Bus(interface='socketcan', channel=binding.interface, fd=True,
                              receive_own_messages=False, ignore_config=True)
            except Exception as error:
                builder.book._release_can_backend(token, self)
                raise ICDError('TARGET_MISSING', 'original SocketCAN backend unavailable; no fallback') from error
            if not isinstance(bus, can.BusABC) or bus._is_shutdown:
                try:
                    if callable(getattr(bus, 'shutdown', None)):
                        bus.shutdown()
                finally:
                    builder.book._release_can_backend(token, self)
                raise ICDError('TARGET_MISSING', 'original factory did not open a live python-can bus')
            try:
                builder.book._claim_can_backend(token, self, bus)
            except ICDError:
                builder.book._release_can_backend(token, self)
                raise
        self.builder, self.session, self.book = builder, builder.session, builder.book
        self.reservation, self.binding, self.bus = token, binding, bus
        self.contract = self.session.contract
        self.wire = self.session.transport.wire
        self.assembler = Reassembler(self.contract, retain_completed=False)
        self._max_records, self._max_bytes, self._max_pending = max_records, max_bytes, max_pending
        self._records, self._bytes, self._pending_bytes, self._pending = [], 0, 0, {}
        self._last_sid, self._last_sequence = None, 0
        self._lock = threading.Lock()
        self._closing, self._closed, self._close_retry = False, False, False
        self._group_ns = self.contract.catalogue['codecs']['CANFD']['reassembly_timeout_ms'] * 1_000_000

    @property
    def execution_ready(self):
        return False

    @property
    def safety_verified(self):
        return False

    @property
    def records(self):
        return tuple(self._records)

    @property
    def pending_count(self):
        return len(self._pending)

    @contextmanager
    def _operation(self, *, closed_ok=False):
        if _admit(self.session, builder=self.builder, sender=self, cleanup=closed_ok):
            self._check_local_operation(closed_ok)
            yield
            return
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE', 'CAN tool operations require one serialized owner')
        try:
            with self.builder._operation(), self.session._operation(closed_ok=closed_ok):
                self._check_local_operation(closed_ok)
                yield
        finally:
            self._lock.release()

    def _check_local_operation(self, closed_ok):
        if (self._closing or self._closed or self.bus._is_shutdown) and not closed_ok:
            raise ICDError('STATE', 'original CAN sender permanently closing or closed')
        recorder = self.session._observation_recorder
        if recorder is not None and not recorder._owns_native(self.session._native_tool_coordinator, self):
            raise ICDError('STATE', 'attached original recorder owns source observations')

    @staticmethod
    def _timeout(value, maximum):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
            raise ICDError('SCHEMA', 'explicit finite bounded CAN timeout required')
        return value

    def _authorize(self, plan):
        _, token, _ = self.builder._owned(plan)
        if token is not self.reservation or plan.binding != self.binding or plan.branch_id != 'CANT':
            raise ICDError('STATE', 'actual CANT plan for this original reservation and channel required')
        item = self._current_authority(plan.source_input)
        if tuple(self.builder.protocol.encode(item.message)) != item.frames:
            raise ICDError('RESOURCE', 'original cantools group differs from owned source bytes')
        return item

    def _current_authority(self, item):
        self.book.validate(self.reservation)
        item = self.session._verify_input(item)
        if item.transport != 'CANFD':
            raise ICDError('UNSUPPORTED', 'original CAN FD input group required')
        value = item.message
        mid, entry = value['message_id'], self.contract.entry(value['message_id'])
        if entry['role'] != 'ANY_SESSION_ROLE' and entry['role'] not in self.session.roles:
            raise ICDError('AUTHORIZATION', 'current original grant lacks this CAN input role')
        if mid not in self.session.capabilities['implemented_message_ids']:
            raise ICDError('TARGET_MISSING', 'receiver did not publish this CAN message implementation')
        model = loads(self.session._identity_json)['model_id']
        if model not in self.session.capabilities['model_ids']:
            raise ICDError('TARGET_MISSING', 'receiver no longer publishes this model implementation')
        self.contract.validate_message(value, direction='TO_36', model_id=model)
        return item

    def _capacity(self, count, size):
        if len(self._records) + count > self._max_records or self._bytes + self._pending_bytes + size > self._max_bytes:
            raise ICDError('BUFFER_FULL', 'original bounded CAN observations cannot be evicted')

    @staticmethod
    def _size(row):
        channel_bytes = len(row.actual_channel.encode('utf-8')) if type(row.actual_channel) is str else 0
        return (512 + len(row.data or b'') + len(row.reply_json or b'')
                + len(row.request_json or b'') + len(row.library_timestamp_bits or b'') + channel_bytes)

    def _failure(self, plan, code):
        now = time.monotonic_ns()
        self._record(CANObservation('FAILED', self.binding.channel_id, self.binding.interface,
            now, completed_ns=now, error=code, request_json=plan.source_input.input_json))

    def _record(self, row):
        size = self._size(row)
        self._capacity(1, size)
        self._records.append(row)
        self._bytes += size
        return len(self._records) - 1

    def _frame_record(self, kind, frame):
        actual_channel = frame.channel
        channel_valid = (actual_channel is None or type(actual_channel) is str and len(actual_channel) <= 1024
                         or type(actual_channel) is int and -(2**63) <= actual_channel < 2**63)
        stamp = frame.timestamp
        stamp_valid = (type(stamp) in (int, float) and 0 <= stamp <= 2**63 - 1 and math.isfinite(stamp))
        if kind != 'RX' and not channel_valid:
            raise ICDError('SCHEMA', 'bounded original CAN channel metadata required')
        if kind != 'RX' and not stamp_valid:
            raise ICDError('SCHEMA', 'finite original CAN library timestamp required')
        # Reject malformed native metadata without losing the received wire frame.
        return CANObservation(kind, self.binding.channel_id, self.binding.interface, time.monotonic_ns(),
                              frame.arbitration_id, bytes(frame.data), frame.is_fd, frame.bitrate_switch,
                              frame.is_extended_id, frame.is_remote_frame, frame.is_error_frame,
                              frame.error_state_indicator, frame.is_rx, frame.dlc,
                              actual_channel if channel_valid else None, float(stamp) if stamp_valid else None,
                              error=None if channel_valid and stamp_valid else 'SCHEMA',
                              library_timestamp_bits=struct.pack('>d', stamp) if type(stamp) is float else None)

    def send(self, plan, *, timeout=0.01):
        timeout = self._timeout(timeout, self._group_ns / 1_000_000_000)
        with self._operation():
            item = self._authorize(plan)
            value, h = item.message, item.message['header']
            if self._last_sid != h['session_id']:
                if self._pending:
                    raise ICDError('STATE', 'retire original old-session CAN contexts before another SID')
                self._last_sid, self._last_sequence = h['session_id'], 0
            if h['sequence'] <= self._last_sequence or id(plan) in self._pending:
                raise ICDError('STATE', 'original CAN input already attempted or behind transmitted order')
            if len(self._pending) >= self._max_pending:
                raise ICDError('BUFFER_FULL', 'bounded CAN feedback contexts full')
            if value['message_id'] == 2 and any(g.plan.source_input.message['message_id'] == 2
                    and g.plan.source_input.message['header']['transaction_id'] == h['transaction_id'] for g in self._pending.values()):
                raise ICDError('STATE', 'CAN Status cannot disambiguate same-transaction Heartbeats')
            messages = self.builder._can_messages(item.frames, self.binding.interface)
            size = len(item.input_json) + sum(len(f.data) for f in item.frames) + 512
            self._capacity(len(messages) + 1, sum(self._size(self._frame_record('TX', m)) for m in messages)
                           + size + 512 + len(item.input_json))
            started = self.session._now()
            self.builder._claim_can_attempt(plan)
            group = _SentGroup(plan, started, size)
            self._pending[id(plan)] = group
            self._pending_bytes += size
            self._last_sequence = h['sequence']
            first = time.monotonic_ns()
            try:
                for frame in messages:
                    self._current_authority(item)
                    remaining = self._group_ns - (time.monotonic_ns() - first)
                    if remaining <= 0:
                        raise ICDError('TIMEOUT', 'original CAN group missed its unchanged assembly deadline')
                    index = self._record(self._frame_record('TX', frame))
                    row, completed, error = self._records[index], None, None
                    try:
                        result = self.bus.send(frame, timeout=min(timeout, remaining / 1_000_000_000))
                        if result is not None:
                            raise ICDError('RESOURCE', 'original python-can send returned an invalid result')
                        completed = True
                        self._current_authority(item)
                        if time.monotonic_ns() - first >= self._group_ns:
                            raise ICDError('TIMEOUT', 'original CAN group completed after its assembly deadline')
                    except ICDError as failure:
                        error = failure.code
                        raise
                    except Exception as failure:
                        error = 'RESOURCE'
                        raise ICDError('RESOURCE', 'original CAN send failed; complete attempt retained') from failure
                    finally:
                        self._records[index] = replace(row, send_completed=completed, error=error, completed_ns=time.monotonic_ns())
            except ICDError as failure:
                self._failure(plan, failure.code)
                raise
            group.complete = True
            return len(messages)

    def _sent(self, plan):
        self.builder._owned(plan)
        group = self._pending.get(id(plan))
        if group is None or group.plan is not plan or not group.complete:
            raise ICDError('STATE', 'actual complete original CAN TX group required for feedback')
        return group

    def _retire(self, plan):
        group = self._pending.pop(id(plan), None)
        if group is not None:
            self._pending_bytes -= group.size + sum(len(raw) for raw, _, _ in group.feedback)

    def _take_feedback(self, group):
        raw, _, _ = group.feedback[0]
        group.feedback = group.feedback[1:]
        self._pending_bytes -= len(raw)
        reply = loads(raw)
        if reply['message_id'] == 131:
            self._retire(group.plan)
        elif reply['payload']['stage'] in ('FAILED', 'APPLIED', 'CONSUMED'):
            self._retire(group.plan)
        return reply

    def receive_for(self, plan, *, timeout=0.2):
        return self._receive_for(plan, timeout=timeout, empty_ok=False)

    def poll_for(self, plan):
        return self._receive_for(plan, timeout=0, empty_ok=True)

    def _receive_for(self, plan, *, timeout, empty_ok):
        timeout = self._timeout(timeout, 10)
        with self._operation():
            self._authorize(plan)
            group = self._sent(plan)
            if group.feedback:
                return self._take_feedback(group)
            deadline = time.monotonic() + timeout
            for _ in range(256):
                self._current_authority(plan.source_input)
                remaining = deadline - time.monotonic()
                if timeout and remaining <= 0:
                    break
                self._capacity(2, 64 + 6144 + 2 * MAX_REPLY_BYTES + len(plan.source_input.input_json))
                try:
                    frame = self.bus.recv(timeout=0 if timeout == 0 else min(remaining, 0.02))
                except Exception as failure:
                    self._failure(plan, 'RESOURCE')
                    raise ICDError('RESOURCE', 'actual original CAN receive failed') from failure
                if frame is None:
                    if timeout == 0:
                        break
                    self.assembler.expire(now_ns=time.monotonic_ns())
                    continue
                index = self._record(self._frame_record('RX', frame))
                try:
                    self._current_authority(plan.source_input)
                    if self._records[index].error is not None:
                        raise ICDError('SCHEMA', 'invalid original native CAN metadata retained with wire bytes')
                    if (type(frame.dlc) is not int or frame.dlc != 64 or len(frame.data) != 64
                            or frame.is_error_frame is not False or frame.error_state_indicator is not False
                            or frame.is_rx is not True):
                        raise ICDError('SCHEMA', 'original received non-error FD64 data frame required')
                    part = self.wire.decode(CANFrame(frame.arbitration_id, bytes(frame.data), frame.is_fd,
                        frame.bitrate_switch, frame.is_extended_id, frame.is_remote_frame), 'CANFD', direction='FROM_36')
                    self._current_authority(plan.source_input)
                    candidates = [g for g in self._pending.values() if g.complete
                        and part.header.session_id == g.plan.source_input.message['header']['session_id']
                        and part.header.transaction_id == g.plan.source_input.message['header']['transaction_id']]
                    if not candidates:
                        raise ICDError('STATE', 'CAN feedback SID/transaction has no actual transmitted group')
                    result = self.assembler.push(part, channel=self.binding.channel_id, direction='FROM_36',
                                                 authorized=True, now_ns=time.monotonic_ns())
                    if result is None:
                        continue
                    reply = result.message
                    matched = []
                    completed = self.session._now()
                    for candidate in candidates:
                        try:
                            self.session._check_reply(candidate.plan.source_input.message, reply, candidate.started_ns, completed)
                            matched.append(candidate)
                        except ICDError:
                            pass
                    if len(matched) != 1:
                        raise ICDError('STATE', 'standard CAN feedback must identify one actual original request')
                    target = matched[0]
                    self._current_authority(target.plan.source_input)
                    raw = canonicalize(reply)
                    if len(target.feedback) >= 8:
                        raise ICDError('BUFFER_FULL', 'bounded original CAN feedback queue full')
                    self._capacity(1, 512 + 2 * len(raw))
                    fresh = self.session.transport._check_feedback_sequence(reply, time.monotonic_ns())
                    self.session._remember_model_feedback(target.plan.source_input.message, reply,
                        target.started_ns, completed, transport='CANFD', channel=self.binding.channel_id,
                        fresh=fresh and reply['header']['sequence'] > self.session.last_rx_sequence)
                    self.session._last_rx_sequence = max(self.session.last_rx_sequence, reply['header']['sequence'])
                    error = reply['payload']['error'] if reply['message_id'] == 130 and reply['payload']['stage'] == 'FAILED' else None
                    self._record(CANObservation('FEEDBACK', self.binding.channel_id, self.binding.interface,
                        self._records[index].started_ns, completed_ns=time.monotonic_ns(), error=error, reply_json=raw))
                    target.feedback += ((raw, completed, fresh),)
                    self._pending_bytes += len(raw)
                    if reply['message_id'] == 131 and fresh:
                        self.session._deadline_ns = max(self.session._deadline_ns, target.started_ns + self.session._lease_ms * 1_000_000)
                    if target is group:
                        return self._take_feedback(group)
                except ICDError as failure:
                    self._records[index] = replace(self._records[index], error=failure.code, completed_ns=time.monotonic_ns())
                    if failure.code in ('BUFFER_FULL', 'STALE_SESSION', 'AUTHORIZATION', 'TARGET_MISSING'):
                        raise
            if empty_ok:
                return None
            self._failure(plan, 'TIMEOUT')
            raise ICDError('TIMEOUT', 'original CAN feedback not received in bounded work and deadline')

    def retire(self, plan):
        with self._operation(closed_ok=True):
            group = self._pending.get(id(plan))
            if group is None:
                self.builder._owned(plan)
            elif group.plan is not plan:
                raise ICDError('STATE', 'actual retained original CAN context required for retirement')
            self._retire(plan)

    def drain_records(self):
        with self._operation(closed_ok=True):
            if self.session._observation_recorder is not None:
                raise ICDError('STATE', 'attached original recorder owns native record draining')
            result = tuple(self._records)
            self._records.clear()
            self._bytes = 0
            return result

    def close(self):
        with self._operation(closed_ok=True):
            if self._closed:
                return
            self._closing = True
            try:
                if self._close_retry:
                    self.bus.stop_all_periodic_tasks()
                self.bus.shutdown()
                self.book._release_can_backend(self.reservation, self)
                self._closed = True
                self._close_retry = False
            except Exception as failure:
                self._close_retry = True
                raise ICDError('RESOURCE', 'original CAN close failed; same bus/handle retained for retry') from failure
