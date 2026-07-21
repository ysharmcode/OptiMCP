"""Deterministic path resolution over a JSON document.

Paths look like ``invoice.total``, ``line_items[0].amount`` or, for
aggregations, ``line_items[*].amount``. Grammar (informal)::

    path      := segment ('.' segment)*
    segment   := key? ('[' (int | '*') ']')*

Resolution never raises on bad data: it returns a :class:`PathError` describing
exactly what was missing so the caller can report an un-evaluable rule instead of
crashing.
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple, Union

# An accessor is one of:
#   ("key", name)   - dict lookup
#   ("index", i)    - list index
#   ("wild",)       - wildcard over a list (aggregations only)
Accessor = Union[Tuple[str, str], Tuple[str, int], Tuple[str]]

_TOKEN = re.compile(r"\.|([^.\[\]]+)|\[(\*|-?\d+)\]")


class PathError(Exception):
    """Raised when a path cannot be resolved against a document."""


def parse_path(path: str) -> List[Accessor]:
    """Parse ``path`` into an ordered list of accessors."""
    if not path or not path.strip():
        raise PathError("empty path")
    accessors: List[Accessor] = []
    pos = 0
    for m in _TOKEN.finditer(path):
        if m.start() != pos:
            raise PathError(f"malformed path near {path[pos:]!r}")
        pos = m.end()
        key, bracket = m.group(1), m.group(2)
        if m.group(0) == ".":
            continue  # segment separator
        if key is not None:
            accessors.append(("key", key))
        elif bracket == "*":
            accessors.append(("wild",))
        else:
            accessors.append(("index", int(bracket)))
    if pos != len(path):
        raise PathError(f"malformed path near {path[pos:]!r}")
    if not accessors:
        raise PathError(f"malformed path {path!r}")
    return accessors


def _walk(node: Any, accessors: List[Accessor], trail: str) -> List[Any]:
    if not accessors:
        return [node]
    acc, rest = accessors[0], accessors[1:]
    kind = acc[0]
    if kind == "key":
        name = acc[1]
        if not isinstance(node, dict):
            raise PathError(f"{trail!r} is not an object; cannot read key {name!r}")
        if name not in node:
            raise PathError(f"missing key {name!r} at {trail or '<root>'!r}")
        return _walk(node[name], rest, f"{trail}.{name}" if trail else name)
    if kind == "index":
        i = acc[1]
        if not isinstance(node, list):
            raise PathError(f"{trail!r} is not a list; cannot index [{i}]")
        if not -len(node) <= i < len(node):
            raise PathError(f"index [{i}] out of range at {trail!r} (len {len(node)})")
        return _walk(node[i], rest, f"{trail}[{i}]")
    # wildcard
    if not isinstance(node, list):
        raise PathError(f"{trail!r} is not a list; cannot wildcard [*]")
    out: List[Any] = []
    for j, el in enumerate(node):
        out.extend(_walk(el, rest, f"{trail}[{j}]"))
    return out


def resolve_ref(document: Any, path: str) -> Any:
    """Resolve a single-valued path. Raises :class:`PathError` on any problem."""
    accessors = parse_path(path)
    if any(a[0] == "wild" for a in accessors):
        raise PathError(f"ref path {path!r} must not contain a wildcard")
    values = _walk(document, accessors, "")
    return values[0]


def resolve_all(document: Any, path: str) -> List[Any]:
    """Resolve a wildcard path to the list of matched leaf values."""
    accessors = parse_path(path)
    return _walk(document, accessors, "")
