#!/usr/bin/env python3
"""Canonical, capacity-bounded public-fact payload shared by two state channels.

The payload is a set of observed (x,y,value) triples, not a model-generated
summary. The same encoded UTF-8 bytes travel in explicit or implicit state.
"""

import json

from discovery_pilot import DOMAIN, MODULUS
from pilot import canonical


PREFIX = "CARRY:"
EMPTY_PAYLOAD = canonical({"facts": []})


def encode_facts(points):
    if not isinstance(points, dict):
        raise ValueError("Expected coordinate/value mapping")
    rows = []
    for point, value in sorted(points.items()):
        if (not isinstance(point, tuple) or len(point) != 2 or
                any(type(v) is not int or v not in DOMAIN for v in point) or
                type(value) is not int or not 0 <= value < MODULUS):
            raise ValueError("Invalid public fact")
        rows.append([point[0], point[1], value])
    return canonical({"facts": rows})


def decode_facts(payload, max_bytes):
    if (not isinstance(payload, str) or type(max_bytes) is not int or
            max_bytes < len(EMPTY_PAYLOAD.encode()) or
            len(payload.encode("utf-8")) > max_bytes):
        raise ValueError("Missing, invalid or over-budget carry payload")
    try:
        record = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid carry JSON") from exc
    if (not isinstance(record, dict) or set(record) != {"facts"} or
            not isinstance(record["facts"], list)):
        raise ValueError("Invalid carry shape")
    points = {}
    for fact in record["facts"]:
        if (not isinstance(fact, list) or len(fact) != 3 or
                any(type(value) is not int for value in fact) or
                fact[0] not in DOMAIN or fact[1] not in DOMAIN or
                not 0 <= fact[2] < MODULUS):
            raise ValueError("Invalid carry fact")
        key = (fact[0], fact[1])
        if key in points:
            raise ValueError("Duplicate carried coordinate")
        points[key] = fact[2]
    if encode_facts(points) != payload:
        raise ValueError("Noncanonical carry encoding")
    return points


def fit_facts(points, max_bytes):
    """Stable greedy prefix policy; it is not an optimal state compressor."""
    if type(max_bytes) is not int or max_bytes < len(EMPTY_PAYLOAD.encode()):
        raise ValueError("Capacity below empty-payload size")
    retained = {}
    for point, value in sorted(points.items()):
        candidate = {**retained, point: value}
        if len(encode_facts(candidate).encode("utf-8")) <= max_bytes:
            retained = candidate
    return encode_facts(retained)
