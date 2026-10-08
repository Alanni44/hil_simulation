"""Bounded E1 reception records; never model or hardware application evidence."""

from dataclasses import dataclass
import json

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from .session import PeerBinding, SessionRegistry


@dataclass(frozen=True, slots=True)
class ReceptionRecord:
    identity_json: bytes
    message_json: bytes
    binding: PeerBinding
    received_ns: int

    @property
    def stored_bytes(self):
        return 512+len(self.identity_json)+len(self.message_json)+len(self.binding.peer.encode('utf-8'))

    @property
    def model_applied(self):
        return False

    @property
    def validation_scope(self):
        return 'WIRE_SCHEMA_SESSION_ONLY'

    def document(self):
        return {'format':'HIL_RECEPTION_RX_1','identity':loads(self.identity_json),
            'message':loads(self.message_json),'binding':{'channel':self.binding.channel,
                'transport':self.binding.transport,'peer':self.binding.peer},
            'received_ns':str(self.received_ns),'validation_scope':self.validation_scope,
            'model_applied':False,'physical_tool_qualification':'NOT_EVALUATED'}


class ReceptionService:
    def __init__(self, contract, registry, message_ids, *, max_records=4096, max_bytes=16777216):
        if (not isinstance(contract,Contract) or not contract.component_hashes
                or type(registry) is not SessionRegistry or registry.contract is not contract):
            raise ICDError('HASH','same verified reception contract/registry required')
        if (type(message_ids) is not tuple or not message_ids
                or any(type(mid) is not int for mid in message_ids)
                or len(set(message_ids))!=len(message_ids)):
            raise ICDError('SCHEMA','explicit distinct immutable reception message IDs required')
        for mid in message_ids:
            if mid in (1,2) or contract.entry(mid)['direction']!='TO_36':
                raise ICDError('UNSUPPORTED','opening/actual Status and feedback are not E1 input consumers')
        if (type(max_records) is not int or not 1<=max_records<=65536
                or type(max_bytes) is not int or not 1<=max_bytes<=128*1024*1024):
            raise ICDError('CAPACITY','bounded reception record count/bytes required')
        self.contract,self.registry=contract,registry
        self._contract,self._registry=contract,registry
        self.message_ids=tuple(sorted(message_ids))
        self._message_ids=self.message_ids
        self._max_records,self._max_bytes=max_records,max_bytes
        self._records,self._seen,self._bytes=[],set(),0
        self._closed=False

    def _check(self, *, closed_ok=False):
        if (self.contract is not self._contract or self.registry is not self._registry
                or self._registry.contract is not self._contract or self.message_ids!=self._message_ids):
            raise ICDError('STATE','original reception owners cannot be replaced')
        if self._closed and not closed_ok:
            raise ICDError('STATE','reception service closed')

    def supports(self, mid, model_id):
        self._check()
        return mid in self._message_ids and model_id in self._contract.entry(mid)['model_ids']

    @property
    def records(self):
        return tuple(self._records)

    def _snapshot(self, request, binding, now_ns):
        self._check()
        if type(binding) is not PeerBinding or type(now_ns) is not int or not 0<=now_ns<=0xffffffffffffffff:
            raise ICDError('SCHEMA','actual reception binding and uint64 clock required')
        identity=self._registry.identity(request['header']['session_id'])
        if not self.supports(request['message_id'],identity['model_id']):
            raise ICDError('TARGET_MISSING','input not installed for E1 reception')
        self._contract.validate_message(request,direction='TO_36',model_id=identity['model_id'])
        raw=json.dumps(request,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode('ascii')
        return ReceptionRecord(canonicalize(identity),raw,binding,now_ns)

    def check_capacity(self, request, binding, *, now_ns):
        record=self._snapshot(request,binding,now_ns)
        key=(request['header']['session_id'],request['header']['sequence'])
        if key in self._seen:
            return
        if len(self._records)>=self._max_records or self._bytes+record.stored_bytes>self._max_bytes:
            raise ICDError('BUFFER_FULL','save reception records before admitting another input')

    def record(self, request, binding, *, now_ns):
        self.check_capacity(request,binding,now_ns=now_ns)
        self._registry.observe_admitted(request,now_ns=now_ns)
        key=(request['header']['session_id'],request['header']['sequence'])
        if key in self._seen:
            raise ICDError('STATE','exact retry must use original cached reception response')
        record=self._snapshot(request,binding,now_ns)
        self._records.append(record)
        self._seen.add(key)
        self._bytes+=record.stored_bytes
        return record

    def close(self):
        self._check(closed_ok=True)
        self._closed=True
