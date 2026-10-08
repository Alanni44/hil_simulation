"""Original-branch installation facts and local reservations, never wire grants."""

from dataclasses import dataclass
import hashlib
import importlib.metadata
import importlib.util
from pathlib import Path
import re
import secrets
import shutil
import threading

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError


BRANCHES = (
    ('CANT', 'SIGNAL_CAN', ('cantools', 'python-can', 'SocketCAN_OR_QUALIFIED_VENDOR_SDK'), 'SEND', 'CANFD'),
    ('CUTIL', 'CAN_UTILS', ('can-utils', 'SocketCAN'), 'OBSERVE_OR_AUTHORIZED_SEND', 'CANFD'),
    ('SAVVY', 'SAVVYCAN', ('SavvyCAN', 'SocketCAN'), 'OBSERVE_OR_AUTHORIZED_SEND', 'CANFD'),
    ('CANREPLAY', 'CAN_REPLAY', ('CAN_LOG', 'canplayer', 'SocketCAN'), 'REPLAY_ONLY_VALIDATED_RAW_OR_REENCODE_UPSTREAM', 'CANFD'),
    ('ETHGEN', 'ETHERNET_GENERATOR', ('Ostinato_OR_Scapy', 'AUTOMOTIVE_ETHERNET'), 'SEND', 'UDP'),
    ('ETHREPLAY', 'PCAP_REPLAY', ('PCAP_OR_PCAPNG', 'tcpreplay', 'AUTOMOTIVE_ETHERNET'), 'RAW_VALIDATED_OR_PREPROCESSED_NEW_SESSION', 'UDP'),
)
IDS = frozenset(b[0] for b in BRANCHES)
INTERFACE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,14}')


@dataclass(frozen=True, slots=True)
class InstallationEvidence:
    kind: str
    name: str
    present: bool
    location: str | None = None
    version: str | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ToolInstallation:
    catalogue_id: str
    branch_id: str
    status: str
    reason: str
    evidence: tuple[InstallationEvidence, ...]
    pending_checks: tuple[str, ...]

    @property
    def execution_ready(self):
        return False

    def api_row(self):
        return {'branch_id': self.branch_id, 'status': self.status, 'reason': self.reason}


def _library(distribution, module):
    try:
        spec = importlib.util.find_spec(module)
        installed = importlib.metadata.distribution(distribution)
        version = installed.version
        if spec is not None and spec.origin and version and installed.files:
            origin = Path(spec.origin).resolve(strict=True)
            if any(Path(installed.locate_file(f)).resolve() == origin for f in installed.files):
                return InstallationEvidence('LIBRARY', distribution, True, str(origin), version)
    except (ImportError, ValueError, OSError, importlib.metadata.PackageNotFoundError):
        pass
    return InstallationEvidence('LIBRARY', distribution, False)


def _executable(name):
    candidate = shutil.which(name)
    if candidate:
        try:
            path = Path(candidate).resolve(strict=True)
            if path.is_file():
                digest = hashlib.sha256()
                with path.open('rb') as source:
                    while chunk := source.read(65536):
                        digest.update(chunk)
                return InstallationEvidence('EXECUTABLE', name, True, str(path), sha256=digest.hexdigest())
        except OSError:
            pass
    return InstallationEvidence('EXECUTABLE', name, False)


class ToolInventory:
    def __init__(self, contract):
        if not isinstance(contract, Contract) or not contract.component_hashes:
            raise ICDError('HASH', 'verified original tool catalogue required')
        expected = [{'id': cid, 'tools': list(tools), 'role': role,
                     'transport': transport, 'qualification': 'REQUIRED'}
                    for cid, _, tools, role, transport in BRANCHES]
        if contract.catalogue.get('toolchains') != expected:
            raise ICDError('HASH', 'six original tool branches differ from the frozen catalogue')

    def inspect(self):
        libraries = {name: _library(name, module) for name, module in
                     (('cantools', 'cantools'), ('python-can', 'can'), ('scapy', 'scapy'), ('ostinato', 'ostinato'))}
        executables = {name: _executable(name) for name in
                       ('candump', 'cansend', 'cangen', 'SavvyCAN', 'canplayer', 'tcpreplay')}
        dependencies = {
            'CANT': (libraries['cantools'], libraries['python-can']),
            'CUTIL': tuple(executables[n] for n in ('candump', 'cansend', 'cangen')),
            'SAVVY': (executables['SavvyCAN'],),
            'CANREPLAY': (executables['canplayer'],),
            'ETHGEN': (libraries['scapy'], libraries['ostinato']),
            'ETHREPLAY': (executables['tcpreplay'],),
        }
        result = []
        for cid, api, _, _, transport in BRANCHES:
            evidence = dependencies[cid]
            present = any(e.present for e in evidence) if cid == 'ETHGEN' else all(e.present for e in evidence)
            pending = ('ACTUAL_TOOL_BACKEND_AND_DEVICE', 'ACTUAL_VERSION_BUILD_QUALIFICATION',
                       'PROCESS_TREE_STOP_AND_SAFETY', 'STANDARD_AUTHORIZATION_AND_FEEDBACK',
                       'TARGET_TIMING_AND_ORIGINAL_TX_RX')
            status = 'UNVERIFIED' if present else 'UNAVAILABLE'
            reason = ('Installation inspected; actual backend, authorization and target qualification are pending.'
                      if status == 'UNVERIFIED' else
                      'Required tool dependencies were not found; no substitute backend.')
            result.append(ToolInstallation(cid, api, status, reason, evidence, pending))
        return tuple(result)


@dataclass(frozen=True, slots=True)
class ChannelReservation:
    run_id: str
    branch_id: str
    interfaces: tuple[str, ...]
    mode: str
    token: str

    @property
    def authorized_to_transmit(self):
        return False


class ChannelReservations:
    def __init__(self, *, capacity=64):
        if type(capacity) is not int or not 1 <= capacity <= 64:
            raise ICDError('CAPACITY', 'local reservation capacity must be between 1 and 64')
        self._capacity = capacity
        self._items = {}
        self._senders = {}
        self._can_backend_owners = {}
        self._lock = threading.Lock()

    @property
    def reservations(self):
        with self._lock:
            return tuple(self._items.values())

    def reserve(self, run_id, branch_id, interfaces, *, mode):
        if (type(run_id) is not str or re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}', run_id) is None
                or type(branch_id) is not str or branch_id not in IDS
                or type(interfaces) is not tuple or not 1 <= len(interfaces) <= 56
                or any(type(i) is not str or INTERFACE.fullmatch(i) is None for i in interfaces)
                or len(set(interfaces)) != len(interfaces)
                or type(mode) is not str or mode not in ('OBSERVE', 'SEND')):
            raise ICDError('SCHEMA', 'explicit original branch, run, interfaces and local mode required')
        with self._lock:
            if any(item.run_id == run_id for item in self._items.values()):
                raise ICDError('STATE', 'local run already owns a reservation')
            if mode == 'SEND' and (any(i in self._senders for i in interfaces)
                    or any(set(interfaces) & set(t.interfaces) for t, _, _ in self._can_backend_owners.values())):
                raise ICDError('STATE', 'another original branch owns a physical send interface')
            if len(self._items) >= self._capacity:
                raise ICDError('BUFFER_FULL', 'active reservations cannot be evicted')
            token = ChannelReservation(run_id, branch_id, interfaces, mode, secrets.token_hex(32))
            self._items[token.token] = token
            if mode == 'SEND':
                self._senders.update({i: token for i in interfaces})
            return token

    def release(self, token):
        with self._lock:
            if type(token) is not ChannelReservation or self._items.get(token.token) is not token:
                raise ICDError('STATE', 'reservation is foreign, forged or already released')
            if token.mode == 'SEND':
                for interface in token.interfaces:
                    del self._senders[interface]
            del self._items[token.token]

    def validate(self, token):
        """Check local identity only; callers must separately prove wire authority."""
        with self._lock:
            if type(token) is not ChannelReservation or self._items.get(token.token) is not token:
                raise ICDError('STATE', 'reservation is foreign, forged or already released')
            return token

    def _claim_can_backend(self, token, owner, bus):
        with self._lock:
            held = self._can_backend_owners.get(token.token) if type(token) is ChannelReservation else None
            retaining = held is not None and held[0] is token and held[1] is owner
            if (type(token) is not ChannelReservation or self._items.get(token.token) is not token and not retaining
                    or token.branch_id != 'CANT' or token.mode != 'SEND'):
                raise ICDError('STATE', 'actual original CANT send reservation required for native owner')
            for held, current, native in self._can_backend_owners.values():
                if current is not owner and (held is token or set(held.interfaces) & set(token.interfaces)
                                             or bus is not None and native is bus):
                    raise ICDError('STATE', 'original CAN reservation/interface/bus has another feedback owner')
            if token.token not in self._can_backend_owners and len(self._can_backend_owners) >= self._capacity:
                raise ICDError('BUFFER_FULL', 'bounded original CAN backend owners cannot be evicted')
            self._can_backend_owners[token.token] = (token, owner, bus)

    def _release_can_backend(self, token, owner):
        with self._lock:
            held = self._can_backend_owners.get(token.token)
            if held is None or held[0] is not token or held[1] is not owner:
                raise ICDError('STATE', 'only the actual original CAN owner can release its local backend')
            del self._can_backend_owners[token.token]
