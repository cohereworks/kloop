#!/usr/bin/env python3
"""Deterministic positive control for verifiable discovery-state assertions.

It sees only public observations and never opens the evaluator's target.
The underlying probe/submit policy is unchanged from the negative control.
"""

import json
import sys

from discovery_baseline_agent import respond as baseline_respond


def respond(request):
    result = baseline_respond(request)
    observed = {(row["x"], row["y"]): row["value"]
                for row in request["observations"]}
    p = request["task"]["modulus"]
    d = observed[(0, 0)]
    a = (observed[(1, 0)] - d) % p
    inferred = {"a": a, "d": d}
    if (0, 1) in observed:
        inferred["b"] = (observed[(0, 1)] - d) % p
    if (1, 1) in observed and "b" in inferred:
        inferred["c"] = (observed[(1, 1)] - a - inferred["b"] - d) % p
    result["ledger"]["inferences"] = [
        {"coefficient": name, "value": inferred[name]}
        for name in sorted(inferred)]
    result["ledger"]["unresolved"] = [
        name for name in ("a", "b", "c", "d") if name not in inferred]
    return result


if __name__ == "__main__":
    json.dump(respond(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")
