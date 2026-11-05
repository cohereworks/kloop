#!/usr/bin/env python3
"""Deterministic, representation-neutral control for capacity-matched channels."""

import json
import sys

from discovery_channel_codec import (EMPTY_PAYLOAD, PREFIX, decode_facts,
                                     fit_facts)


def respond(request):
    budget = request["state_budget_bytes"]
    if request["condition"]["state"] == "explicit":
        previous = (request["ledger"] or {}).get("carry", EMPTY_PAYLOAD)
    else:
        history = request["history"]
        previous = (history[-1]["message"][len(PREFIX):]
                    if history else EMPTY_PAYLOAD)
    points = decode_facts(previous, budget)
    for row in request["observations"]:
        points[(row["x"], row["y"])] = row["value"]
    modulus = request["task"]["modulus"]
    tool_error = request.get("last_tool_error")
    if tool_error and tool_error.get("retryable"):
        action = {"type": "probe", "x": tool_error["x"], "y": tool_error["y"]}
    elif request["probe_budget_remaining"] == 3:
        action = {"type": "probe", "x": 0, "y": 1}
    elif request["probe_budget_remaining"] == 2:
        action = {"type": "probe", "x": 1, "y": 1}
    else:
        d = points.get((0, 0), 0)
        a = (points.get((1, 0), d) - d) % modulus
        b = (points.get((0, 1), d) - d) % modulus
        c = (points.get((1, 1), a + b + d) - a - b - d) % modulus
        action = {"type": "submit", "coefficients":
                  {"a": a, "b": b, "c": c, "d": d}}
    carry = fit_facts(points, budget)
    # Both arms return the same response schema and bytes. The host projects
    # exactly one of the two equivalent carriers into the following request.
    return {"action": action, "message": PREFIX + carry,
            "ledger": {"objective": "retention-control", "established": [],
                       "falsified": [], "unresolved": [],
                       "next_action": action["type"], "verification": "",
                       "carry": carry}}


if __name__ == "__main__":
    json.dump(respond(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")
