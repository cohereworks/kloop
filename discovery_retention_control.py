#!/usr/bin/env python3
"""Deterministic control for the separate evidence-window retention diagnostic.

The control explicitly carries observed values through either the ledger or
the most recent assistant message. It never reads the evaluator's target.
"""

import json
import sys


PREFIX = "STATE:"


def retained_observations(request):
    points = {}
    ledger = request.get("ledger")
    if isinstance(ledger, dict):
        for item in ledger.get("established", []):
            if not isinstance(item, str) or "=" not in item:
                continue
            xy, value = item.split("=", 1)
            x, y = xy.split(",", 1)
            points[(int(x), int(y))] = int(value)
    history = request.get("history") or []
    if history:
        last = history[-1].get("message", "")
        if last.startswith(PREFIX):
            for row in json.loads(last[len(PREFIX):]):
                points[(row["x"], row["y"])] = row["value"]
    for row in request["observations"]:
        points[(row["x"], row["y"])] = row["value"]
    return points


def respond(request):
    points = retained_observations(request)
    modulus = request["task"]["modulus"]
    error = request.get("last_tool_error")
    if error is not None and error.get("retryable"):
        action = {"type": "probe", "x": error["x"], "y": error["y"]}
    elif request["probe_budget_remaining"] == 3:
        action = {"type": "probe", "x": 0, "y": 1}
    elif request["probe_budget_remaining"] == 2:
        action = {"type": "probe", "x": 1, "y": 1}
    else:
        # Missing observations deliberately default to zero, making loss of
        # sufficient state visible without consulting hidden target values.
        d = points.get((0, 0), 0)
        a = (points.get((1, 0), d) - d) % modulus
        b = (points.get((0, 1), d) - d) % modulus
        c = (points.get((1, 1), a + b + d) - a - b - d) % modulus
        action = {"type": "submit", "coefficients":
                  {"a": a, "b": b, "c": c, "d": d}}
    records = [{"x": x, "y": y, "value": value}
               for (x, y), value in sorted(points.items())]
    return {"action": action,
            "message": PREFIX + json.dumps(records, separators=(",", ":")),
            "ledger": {"objective": "Identify function coefficients",
                       "established": [f"{r['x']},{r['y']}={r['value']}"
                                       for r in records],
                       "falsified": [], "unresolved": [],
                       "next_action": action["type"],
                       "verification": "Retained values are public observations"}}


def respond_state_blind(request):
    """Ablate both incoming state channels while keeping the action policy."""
    from copy import deepcopy
    public = deepcopy(request)
    public["ledger"] = None
    public["history"] = []
    return respond(public)


if __name__ == "__main__":
    json.dump(respond(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")
