"""Canonical document_hash stability."""

from optimcp.monitor.hashing import canonical_dumps, document_hash


def test_key_order_independent():
    a = {"b": 1, "a": {"z": 2, "y": 3}}
    b = {"a": {"y": 3, "z": 2}, "b": 1}
    assert document_hash(a) == document_hash(b)
    assert canonical_dumps(a) == canonical_dumps(b)


def test_number_formatting_normalized():
    assert document_hash({"n": 1}) == document_hash({"n": 1.0})
    assert document_hash({"n": 1.00}) == document_hash({"n": 1})


def test_array_order_preserved():
    assert document_hash({"xs": [1, 2]}) != document_hash({"xs": [2, 1]})


def test_stable_hex_digest_shape():
    h = document_hash({"x": 1})
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
