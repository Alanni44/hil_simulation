"""Strict development deployment configuration, separate from business ICD."""

from dataclasses import dataclass
import ipaddress
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from .session import PeerBinding, SessionRegistry, SourceGrant


_ENDPOINT = {"type": "object", "additionalProperties": False, "required": ["ip", "port"],
             "properties": {"ip": {"type": "string", "format": "ipv4"},
                            "port": {"type": "integer", "minimum": 1, "maximum": 65535}}}
_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["mode", "channel", "receiver_bind", "grants"],
    "properties": {
        "mode": {"enum": ["DEVELOPMENT", "FORMAL"]},
        "channel": {"enum": [f"ETH_{i}" for i in range(4)]},
        "receiver_bind": _ENDPOINT,
        "grants": {"type": "array", "minItems": 1, "maxItems": 64,
                   "items": {"type": "object", "additionalProperties": False,
                             "required": ["identity", "roles", "source_endpoint", "feedback_endpoint"],
                             "properties": {"identity": {"type": "object"},
                                            "roles": {"type": "array", "minItems": 1, "maxItems": 3,
                                                      "uniqueItems": True,
                                                      "items": {"enum": ["STIMULUS", "CONTROLLER", "OBSERVER"]}},
                                            "source_endpoint": _ENDPOINT, "feedback_endpoint": _ENDPOINT,
                                            "can_bindings": {"type":"array","minItems":1,"maxItems":4,
                                                "uniqueItems":True,"items":{"type":"object",
                                                    "additionalProperties":False,"required":["channel","interface"],
                                                    "properties":{"channel":{"enum":[f"CANFD_{i}" for i in range(4)]},
                                                        "interface":{"type":"string","pattern":"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,14}$"}}}}}}},
    },
}


def endpoint(value, *, allow_ephemeral=False):
    if not isinstance(value, tuple) or len(value) != 2 or type(value[0]) is not str or type(value[1]) is not int:
        raise ICDError("SCHEMA", "IPv4 address and integer port tuple required")
    try:
        address = ipaddress.IPv4Address(value[0])
    except ipaddress.AddressValueError as error:
        raise ICDError("SCHEMA", "invalid IPv4 deployment address") from error
    if address.is_multicast or not (0 if allow_ephemeral else 1) <= value[1] <= 65535:
        raise ICDError("SCHEMA", "invalid unicast UDP deployment endpoint")
    return str(address), value[1]


def parse_endpoint(text):
    try:
        address, port = text.rsplit(":", 1)
        if not port.isascii() or not port.isdecimal():
            raise ValueError
        return endpoint((address, int(port)))
    except (AttributeError, ValueError) as error:
        raise ICDError("SCHEMA", "endpoint must be IPv4:port") from error


@dataclass(frozen=True, slots=True)
class Deployment:
    bind: tuple
    channel: str
    grants: tuple
    feedback_routes: dict
    can_bindings: tuple = ()


def load_deployment(path, contract):
    with Path(path).open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ICDError("CAPACITY", "deployment file exceeds 64KiB")
    value = loads(raw)
    error = next(Draft202012Validator(_SCHEMA, format_checker=FormatChecker()).iter_errors(value), None)
    if error:
        raise ICDError("SCHEMA", "invalid deployment fields")
    if value["mode"] != "DEVELOPMENT":
        raise ICDError("STATE", "formal deployment unavailable: release/target gates are not implemented")
    unpack = lambda item: endpoint((item["ip"], int(item["port"])))
    bind = unpack(value["receiver_bind"])
    grants, routes, can_bindings = [], {}, []
    for item in value["grants"]:
        source = unpack(item["source_endpoint"])
        feedback = unpack(item["feedback_endpoint"])
        if source == feedback or source == bind or feedback == bind or source[0] == "0.0.0.0" or feedback[0] == "0.0.0.0":
            raise ICDError("SCHEMA", "explicit distinct TX/RX/receiver endpoint roles required")
        binding = PeerBinding(value["channel"], "UDP", f"{source[0]}:{source[1]}")
        native=[]
        for mapping in item.get('can_bindings',[]):
            interface=mapping['interface']
            if interface=='any' or re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,14}',interface) is None:
                raise ICDError('SCHEMA','explicit original single CAN interface required')
            native.append(PeerBinding(mapping['channel'],'CANFD',interface))
        if len({b.channel for b in native})!=len(native) or len({b.peer for b in native})!=len(native):
            raise ICDError('SCHEMA','CAN channels and physical interfaces must map one-to-one')
        grants.append(SourceGrant(item["identity"], tuple(item["roles"]), (binding,*native)))
        can_bindings.extend(native)
        routes[binding] = feedback
    SessionRegistry(contract, grants)
    if len({b.channel for b in can_bindings})!=len(can_bindings) or len({b.peer for b in can_bindings})!=len(can_bindings):
        raise ICDError('AUTHORIZATION','physical CAN input must have one unambiguous source grant')
    return Deployment(bind, value["channel"], tuple(grants), routes,tuple(can_bindings))
