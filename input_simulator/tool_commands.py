"""Literal original-tool parameter plans, not a launch or wire authorization API."""

from dataclasses import dataclass
from pathlib import Path
import re

from icd_runtime.errors import ICDError
from .replay_export import ExportBinding, ReplayExport, ReplayExporter
from .tools import ChannelReservations, INTERFACE, ToolInventory


@dataclass(frozen=True, slots=True)
class ToolCommand:
    argv: tuple[str, ...]
    channel_id: str | None = None
    resource_sha256: str | None = None
    first_offset_ns: int | None = None


@dataclass(frozen=True, slots=True)
class ToolCommandPlan:
    run_id: str
    branch_id: str
    baseline_sha256: str
    commands: tuple[ToolCommand, ...]
    export: ReplayExport | None
    pending_checks: tuple[str, ...]

    @property
    def execution_ready(self):
        return False

    @property
    def authorized_to_transmit(self):
        return False

    def require_execution_ready(self):
        raise ICDError('STATE', 'tool parameters do not prove actual authorization, backend or execution readiness')


class ToolCommandBuilder:
    def __init__(self, contract, reservations):
        ToolInventory(contract)
        if type(reservations) is not ChannelReservations:
            raise ICDError('SCHEMA', 'actual shared reservation book required')
        self.contract, self.reservations = contract, reservations
        self.channels = {c['id']: c for c in contract.catalogue['channels']}

    def _bindings(self, token, bindings, transport):
        if type(bindings) is not tuple or not 1 <= len(bindings) <= 4:
            raise ICDError('SCHEMA', 'explicit one-to-one formal channel bindings required')
        channels, interfaces = set(), set()
        for binding in bindings:
            if (type(binding) is not ExportBinding or type(binding.channel_id) is not str
                    or binding.channel_id not in self.channels
                    or self.channels[binding.channel_id]['type'] != ('ETH' if transport == 'UDP' else 'CANFD')
                    or type(binding.interface) is not str or INTERFACE.fullmatch(binding.interface) is None
                    or binding.interface == 'any' or binding.channel_id in channels or binding.interface in interfaces
                    or (token.branch_id == 'CANREPLAY' and binding.interface == 'stdout')
                    or (transport == 'CANFD' and (binding.source_mac is not None or binding.destination_mac is not None))):
                raise ICDError('SCHEMA', 'binding differs from formal channel, interface or medium')
            channels.add(binding.channel_id)
            interfaces.add(binding.interface)
        if interfaces != set(token.interfaces):
            raise ICDError('SCHEMA', 'every reserved interface must bind exactly once')

    def _plan(self, token, commands, export=None):
        # Recheck after potentially lengthy export. This remains a local snapshot,
        # never an atomic reservation/authorization to launch a sender.
        self.reservations.validate(token)
        pending = ('ACTUAL_VERSION_BACKEND_AND_DEVICE_QUALIFICATION',
                   'CURRENT_SESSION_ROLE_SEQUENCE_TARGET_AND_LIFECYCLE',
                   'COMMON_START_OFFSET_SCHEDULER', 'ACTUAL_TOOL_TIMING_AND_ORIGINAL_TX_RX',
                   'PROCESS_TREE_STOP_AND_SAFETY')
        if export is not None:
            pending = tuple(dict.fromkeys(tuple(export.report()['pending_checks']) + pending))
        return ToolCommandPlan(token.run_id, token.branch_id, self.contract.baseline_sha256,
                               tuple(commands), export, pending)

    def observe(self, token, bindings):
        self.reservations.validate(token)
        if token.branch_id != 'CUTIL' or token.mode != 'OBSERVE':
            raise ICDError('AUTHORIZATION', 'candump preparation requires the original CUTIL observer reservation')
        self._bindings(token, bindings, 'CANFD')
        ids = sorted(m['can_id'] for m in self.contract.messages.values() if m['can_id'] is not None)
        filters = ','.join(f'{i:03X}:C00007FF' for i in ids)
        argv = ('candump', '-L', '-N', '-x') + tuple(b.interface + ',' + filters for b in bindings)
        return self._plan(token, (ToolCommand(argv),))

    @staticmethod
    def _directory(directory):
        if not isinstance(directory, Path):
            raise ICDError('RESOURCE', 'new absolute export directory required')
        try:
            if (not directory.is_absolute() or '\x00' in str(directory)
                    or re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}', directory.name) is None
                    or directory.exists() or directory.is_symlink()
                    or not directory.parent.resolve(strict=True).is_dir()):
                raise ICDError('RESOURCE', 'new literal export directory with existing parent required')
            return directory.parent.resolve(strict=True) / directory.name
        except (OSError, ValueError) as error:
            raise ICDError('RESOURCE', 'export directory cannot be resolved') from error

    def replay(self, token, prepared, bindings, *, directory):
        self.reservations.validate(token)
        if token.mode != 'SEND' or token.branch_id not in ('CANREPLAY', 'ETHREPLAY'):
            raise ICDError('AUTHORIZATION', 'original replay branch sender reservation required; it is not a wire grant')
        transport = 'CANFD' if token.branch_id == 'CANREPLAY' else 'UDP'
        # Report a medium mismatch separately from malformed bindings.
        if (type(bindings) is tuple and any(type(b) is ExportBinding and type(b.channel_id) is str
                and b.channel_id in self.channels
                and self.channels[b.channel_id]['type'] != ('ETH' if transport == 'UDP' else 'CANFD')
                for b in bindings)):
            raise ICDError('UNSUPPORTED', 'original tool does not replay this medium')
        self._bindings(token, bindings, transport)
        directory = self._directory(directory)
        bundle = ReplayExporter(self.contract).export(prepared, bindings, epoch_ns=0)
        if set(f.interface for f in bundle.files) != set(token.interfaces):
            raise ICDError('SCHEMA', 'export omitted a reserved channel')
        commands = []
        for item, descriptor in zip(bundle.files, bundle.report()['files']):
            path = str(directory / item.name)
            if item.format == 'CAN_LOG':
                if item.tool_timing_compatible is not True:
                    raise ICDError('UNSUPPORTED', 'canplayer cannot faithfully express the exported relative timing')
                argv = ('canplayer', '-I', path, '-l', '1', f'{item.interface}={item.interface}')
            else:
                argv = ('tcpreplay', f'--intf1={item.interface}', '--loop=1', '--multiplier=1.0', path)
            first = int(descriptor['packets'][0]['relative_offset_ns'])
            commands.append(ToolCommand(argv, item.channel_id, item.sha256, first))
        return self._plan(token, commands, bundle)
