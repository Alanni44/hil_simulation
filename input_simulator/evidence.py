"""Actual received claims and original bytes, never local model qualification."""

from dataclasses import dataclass
import hashlib

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import check_json_domain, loads
from icd_runtime.reassembly import Reassembler
from icd_runtime.wire import Header
from .session import MAX_COUNTER, MAX_REPLY_BYTES, SourceSession, _snapshot_message


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    kind: str
    received_ns: int
    channel: str
    peer: tuple
    wire_data: bytes | None = None
    reply_json: bytes | None = None
    request_json: bytes | None = None
    correlation_matched: bool = False
    error: str | None = None

    @property
    def reply(self):
        return None if self.reply_json is None else loads(self.reply_json)

    @property
    def request(self):
        return None if self.request_json is None else loads(self.request_json)

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'

    @property
    def stored_bytes(self):
        return 512 + sum(len(x) for x in (self.wire_data,self.reply_json,self.request_json) if x is not None)


@dataclass(frozen=True, slots=True)
class _Watch:
    header: Header
    request_json: bytes
    frames: tuple
    message_id: int
    payload_sha256: str
    event_id: str
    trace_id: str
    min_step: int
    max_step: int
    stages: tuple

    @property
    def stored_bytes(self):
        return 512 + len(self.request_json) + sum(map(len,self.frames)) + len(self.event_id.encode('utf-8')) + len(self.trace_id.encode('utf-8'))


class EvidenceInbox:
    def __init__(self, session, *, max_requests=4096, max_records=4096, max_bytes=16*1024*1024):
        if (type(max_requests) is not int or not 1 <= max_requests <= 65536 or
                type(max_records) is not int or not 1 <= max_records <= 65536 or
                type(max_bytes) is not int or not 1 <= max_bytes <= 128*1024*1024):
            raise ICDError('CAPACITY', 'bounded evidence request/record/byte limits required')
        if (not isinstance(session, SourceSession) or session.session_id is None or
                session._state != 'LIVE' or session._dispatcher is None):
            raise ICDError('STATE', 'actual granted source session required')
        self.session, self.contract = session, session.contract
        self._owner = session._dispatcher
        self.channel = session.transport.channel
        self._model = loads(session._identity_json)['model_id']
        self._sid = session.session_id
        self._available = frozenset(session.capabilities['available_probes'])
        self._probes = {p['name']:p for p in self.contract.catalogue['probe_catalog']}
        self._assembler = Reassembler(self.contract,retain_completed=False)
        self._max_requests, self._max_records, self._max_bytes = max_requests,max_records,max_bytes
        self._watches, self._tx = {}, {}
        self._context_bytes = self._record_bytes = 0
        self._records = []
        self._closed = False

    @property
    def execution_ready(self):
        return False

    @property
    def request_count(self):
        return len(self._watches)

    @property
    def records(self):
        return tuple(self._records)

    @property
    def stored_bytes(self):
        return self._context_bytes + self._record_bytes

    def _watch(self, header, request, *, event_id, trace_id, min_step, max_step, stages):
        if self._closed:
            raise ICDError('STATE', 'evidence inbox permanently closed')
        if (type(header) is not Header or header.session_id != self._sid or
                self.session.session_id != self._sid or self.session._last_now >= self.session._deadline_ns):
            raise ICDError('STALE_SESSION', 'evidence watch requires the current original session')
        for text in (event_id,trace_id):
            check_json_domain(text)
            if type(text) is not str or not 1 <= len(text) <= 128:
                raise ICDError('SCHEMA', 'explicit frozen event/trace string required')
        if (type(min_step) is not int or type(max_step) is not int or
                not 0 <= min_step <= max_step <= MAX_COUNTER or type(stages) is not tuple or
                not stages or any(type(s) is not str or s not in ('E0','E1','E2','E3') for s in stages) or
                len(set(stages)) != len(stages)):
            raise ICDError('SCHEMA', 'explicit uint32 evidence window and distinct stages required')
        if header.sequence in self._watches:
            raise ICDError('DUPLICATE', 'original request already watched')
        self.contract.validate_message(request,direction='TO_36',model_id=self._model)
        if (type(request['message_id']) is not int or
                any(type(x) is not int for x in request['header'].values())):
            raise ICDError('SCHEMA', 'original request integer types required')
        wire = self.session.transport.wire
        watch = _Watch(header,_snapshot_message(request),tuple(wire.encode(request,'UDP')),request['message_id'],
                       hashlib.sha256(wire.payload_codec.encode(request['message_id'],request['payload'])).hexdigest(),
                       event_id,trace_id,min_step,max_step,stages)
        if len(self._watches) >= self._max_requests or self.stored_bytes + watch.stored_bytes > self._max_bytes:
            raise ICDError('BUFFER_FULL', 'evidence watch context capacity full')
        self._watches[header.sequence] = watch
        self._tx[header.sequence] = set()
        self._context_bytes += watch.stored_bytes

    def _note_tx(self, header, index, packet):
        watch = self._watches.get(header.sequence)
        if watch is None:
            return
        if watch.header is not header or watch.frames[index] != packet:
            raise ICDError('STATE', 'actual TX differs from original evidence watch')
        self._tx[header.sequence].add(index)

    def _unwatch(self, header):
        watch = self._watches.get(getattr(header,'sequence',None))
        if watch is None or watch.header is not header:
            raise ICDError('STATE', 'original watched Header object required')
        self._context_bytes -= watch.stored_bytes
        del self._watches[header.sequence]
        del self._tx[header.sequence]

    def _preflight_receive(self):
        # Reserve before recv: one full datagram plus one worst-case decoded
        # record with its original request, even when a malformed peer sends it.
        request_bytes = max((len(w.request_json) for w in self._watches.values()),default=0)
        worst = 1024 + 65536 + MAX_REPLY_BYTES + request_bytes
        if self._closed:
            raise ICDError('STATE', 'evidence inbox permanently closed')
        if len(self._records) + 2 > self._max_records or self.stored_bytes + worst > self._max_bytes:
            raise ICDError('BUFFER_FULL', 'drain evidence before consuming another socket datagram')

    def _record(self, record):
        if len(self._records) >= self._max_records or self.stored_bytes + record.stored_bytes > self._max_bytes:
            raise ICDError('BUFFER_FULL', 'pre-reserved evidence capacity exhausted')
        self._records.append(record)
        self._record_bytes += record.stored_bytes

    def _datagram(self, packet, peer, now):
        self._record(EvidenceRecord('DATAGRAM',now,self.channel,tuple(peer),wire_data=packet))

    def _push(self, fragment, now):
        self._assembler.expire(now_ns=now)
        if not any(w.header.session_id == fragment.header.session_id and
                   w.header.transaction_id == fragment.header.transaction_id for w in self._watches.values()):
            raise ICDError('STATE', 'evidence fragment has no original watched SID/transaction')
        result = self._assembler.push(fragment,channel=self.channel,direction='FROM_36',authorized=True,now_ns=now)
        return None if result is None else result.message

    def _match(self, reply):
        self.contract.validate_message(reply,direction='FROM_36',model_id=self._model)
        payload,h = reply['payload'],reply['header']
        watch = self._watches.get(payload['request_sequence'])
        if watch is None:
            raise ICDError('STATE', 'evidence names no original watched request')
        now = self.session._now()
        if (self.session.session_id != self._sid or self.session._state != 'LIVE' or
                self.session._closed or now >= self.session._deadline_ns):
            raise ICDError('STALE_SESSION', 'evidence belongs to an inactive original grant')
        if len(self._tx[watch.header.sequence]) != len(watch.frames):
            raise ICDError('STATE', 'evidence request has no actual complete TX group')
        if (h['session_id'] != watch.header.session_id or h['transaction_id'] != watch.header.transaction_id or
                payload['message_id'] != watch.message_id or payload['event_id'] != watch.event_id or
                payload['trace_id'] != watch.trace_id):
            raise ICDError('STATE', 'evidence identity differs from original watch')
        if payload['payload_sha256'] != watch.payload_sha256:
            raise ICDError('HASH', 'evidence hash differs from original encoded payload')
        if payload['stage'] not in watch.stages or not watch.min_step <= payload['model_step'] <= watch.max_step:
            raise ICDError('RANGE', 'evidence stage/model step outside explicit watch')
        for key in ('request_sequence','message_id','model_step'):
            if type(payload[key]) is not int:
                raise ICDError('SCHEMA', 'evidence integers cannot be normalized floats')
        probe = self._probes[payload['probe_id']]
        if probe['id'] == 0:
            if payload['stage'] in ('E2','E3'):
                raise ICDError('TARGET_MISSING', 'applied/business stage requires an actual probe')
        else:
            if payload['probe_id'] not in self._available:
                raise ICDError('TARGET_MISSING', 'probe not published by the original actual grant')
            if 'message_id' in probe and probe['message_id'] != watch.message_id:
                raise ICDError('SCHEMA', 'consumer probe belongs to another message')
            if 'model_id' in probe:
                if probe['model_id'] != self._model:
                    raise ICDError('MODEL', 'probe belongs to another model')
                group = ('flight_control' if watch.message_id in (7,8,9,14,15,16) else
                         'environment' if watch.message_id == 10 else 'fault' if watch.message_id in (11,12,13) else
                         'parameters' if watch.message_id in (17,18,19) else None)
                if probe['target'].split('.')[0] != group or payload['stage'] == 'E3':
                    raise ICDError('SCHEMA', 'input probe cannot stand for another consumer or business output')
        if ((payload['business_result'] == 'PASS' and payload['error'] != 'OK') or
                (payload['business_result'] == 'FAIL' and payload['error'] == 'OK')):
            raise ICDError('SCHEMA', 'remote business outcome and error contradict one another')
        return watch

    def _complete(self, reply, peer, now, check_sequence):
        error,watch = None,self._watches.get(reply['payload']['request_sequence'])
        try:
            watch = self._match(reply)
            if not check_sequence(reply,now):
                raise ICDError('DUPLICATE', 'original evidence retry already collected')
        except ICDError as exc:
            error = exc.code
        self._record(EvidenceRecord('EVIDENCE',now,self.channel,tuple(peer),reply_json=_snapshot_message(reply),
                                     request_json=None if watch is None else watch.request_json,
                                     correlation_matched=error is None,error=error))
        return error is None

    def drain_records(self):
        with self._owner._operation(closed_ok=True):
            if self._owner._observation_recorder is not None:
                raise ICDError('STATE', 'original recorder owns persist-before-reclaim')
            rows = tuple(self._records)
            self._records.clear()
            self._record_bytes = 0
            return rows

    def close(self):
        with self._owner._operation(closed_ok=True):
            self._close()
            if self._owner._evidence_inbox is self:
                self._owner._evidence_inbox = None
            if self.session.transport._evidence_inbox is self:
                self.session.transport._evidence_inbox = None

    def _close(self):
        self._closed = True
        self._watches.clear()
        self._tx.clear()
        self._context_bytes = 0
        self._assembler.clear()
