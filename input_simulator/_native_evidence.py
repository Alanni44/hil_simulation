"""Lossless closed native observation rows, not an ICD or qualification."""

import base64
import binascii
from dataclasses import fields
import math
import re
import struct

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, check_json_domain, loads
from .can_signal import CANObservation
from .scapy_source import L2Transmission


NATIVE_TYPES = {'CAN': CANObservation, 'L2': L2Transmission}
BYTES = {'data', 'reply_json', 'request_json', 'library_timestamp_bits', 'ethernet_data', 'udp_data'}
TIMES = {'started_ns', 'completed_ns'}
CAN_INTS = {'arbitration_id', 'dlc'}
FLAGS = {'is_fd', 'bitrate_switch', 'is_extended_id', 'is_remote_frame',
         'is_error_frame', 'error_state_indicator', 'is_rx', 'send_completed'}


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ICDError('RESOURCE', 'native observation integer type/range invalid')
    return value


def _decimal(value, minimum, maximum):
    if type(value) is not str or re.fullmatch(r'0|-?[1-9][0-9]{0,19}', value) is None:
        raise ICDError('RESOURCE', 'native observation integer must be a canonical decimal string')
    return _integer(int(value), minimum, maximum)


def _text(value, *, empty=False):
    check_json_domain(value)
    if type(value) is not str or not (0 if empty else 1) <= len(value) <= 1024:
        raise ICDError('RESOURCE', 'native observation text type/size invalid')
    return value


def encode_native_record(stream, record):
    if type(stream) is not str or stream not in NATIVE_TYPES or type(record) is not NATIVE_TYPES[stream]:
        raise ICDError('STATE', 'actual typed native observation required')
    row = {}
    for field in fields(record):
        name, value = field.name, getattr(record, field.name)
        if value is not None:
            if name in BYTES:
                if type(value) is not bytes:
                    raise ICDError('STATE', 'immutable native observation bytes required')
                value = base64.b64encode(value).decode('ascii')
            elif name in TIMES or name in CAN_INTS:
                value = str(_integer(value, 0 if name in TIMES else -(2**63), 2**64-1))
            elif name == 'library_timestamp':
                if type(value) is not float:
                    raise ICDError('STATE', 'original native timestamp must be an IEEE754 float')
                # RFC8785 erases negative zero; retain the exact observed double.
                value = struct.pack('>d', value).hex()
            elif name == 'actual_channel':
                if type(value) is int:
                    value = {'type': 'INTEGER', 'value': str(_integer(value, -(2**63), 2**63-1))}
                elif type(value) is str:
                    value = {'type': 'STRING', 'value': value}
                else:
                    raise ICDError('STATE', 'original native channel metadata required')
        row[name] = value
    result = {'stream': stream, 'record': row}
    decode_native_record(result)
    return canonicalize(result) + b'\n'


def decode_native_record(row):
    try:
        if (type(row) is not dict or set(row) != {'stream', 'record'}
                or type(row['stream']) is not str or row['stream'] not in NATIVE_TYPES):
            raise ICDError('RESOURCE', 'closed native observation stream required')
        stream, value = row['stream'], row['record']
        cls = NATIVE_TYPES[stream]
        if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
            raise ICDError('RESOURCE', 'closed native observation fields required')
        decoded = {}
        for name, item in value.items():
            if name in BYTES and item is not None:
                if type(item) is not str:
                    raise ICDError('RESOURCE', 'native bytes must be canonical base64')
                raw = base64.b64decode(item, validate=True)
                if base64.b64encode(raw).decode('ascii') != item:
                    raise ICDError('RESOURCE', 'noncanonical native base64')
                if name.endswith('_json'):
                    loads(raw)
                if name == 'library_timestamp_bits' and len(raw) != 8:
                    raise ICDError('RESOURCE', 'original native timestamp bits must be eight bytes')
                item = raw
            elif name in TIMES:
                if item is None:
                    if name == 'started_ns':
                        raise ICDError('RESOURCE', 'native observation start time required')
                else:
                    item = _decimal(item, 0, 2**64-1)
            elif name in CAN_INTS and item is not None:
                item = _decimal(item, -(2**63), 2**64-1)
            elif name in FLAGS and item is not None:
                if type(item) is not bool:
                    raise ICDError('RESOURCE', 'native observation flag must be boolean')
            elif name == 'library_timestamp' and item is not None:
                if type(item) is not str or re.fullmatch('[0-9a-f]{16}', item) is None:
                    raise ICDError('RESOURCE', 'native timestamp must preserve exact IEEE754 bits')
                item = struct.unpack('>d', bytes.fromhex(item))[0]
                if not math.isfinite(item) or not 0 <= item <= 2**63-1:
                    raise ICDError('RESOURCE', 'invalid library timestamp belongs in original failure bits only')
            elif name == 'actual_channel' and item is not None:
                if type(item) is not dict or set(item) != {'type', 'value'}:
                    raise ICDError('RESOURCE', 'tagged original native channel metadata required')
                if item['type'] == 'INTEGER':
                    item = _decimal(item['value'], -(2**63), 2**63-1)
                elif item['type'] == 'STRING':
                    item = _text(item['value'], empty=True)
                else:
                    raise ICDError('RESOURCE', 'unknown native channel metadata type')
            elif name == 'kind':
                if type(item) is not str or item not in ('TX', 'RX', 'FEEDBACK', 'FAILED'):
                    raise ICDError('RESOURCE', 'unknown original CAN observation kind')
            elif name == 'channel_id':
                if type(item) is not str or item not in tuple(f'CANFD_{i}' for i in range(4)):
                    raise ICDError('RESOURCE', 'original formal CAN channel required')
            elif name == 'interface':
                _text(item)
            elif name == 'error' and item is not None:
                _text(item)
            elif name == 'sent_bytes' and item is not None:
                _integer(item, 0, 2**32-1)
            elif name == 'qualification_status':
                if item != 'NOT_EVALUATED':
                    raise ICDError('RESOURCE', 'native observations cannot promote qualification')
            decoded[name] = item
        if decoded['completed_ns'] is not None and decoded['completed_ns'] < decoded['started_ns']:
            raise ICDError('RESOURCE', 'native observation completion precedes actual start')
        if stream == 'CAN':
            stamp, bits = decoded['library_timestamp'], decoded['library_timestamp_bits']
            if stamp is not None and bits is not None and struct.pack('>d', stamp) != bits:
                raise ICDError('RESOURCE', 'native timestamp differs from its original bits')
        elif decoded['ethernet_data'] is None or decoded['udp_data'] is None:
            raise ICDError('RESOURCE', 'original Ethernet and UDP bytes required')
        return cls(**decoded)
    except (ICDError, TypeError, ValueError, KeyError, binascii.Error) as error:
        raise ICDError('RESOURCE', 'native observation closed structure invalid') from error
