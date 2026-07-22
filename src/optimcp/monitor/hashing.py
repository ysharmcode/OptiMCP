"""Canonical document hashing for audit-trail continuity.

Two semantically identical documents must produce the same SHA-256 digest even
when key order, insignificant whitespace, or number formatting differ. All store
and service code must hash via :func:`document_hash` only.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any


def _norm_number(value: float | int | Decimal) -> str:
    """Fixed decimal string form (no scientific notation, no trailing noise)."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not d.is_finite():
        return str(d)
    # Normalize then strip exponent form: Decimal('1E+2') -> '100'
    normalized = d.normalize()
    # Force fixed-point representation
    s = format(normalized, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("", "-"):
        s = "0"
    if s == "-0":
        s = "0"
    return s


def _canon(obj: Any) -> Any:
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, int) and not isinstance(obj, bool):
        return _norm_number(obj)
    if isinstance(obj, float):
        return _norm_number(obj)
    if isinstance(obj, Decimal):
        return _norm_number(obj)
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, dict):
        return {k: _canon(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, (list, tuple)):
        return [_canon(x) for x in obj]
    # Fallback: stringify unknown leaves stably
    return unicodedata.normalize("NFC", str(obj))


def canonical_dumps(document: Any) -> bytes:
    """UTF-8 canonical serialization (sorted keys, normalized numbers)."""
    return json.dumps(
        _canon(document),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def document_hash(document: Any) -> str:
    """SHA-256 hex digest of the canonical serialization."""
    return hashlib.sha256(canonical_dumps(document)).hexdigest()
