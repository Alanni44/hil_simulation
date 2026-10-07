"""Frozen negative wire preparation, never a sender or no-apply proof."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
import re
import struct

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from icd_runtime.payload import _format
from icd_runtime.wire import CANFrame, CAN_HEADER, UDP_HEADER, WireCodec, crc16, crc32
from ._native_scope import _delegated
from .session import SourceSession, _snapshot_message


CASES=('T02','T05','T06')
COMPONENT=re.compile(r'([A-Za-z_][A-Za-z0-9_]*)(?:\[(0|[1-9][0-9]*)\])?\Z')
HEADER_FIELDS={'SEQUENCE_OVERRIDE':'sequence','SESSION_OVERRIDE':'session_id',
               'TARGET_STEP_OVERRIDE':'target_step'}


@dataclass(frozen=True, slots=True)
class PreparedNegativeInput:
    source_input: object
    event_json: bytes
    mutated_frames: tuple
    mutated_payload: bytes
    mutated_header_json: bytes
    enabled_cases: tuple

    @property
    def event(self):
        return loads(self.event_json)

    @property
    def original_frames(self):
        return self.source_input.frames

    @property
    def execution_ready(self):
        return False

    @property
    def authorized_to_transmit(self):
        return False

    @property
    def qualification_status(self):
        return 'NOT_EVALUATED'

    @property
    def stored_bytes(self):
        raw=lambda frame:frame.data if type(frame) is CANFrame else frame
        return (512+len(self.event_json)+len(self.mutated_payload)+len(self.mutated_header_json)
                +len(self.source_input.message_json)+len(self.source_input.input_json)
                +sum(len(raw(f)) for f in self.original_frames+self.mutated_frames))


@contextmanager
def _source_owner(source):
    if _delegated(source):
        yield
    else:
        with source._operation():
            yield


def _tokens(path):
    result=[]
    for component in path.split('.'):
        match=COMPONENT.fullmatch(component)
        if match is None:
            raise ICDError('SCHEMA','unique structural payload path required')
        result.append(match[1])
        if match[2] is not None:
            result.append(int(match[2]))
    return tuple(result)


def _parent(payload,tokens,*,adding=False):
    value=payload
    for token in tokens[:-1]:
        if type(token) is str and type(value) is dict and token in value:
            value=value[token]
        elif type(token) is int and type(value) is list and 0 <= token < len(value):
            value=value[token]
        else:
            raise ICDError('SCHEMA','payload path does not uniquely resolve')
    token=tokens[-1]
    if type(token) is str and type(value) is dict:
        if (token in value)==adding:
            raise ICDError('SCHEMA','new field cannot overwrite; existing field must exist')
    elif type(token) is int and type(value) is list and not adding and 0 <= token < len(value):
        pass
    else:
        raise ICDError('SCHEMA','scalar payload leaf or new dictionary member required')
    return value,token


def _packed_field(entry,tokens):
    if len(tokens) not in (1,2) or type(tokens[0]) is not str:
        raise ICDError('SCHEMA','packed field has no nested object path')
    field=next((f for f in entry['fields'] if f['name']==tokens[0]),None)
    if field is None:
        raise ICDError('SCHEMA','packed field not in frozen catalogue')
    fmt,array=_format(field)
    count=int(fmt[1:-1])
    if (array and (len(tokens)!=2 or type(tokens[1]) is not int or not 0 <= tokens[1] < count)
            or not array and len(tokens)!=1):
        raise ICDError('SCHEMA','packed scalar/array leaf must be explicit')
    scalar='<'+fmt[-1]
    return field,scalar,field['offset']+(tokens[1] if array else 0)*struct.calcsize(scalar)


def _payload(entry,payload,raw,mutation):
    kind=mutation['kind']
    tokens=_tokens(mutation['field_path'])
    if entry['encoding']=='RFC8785_JSON_UTF8':
        if kind=='F64_BITS':
            raise ICDError('UNSUPPORTED','JSON cannot carry raw nonfinite IEEE754 bits')
        parent,key=_parent(payload,tokens,adding=kind=='ADD_UNKNOWN_FIELD')
        if kind=='DROP_FIELD':
            if type(parent) is list:
                parent.pop(key)
            else:
                del parent[key]
        else:
            parent[key]=mutation['value']
        return canonicalize(payload)
    if kind in ('DROP_FIELD','ADD_UNKNOWN_FIELD'):
        raise ICDError('UNSUPPORTED','fixed packed layout cannot encode missing/unknown field names')
    _parent(payload,tokens)
    field,fmt,offset=_packed_field(entry,tokens)
    result=bytearray(raw)
    if kind=='F64_BITS':
        if fmt!='<d':
            raise ICDError('UNSUPPORTED','raw IEEE754 mutation requires a frozen f64 leaf')
        result[offset:offset+8]=bytes.fromhex(mutation['bits_hex_le'])
    else:
        value=mutation['value']
        if field['type']=='u8enum' and type(value) is str:
            if value not in field['enum_codes']:
                raise ICDError('UNSUPPORTED','unknown enum text has no frozen wire code')
            value=field['enum_codes'][value]
        if fmt=='<d' and type(value) not in (int,float):
            raise ICDError('UNSUPPORTED','value cannot be represented by frozen f64 layout')
        if fmt!='<d':
            if type(value) is bool and field['type']=='u8bool':
                value=int(value)
            elif type(value) is not int:
                raise ICDError('UNSUPPORTED','value cannot be represented by frozen integer layout')
        try:
            struct.pack_into(fmt,result,offset,value)
        except (struct.error,OverflowError,TypeError) as error:
            raise ICDError('UNSUPPORTED','mutation is not representable by the frozen packed leaf') from error
    return bytes(result)


def _frames(contract,item,entry,raw,header):
    rules=contract.catalogue['codecs'][item.transport]
    size=rules['chunk_bytes']
    chunks=tuple(raw[i:i+size] for i in range(0,len(raw),size))
    if not raw or len(raw)>entry['max_logical_payload_bytes'] or len(chunks)>rules['max_fragments']:
        raise ICDError('CAPACITY','mutated payload exceeds original finite group bounds')
    result=[]
    for index,chunk in enumerate(chunks):
        # Deliberate negative headers/payload bypass only sender-side validation.
        # Framing and CRC use the exact original formal layouts, not a new codec.
        if item.transport=='CANFD':
            prefix=CAN_HEADER.pack(1,0,0,len(chunk),header['session_id'],header['sequence'],
                header['target_step'],header['transaction_id'],index,len(chunks),header['valid_for_ms'])
            body=prefix+chunk+bytes(size-len(chunk))
            checksum=crc16(struct.pack('<H',entry['can_id'])+body)
            result.append(CANFrame(entry['can_id'],body+struct.pack('<H',checksum)))
        else:
            prefix=UDP_HEADER.pack(b'HIL1',1,0,0,header['session_id'],header['sequence'],
                header['target_step'],header['transaction_id'],index,len(chunks),len(chunk),
                header['valid_for_ms'],entry['id'],0)
            result.append(prefix+struct.pack('<I',crc32(prefix+chunk))+chunk)
    return tuple(result)


def prepare_negative_input(source,item,event,*,enabled_cases,max_bytes=16*1024*1024):
    if not isinstance(source,SourceSession):
        raise ICDError('STATE','actual original source required for negative preparation')
    if (type(enabled_cases) is not tuple or not enabled_cases
            or any(type(c) is not str or c not in CASES for c in enabled_cases)
            or len(set(enabled_cases))!=len(enabled_cases)):
        raise ICDError('AUTHORIZATION','explicit distinct enabled T02/T05/T06 cases required')
    if type(max_bytes) is not int or not 1 <= max_bytes <= 64*1024*1024:
        raise ICDError('CAPACITY','finite integral negative byte capacity required')
    source.contract.validate_source_definition('Event',event)
    if event['type']!='NEGATIVE_SEND' or event['must_not_apply'] is not True:
        raise ICDError('SCHEMA','original negative event and no-apply requirement needed')
    if event['authorization_case_id'] not in enabled_cases:
        raise ICDError('AUTHORIZATION','negative case is not explicitly enabled')
    mutation=event['mutation']
    for key,value in mutation.items():
        if key in ('xor_mask','sequence','session_id','target_step','remove_tail_bytes') and type(value) is not int:
            raise ICDError('SCHEMA','mutation integers cannot normalize bool or float')
    with _source_owner(source):
        source._verify_input(item)
        value=item.message
        source.contract.validate_message(value,direction='TO_36')
        if _snapshot_message(event['stimulus'])!=_snapshot_message({'message_id':value['message_id'],'payload':value['payload']}):
            raise ICDError('RESOURCE','negative event must retain the original legal Stimulus')
        expected='UDP' if event['link_id']=='ETHGEN' else 'CANFD' if event['link_id'] in ('CANT','CUTIL','SAVVY') else None
        if expected is None or item.transport!=expected:
            raise ICDError('AUTHORIZATION','negative event must retain its original non-replay tool medium')
        wire=WireCodec(source.contract)
        if tuple(wire.encode(value,item.transport))!=item.frames:
            raise ICDError('RESOURCE','original legal frame group differs from owned input')
        entry=source.contract.entry(value['message_id'])
        raw=wire.payload_codec.encode(value['message_id'],value['payload'])
        header=dict(value['header'])
        kind=mutation['kind']
        if kind in HEADER_FIELDS:
            field=HEADER_FIELDS[kind]
            header[field]=mutation[field]
            frames=_frames(source.contract,item,entry,raw,header)
        elif kind in ('PATCH_VALUE','DROP_FIELD','ADD_UNKNOWN_FIELD','F64_BITS'):
            raw=_payload(entry,value['payload'],raw,mutation)
            frames=_frames(source.contract,item,entry,raw,header)
        else:
            frames=list(item.frames)
            index=0 if kind=='CRC_XOR' else len(frames)-1
            frame=frames[index]
            data=bytearray(frame.data if item.transport=='CANFD' else frame)
            if kind=='CRC_XOR':
                data[62 if item.transport=='CANFD' else 36]^=mutation['xor_mask']
            else:
                count=mutation['remove_tail_bytes']
                if count>=len(data):
                    raise ICDError('RANGE','truncation must leave a nonempty original final frame')
                del data[-count:]
            frames[index]=replace(frame,data=bytes(data)) if item.transport=='CANFD' else bytes(data)
            frames=tuple(frames)
        if frames==item.frames:
            raise ICDError('RESOURCE','no-op is not negative byte evidence')
        result=PreparedNegativeInput(item,_snapshot_message(event),frames,raw,_snapshot_message(header),enabled_cases)
        if result.stored_bytes>max_bytes:
            raise ICDError('CAPACITY','negative original/mutated byte evidence exceeds bound')
        source._verify_input(item)
        return result
