"""Current-grant original-library inputs; no bus, packet sender or launch API."""

from contextlib import contextmanager
import copy
from dataclasses import asdict, dataclass
import ipaddress
import re
import threading

import can
from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether

from icd_gateway.config import endpoint
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from .protocol import ProtocolParser
from .replay_export import ExportBinding
from .session import SourceSession, _snapshot_message
from .tool_commands import ToolCommand
from .tools import ChannelReservations, INTERFACE, ToolInventory
from ._native_scope import _admit, _delegated


MAC = re.compile(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}')


@dataclass(frozen=True, slots=True)
class LiveToolInput:
    run_id: str
    branch_id: str
    binding: ExportBinding
    source_input: object
    commands: tuple[ToolCommand, ...]
    ethernet_frames: tuple[bytes, ...]
    pending_checks: tuple[str, ...]

    @property
    def execution_ready(self):
        return False

    @property
    def authorized_to_transmit(self):
        return False

    def require_execution_ready(self):
        raise ICDError('STATE', 'prepared library inputs are not actual tool, device or model authorization')


@dataclass(frozen=True, slots=True)
class FailedToolPreparation:
    binding: ExportBinding
    source_input: object


class ToolPreparationError(ICDError):
    def __init__(self, code, failure):
        self.failure = failure
        super().__init__(code, 'original tool preparation failed after owned source allocation')


class LiveToolInputBuilder:
    def __init__(self, reservations, session, *, protocol=None, capacity=64, max_bytes=8*1024*1024):
        if (type(capacity) is not int or not 1 <= capacity <= 64
                or type(max_bytes) is not int or not 1 <= max_bytes <= 64*1024*1024):
            raise ICDError('CAPACITY', 'bounded live tool plan count/bytes required')
        if type(reservations) is not ChannelReservations or not isinstance(session, SourceSession):
            raise ICDError('STATE', 'actual shared reservation book and source session required')
        ToolInventory(session.contract)
        if protocol is not None and (type(protocol) is not ProtocolParser
                or protocol.contract.baseline_sha256 != session.contract.baseline_sha256
                or protocol.contract.component_hashes != session.contract.component_hashes):
            raise ICDError('HASH', 'original parsed protocol must share the verified baseline')
        self.book, self.session, self.protocol = reservations, session, protocol
        self.contract = session.contract
        self.channels = {c['id']: c['type'] for c in self.contract.catalogue['channels']}
        self._capacity, self._maximum_bytes = capacity, max_bytes
        self._plans, self._bytes = {}, 0
        self._failed = {}
        self._lock = threading.Lock()

    @contextmanager
    def _operation(self, *, cleanup=False):
        if _admit(self.session, builder=self, cleanup=cleanup):
            yield
            return
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE', 'live tool preparation requires a serialized owner')
        try:
            yield
        finally:
            self._lock.release()

    @property
    def failed_preparations(self):
        return tuple(entry[0] for entry in self._failed.values())

    @contextmanager
    def _source_operation(self):
        if _delegated(self.session, builder=self):
            yield
        else:
            with self.session._operation():
                yield

    @staticmethod
    def _mac(value):
        if type(value) is not str or MAC.fullmatch(value) is None:
            raise ICDError('SCHEMA', 'explicit Ethernet unicast MAC required')
        raw = bytes.fromhex(value.replace(':', ''))
        if raw == b'\0'*6 or raw[0] & 1:
            raise ICDError('SCHEMA', 'Ethernet MAC must be nonzero unicast')

    def _binding(self, token, binding):
        self.book.validate(token)
        if token.mode != 'SEND' or token.branch_id not in ('CANT', 'CUTIL', 'ETHGEN'):
            raise ICDError('AUTHORIZATION', 'original live branch sender reservation required; not a wire grant')
        transport = 'UDP' if token.branch_id == 'ETHGEN' else 'CANFD'
        if (type(binding) is not ExportBinding or type(binding.channel_id) is not str
                or self.channels.get(binding.channel_id) != ('ETH' if transport == 'UDP' else 'CANFD')
                or type(binding.interface) is not str or INTERFACE.fullmatch(binding.interface) is None
                or binding.interface == 'any' or token.interfaces != (binding.interface,)):
            raise ICDError('SCHEMA', 'one explicit formal channel and reserved physical interface required')
        if transport == 'CANFD':
            if binding.source_mac is not None or binding.destination_mac is not None:
                raise ICDError('SCHEMA', 'CAN binding cannot contain Ethernet identity')
            if self.protocol is None:
                raise ICDError('STATE', 'original complete parsed protocol required for CAN tool inputs')
            self.protocol._require_parsed()
            return transport, None
        if binding.channel_id != self.session.transport.channel:
            raise ICDError('AUTHORIZATION', 'Ethernet output must remain on the actual session transport channel')
        self._mac(binding.source_mac)
        self._mac(binding.destination_mac)
        source = endpoint(getattr(self.session.transport, 'source_endpoint', None))
        receiver = endpoint(getattr(self.session.transport, 'receiver_endpoint', None))
        if any(ipaddress.IPv4Address(e[0]).is_unspecified or e[0] == '255.255.255.255' for e in (source, receiver)):
            raise ICDError('SCHEMA', 'actual explicit unicast session endpoints required')
        return transport, (source, receiver)

    @staticmethod
    def _can_messages(frames, interface):
        return tuple(can.Message(arbitration_id=f.arbitration_id, data=f.data, channel=interface,
                                 is_extended_id=False, is_remote_frame=False, is_error_frame=False,
                                 is_fd=True, bitrate_switch=True, error_state_indicator=False,
                                 is_rx=False, dlc=64, check=True) for f in frames)

    def _materialize(self, token, binding, value, frames, endpoints):
        if endpoints is None:
            original = self.protocol.encode(value)
            if original != frames:
                raise ICDError('RESOURCE', 'original cantools and source wire group differ')
            self._can_messages(frames, binding.interface)
            commands = () if token.branch_id == 'CANT' else tuple(
                ToolCommand(('cansend', binding.interface, f'{f.arbitration_id:03X}##1{f.data.hex().upper()}'), binding.channel_id)
                for f in frames)
            return commands, ()
        source, receiver = endpoints
        ethernet = tuple(bytes(Ether(src=binding.source_mac, dst=binding.destination_mac) /
            IP(src=source[0], dst=receiver[0], ttl=64) / UDP(sport=source[1], dport=receiver[1]) / raw) for raw in frames)
        return (), ethernet

    @staticmethod
    def _size(value, frames, commands, ethernet):
        return (len(canonicalize(value)) + len(_snapshot_message(value))
                + sum(len(f.data if hasattr(f, 'data') else f) for f in frames)
                + sum(sum(len(a.encode('utf-8')) for a in c.argv) for c in commands)
                + sum(map(len, ethernet)) + 1024)

    def prepare(self, token, stimulus, binding, *, target_step, transaction_id=None):
        with self._operation(), self._source_operation():
            transport, endpoints = self._binding(token, binding)
            stimulus = copy.deepcopy(stimulus)
            if type(stimulus) is not dict:
                raise ICDError('SCHEMA', 'input Stimulus object required')
            if type(stimulus.get('message_id')) is int and stimulus['message_id'] == 1:
                raise ICDError('STATE', 'live tool cannot generate a second opening request')
            self.contract.validate_stimulus(stimulus, model_id=loads(self.session._identity_json)['model_id'])
            header = self.session._preview_header(stimulus['message_id'], target_step, transaction_id)
            preview = {**stimulus, 'header': asdict(header)}
            from icd_runtime.wire import WireCodec
            frames = tuple(WireCodec(self.contract).encode(preview, transport))
            commands, ethernet = self._materialize(token, binding, preview, frames, endpoints)
            size = self._size(preview, frames, commands, ethernet)
            if len(self._plans) + len(self._failed) >= self._capacity or self._bytes + size > self._maximum_bytes:
                raise ICDError('BUFFER_FULL', 'live tool plans cannot evict prior inputs or exceed their byte bound')
            self.book.validate(token)
            item = self.session._prepare_input(stimulus, transport, target_step, transaction_id)
            # Keep the original owned source input if a tool error or revocation
            # occurs after allocation. No counter rollback or imaginary TX.
            try:
                commands, ethernet = self._materialize(token, binding, item.message, item.frames, endpoints)
                self.book.validate(token)
                self.session._verify_input(item)
            except Exception as error:
                failure = FailedToolPreparation(binding, item)
                self._failed[id(failure)] = (failure, token, size)
                self._bytes += size
                raise ToolPreparationError(error.code if isinstance(error, ICDError) else 'RESOURCE', failure) from error
            pending = ('ACTUAL_INGRESS_BINDING_AND_QUALIFIED_CHANNEL', 'ACTUAL_TOOL_BACKEND_AND_DEVICE',
                       'CURRENT_CONTROL_OWNER_MODEL_STATE_AND_TARGET_STEP', 'GLOBAL_TX_ORDER_AND_SCHEDULER',
                       'STANDARD_FEEDBACK_AND_ORIGINAL_TX_RX', 'PROCESS_TREE_STOP_AND_SAFETY')
            plan = LiveToolInput(token.run_id, token.branch_id, binding, item, commands, ethernet, pending)
            self._plans[id(plan)] = (plan, token, size)
            self._bytes += size
            return plan

    def _owned(self, plan):
        entry = self._plans.get(id(plan))
        if type(plan) is not LiveToolInput or entry is None or entry[0] is not plan:
            raise ICDError('STATE', 'actual plan from this builder required; forged/foreign/discarded plan rejected')
        return entry

    def _claim_can_attempt(self, plan):
        self._owned(plan)
        self.session._claim_can_attempt(plan.source_input)

    def validate(self, plan):
        with self._operation(), self._source_operation():
            _, token, _ = self._owned(plan)
            self.book.validate(token)
            self.session._verify_input(plan.source_input)
            return plan

    def python_can_messages(self, plan):
        self.validate(plan)
        if plan.branch_id != 'CANT':
            raise ICDError('UNSUPPORTED', 'python-can input objects belong to the original CANT branch')
        return self._can_messages(plan.source_input.frames, plan.binding.interface)

    def discard(self, plan):
        with self._operation(cleanup=True), self._source_operation():
            _, _, size = self._owned(plan)
            if any(item is plan.source_input for item in self.session.prepared_inputs):
                self.session._discard_input(plan.source_input)
            del self._plans[id(plan)]
            self._bytes -= size

    def _owned_failure(self, failure):
        entry = self._failed.get(id(failure))
        if type(failure) is not FailedToolPreparation or entry is None or entry[0] is not failure:
            raise ICDError('STATE', 'exact original failed preparation required for local recovery')
        return entry

    def discard_failed(self, failure):
        with self._operation(cleanup=True), self._source_operation():
            _, _, size = self._owned_failure(failure)
            if any(item is failure.source_input for item in self.session.prepared_inputs):
                self.session._discard_input(failure.source_input)
            del self._failed[id(failure)]
            self._bytes -= size
