#!/usr/bin/env python3
"""Deterministic negative control for the discoverable-uncertainty stratum."""

import json
import sys


def respond(request):
    observations = {(row["x"], row["y"]): row["value"]
                    for row in request["observations"]}
    p = request["task"]["modulus"]
    if (0, 1) not in observations and request["probe_budget_remaining"]:
        action = {"type": "probe", "x": 0, "y": 1}
        message = "Probe the y term independently."
    elif (1, 1) not in observations and request["probe_budget_remaining"]:
        action = {"type": "probe", "x": 1, "y": 1}
        message = "Probe the interaction term."
    else:
        d = observations[(0, 0)]
        a = (observations[(1, 0)] - d) % p
        b = (observations.get((0, 1), d) - d) % p
        c = (observations.get((1, 1), d) - a - b - d) % p
        action = {"type": "submit", "coefficients": {
            "a": a, "b": b, "c": c, "d": d}}
        message = "Solve the linear coefficients from observations."
    return {"action": action, "message": message,
            "ledger": {"objective": "Identify function coefficients",
                       "established": sorted(f"{x},{y}" for x, y in observations),
                       "falsified": [], "unresolved": ["Unobserved coefficients"],
                       "next_action": action["type"],
                       "verification": "Only observed values are known"}}


if __name__ == "__main__":
    json.dump(respond(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")
