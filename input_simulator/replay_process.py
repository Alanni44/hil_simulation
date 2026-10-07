"""Original replay direct-child orchestration, never wire/application evidence."""

from abc import ABC, abstractmethod
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from pathlib import Path
import shutil
import threading

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from icd_runtime.wire import WireCodec
from .evidence_archive import _read_bounded
from .replay import PreparedReplay
from .replay_export import ReplayExporter
from .scenario_execution import ScenarioExecution
from .session import SourceSession
from .tool_commands import ToolCommand, ToolCommandPlan
from .tool_process import ProcessSupervisor
from .tools import ChannelReservations


class ReplayProcessAuthority(ABC):
    """Trusted runtime integration, deliberately without a successful default.

    Implementations must prove actual original endpoint/device, allocation and
    per-packet ordering, model target/control, observations and stop readiness.
    Library/process availability alone does not establish those conditions.
    Validation returns None or raises; no caller boolean becomes a wire grant.
    """
    def __init__(self, session):
        if type(session) is not SourceSession:
            raise ICDError('STATE', 'actual original replay source required')
        self.session = session

    @abstractmethod
    def preflight(self, prepared, plan):
        pass

    @abstractmethod
    def check(self, prepared, plan, *, channel_id=None):
        pass


@dataclass(frozen=True, slots=True)
class ReplayProcessRecord:
    kind: str
    command: object
    at_ns: int | None
    scheduled_ns: int | None
    process: object = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayProcessSnapshot:
    state: str
    error: str | None
    processes: tuple
    pending_cleanup: bool

    @property
    def execution_ready(self):
        return False

    @property
    def evidence_complete(self):
        return False

    @property
    def safety_verified(self):
        return False

    @property
    def tree_cleanup_verified(self):
        return False


class ReplayProcessRun:
    def __init__(self, contract, prepared, plan, bindings, reservations, reservation, *,
                 authority=None, executables=None, start_lateness_ns=1000000,
                 timeout_ms=10000, output_limit=1048576, stop_timeout_ms=1000):
        if (not isinstance(contract, Contract) or not contract.component_hashes
                or type(prepared) is not PreparedReplay or type(plan) is not ToolCommandPlan
                or type(reservations) is not ChannelReservations):
            raise ICDError('STATE', 'original verified replay resource/command owners required')
        if authority is not None and not isinstance(authority, ReplayProcessAuthority):
            raise ICDError('TARGET_MISSING', 'explicit original runtime replay authority required')
        for value, maximum in ((start_lateness_ns,1000000000),(timeout_ms,3600000),
                               (output_limit,64*1024*1024),(stop_timeout_ms,10000)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ICDError('CAPACITY', 'finite original replay process limits required')
        reservations.validate(reservation)
        if (reservation.mode != 'SEND' or reservation.branch_id not in ('CANREPLAY','ETHREPLAY')
                or plan.branch_id != reservation.branch_id or plan.run_id != reservation.run_id
                or plan.baseline_sha256 != contract.baseline_sha256
                or type(plan.commands) is not tuple or not 1 <= len(plan.commands) <= 4):
            raise ICDError('STATE', 'original one-round replay sender reservation required')
        self._contract, self._prepared, self._plan = contract, prepared, plan
        self._book, self._reservation, self._authority = reservations, reservation, authority
        self._source = None if authority is None else authority.session
        if self._source is not None and type(self._source) is not SourceSession:
            raise ICDError('STATE', 'original runtime authority source was replaced')
        self._source_contract = None if self._source is None else self._source.contract
        self._sid = None if self._source is None else self._source.session_id
        self._tool = 'canplayer' if reservation.branch_id=='CANREPLAY' else 'tcpreplay'
        if executables is not None and (type(executables) is not dict or set(executables) != {self._tool}
                or not isinstance(executables[self._tool],Path) or not executables[self._tool].is_absolute()):
            raise ICDError('SCHEMA', 'explicit literal original executable path required')
        self._configured_executable = None if executables is None else executables[self._tool]
        self._export = ReplayExporter(contract).export(prepared, bindings, epoch_ns=0)
        if self._export != plan.export or set(f.interface for f in self._export.files) != set(reservation.interfaces):
            raise ICDError('RESOURCE', 'original complete replay export/bindings differ')
        directories = []
        for command,item,descriptor in zip(plan.commands,self._export.files,self._export.report()['files']):
            if (type(command) is not ToolCommand or type(command.argv) is not tuple
                    or len(command.argv)!=(6 if self._tool=='canplayer' else 5)
                    or any(type(a) is not str or '\0' in a or len(a)>32768 for a in command.argv)):
                raise ICDError('RESOURCE','closed original literal replay command required')
            path = Path(command.argv[2] if self._tool=='canplayer' else command.argv[-1])
            argv = (('canplayer','-I',str(path),'-l','1',f'{item.interface}={item.interface}')
                    if self._tool=='canplayer' else
                    ('tcpreplay',f'--intf1={item.interface}','--loop=1','--multiplier=1.0',str(path)))
            if (not path.is_absolute() or path.name!=item.name or command.argv!=argv
                    or command.channel_id!=item.channel_id or command.resource_sha256!=item.sha256
                    or type(command.first_offset_ns) is not int
                    or command.first_offset_ns!=int(descriptor['packets'][0]['relative_offset_ns'])
                    or self._tool=='canplayer' and item.tool_timing_compatible is not True):
                raise ICDError('RESOURCE', 'original literal command/channel/timing differs')
            directories.append(path.parent)
        if len(plan.commands)!=len(self._export.files) or len(set(directories))!=1:
            raise ICDError('RESOURCE', 'complete single original export directory required')
        self._directory=directories[0]
        self._lateness=start_lateness_ns
        self._limits=dict(timeout_ms=timeout_ms,output_limit=output_limit,stop_timeout_ms=stop_timeout_ms)
        self._children=[None]*len(plan.commands)
        self._terminal_recorded=set()
        self._stop_failed=set()
        self._records=[]
        self._lock=threading.Lock()
        self._state,self._error='NEW',None
        self._epoch=self._last_now=None
        self._attempted=self._closed=False

    @contextmanager
    def _operation(self):
        if not self._lock.acquire(blocking=False):
            raise ICDError('STATE', 'one serialized original replay process owner required')
        try:
            yield
        finally:
            self._lock.release()

    @property
    def records(self):
        return tuple(self._records)

    @property
    def processes(self):
        return tuple(c.snapshot for c in self._children if c is not None)

    @property
    def snapshot(self):
        pending=False
        for child in self._children:
            if child is not None:
                status=child.snapshot
                pending=pending or (status.pid is not None and not status.direct_child_terminal)
                pending=pending or any(t.is_alive() for t in child._threads)
        return ReplayProcessSnapshot(self._state,self._error,self.processes,pending)

    def _source_check(self):
        source=self._source
        if (self._authority is None or self._authority.session is not source or type(source) is not SourceSession
                or source.contract is not self._source_contract or source.session_id!=self._sid or self._sid is None
                or source.contract.baseline_sha256!=self._contract.baseline_sha256
                or source.contract.component_hashes!=self._contract.component_hashes):
            raise ICDError('STATE','original replay authority/source identity changed')
        self._book.validate(self._reservation)
        with ExitStack() as stack:
            dispatcher=source._dispatcher
            if dispatcher is not None:
                stack.enter_context(dispatcher._operation())
            stack.enter_context(source._operation(owner=dispatcher))
            now=source._now()
            if self._last_now is not None and now<self._last_now:
                raise ICDError('CLOCK_UNSYNC','original replay local clock reversed')
            model=loads(source._identity_json)['model_id']
            wire=WireCodec(self._contract)
            for packet in self._prepared.packets:
                fragment=wire.decode(packet.wire_data,packet.transport,direction='TO_36')
                if fragment.header.session_id!=self._sid:
                    raise ICDError('STALE_SESSION','original replay headers lack current actual grant')
                source._preview_header(fragment.message_id,fragment.header.target_step,fragment.header.transaction_id)
                if model not in self._contract.entry(fragment.message_id)['model_ids']:
                    raise ICDError('MODEL','replay input belongs to another actual model')
            self._last_now=now
            return now

    def _validate_files(self):
        try:
            expected={f.name for f in self._export.files}|{'manifest.json','manifest.pending.json'}
            if self._directory.is_symlink() or {p.name for p in self._directory.iterdir()}!=expected:
                raise ICDError('RESOURCE','original export directory contents differ')
            for name,raw in [(f.name,f.data) for f in self._export.files]+[
                    ('manifest.json',self._export.report_json),('manifest.pending.json',self._export.report_json)]:
                if _read_bounded(self._directory/name,len(raw))!=raw:
                    raise ICDError('RESOURCE','original replay persistent readback differs')
        except OSError as error:
            raise ICDError('RESOURCE','original replay files unavailable') from error

    @staticmethod
    def _validated(result):
        if result is not None:
            raise ICDError('SCHEMA','runtime validation must raise or return None, never a success claim')

    def _failure(self, error):
        self._error=self._error or ScenarioExecution._error(error)
        self._state='FAILED'
        self._stop_children()
        if not any(r.kind=='FAILED' for r in self._records):
            self._records.append(ReplayProcessRecord('FAILED',None,self._last_now,None,error=self._error))

    def _stop_children(self):
        for index,child in enumerate(self._children):
            if child is not None:
                try:
                    status=child.stop()
                    if status.error:
                        raise ICDError(status.error,'original replay direct-child stop returned failure')
                except Exception as error:
                    code=ScenarioExecution._error(error)
                    self._state='FAILED'
                    self._error=self._error or code
                    if index not in self._stop_failed:
                        self._records.append(ReplayProcessRecord('STOP_FAILED',self._plan.commands[index],
                            self._last_now,None,error=code))
                        self._stop_failed.add(index)

    def start(self):
        with self._operation():
            if self._attempted or self._closed or self._state!='NEW':
                raise ICDError('STATE','original replay process starts once')
            self._attempted=True
            try:
                if self._authority is None:
                    raise ICDError('TARGET_MISSING','actual original replay runtime authority is not installed')
                self._source_check()
                self._validated(self._authority.preflight(self._prepared,self._plan))
                candidate=self._configured_executable or shutil.which(self._tool)
                if candidate is None:
                    raise ICDError('TARGET_MISSING','original replay executable unavailable; no fallback')
                self._executable=Path(candidate).resolve(strict=True)
                if not self._executable.is_file():
                    raise ICDError('TARGET_MISSING','actual original executable file required')
                self._source_check()
                self._export.write_new_directory(self._directory)
                self._validate_files()
                self._epoch=self._source_check()
                self._state='RUNNING'
                return self._poll()
            except Exception as error:
                self._failure(error)
                raise ICDError(self._error,'original replay process start failed; original handles retained') from error

    def _poll(self):
        if self._state!='RUNNING':
            return self.snapshot
        try:
            now=self._source_check()
            self._validated(self._authority.check(self._prepared,self._plan))
            for index,command in enumerate(self._plan.commands):
                scheduled=self._epoch+command.first_offset_ns
                child=self._children[index]
                if child is None and now>=scheduled:
                    self._validated(self._authority.check(self._prepared,self._plan,channel_id=command.channel_id))
                    self._validate_files()
                    now=self._source_check()
                    if now>scheduled+self._lateness:
                        raise ICDError('LATE','original channel start window missed; no catch-up launch')
                    child=ProcessSupervisor((str(self._executable),)+command.argv[1:],cwd=self._directory,**self._limits)
                    self._children[index]=child
                    started=child.start()
                    self._records.append(ReplayProcessRecord('STARTED',command,now,scheduled,started))
                if child is not None:
                    snapshot=child.poll()
                    if snapshot.error:
                        raise ICDError(snapshot.error,'original replay direct-child failed')
                    if snapshot.direct_child_terminal and snapshot.output_complete and index not in self._terminal_recorded:
                        self._records.append(ReplayProcessRecord('LOCAL_EXITED',command,now,scheduled,snapshot))
                        self._terminal_recorded.add(index)
            if len(self._terminal_recorded)==len(self._children):
                self._state='LOCAL_EXITED'
        except Exception as error:
            self._failure(error)
        return self.snapshot

    def poll(self):
        with self._operation():
            return self._poll()

    def stop(self):
        with self._operation():
            self._stop_children()
            if self._state!='FAILED':
                self._state='LOCAL_STOPPED'
            return self.snapshot

    def close(self):
        with self._operation():
            if self._closed:
                return self.snapshot
            self._stop_children()
            if self.snapshot.pending_cleanup:
                raise ICDError('STATE','same original child/reader handles require further stop; not detached')
            self._closed=True
            if self._state not in ('FAILED','LOCAL_EXITED'):
                self._state='LOCAL_STOPPED'
            return self.snapshot
