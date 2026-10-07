"""Strict JSON domain and RFC8785 bytes; no permissive fallback encoder."""

import json
import math

import jcs

from .errors import ICDError


def check_json_domain(value, depth=0):
    if depth > 128:
        raise ICDError("SCHEMA", "JSON nesting exceeds safe parser depth")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        try:
            representable = math.isfinite(float(value)) and int(float(value)) == value
        except OverflowError:
            representable = False
        if not representable:
            raise ICDError("SCHEMA", "integer would lose precision in an IEEE754 JSON number")
    elif type(value) is float:
        if not math.isfinite(value):
            raise ICDError("SCHEMA", "NaN/Infinity not allowed")
    elif type(value) is str:
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ICDError("SCHEMA", "isolated Unicode surrogate") from exc
    elif type(value) is list:
        for item in value:
            check_json_domain(item, depth + 1)
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ICDError("SCHEMA", "JSON object keys must be strings")
            check_json_domain(key, depth + 1)
            check_json_domain(item, depth + 1)
    else:
        raise ICDError("SCHEMA", "value is outside the JSON domain")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ICDError("SCHEMA", "duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ICDError("SCHEMA", f"invalid JSON numeric literal {value}")


def loads(raw: bytes):
    if type(raw) is not bytes or raw.startswith(b"\xef\xbb\xbf"):
        raise ICDError("SCHEMA", "expected UTF8 bytes without BOM")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"),
                           object_pairs_hook=_object, parse_constant=_constant)
        check_json_domain(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError, ValueError) as exc:
        if isinstance(exc, ICDError):
            raise
        raise ICDError("SCHEMA", "invalid UTF8 JSON") from exc


def canonicalize(value) -> bytes:
    check_json_domain(value)
    try:
        return jcs.canonicalize(value)
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError) as exc:
        raise ICDError("SCHEMA", "RFC8785 serialization failed") from exc
