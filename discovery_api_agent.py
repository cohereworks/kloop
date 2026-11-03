#!/usr/bin/env python3
"""OpenAI-compatible model adapter for discovery_pilot.py's action protocol."""

import json
import sys

from api_agent import call_model


INSTRUCTIONS = """You are identifying an unknown modular bilinear function.
The task gives its formula family, modulus, initial observations, and probe budget.
You may choose one action per turn. Return exactly one JSON object with:
- action: either {"type":"probe","x":INTEGER,"y":INTEGER} to obtain a fresh
  environmental observation, or {"type":"submit","coefficients":
  {"a":INTEGER,"b":INTEGER,"c":INTEGER,"d":INTEGER}} to submit the hypothesis.
- message: brief explanation of the inference or planned probe.
- ledger: for explicit-state arms, provide objective, established, falsified,
  unresolved, next_action, and verification. Be precise; do not invent evidence.
Coordinates must be in [-3,3], coefficients in [0,10]. Probe budget is finite.
The human signal K means continue, not correctness or encouragement.
Environmental observations can identify unknown coefficients. In contrast,
unobserved data are not inferable merely because K was given. No Markdown.
"""


def main():
    try:
        request = json.load(sys.stdin)
        response = call_model(request, instructions=INSTRUCTIONS)
        json.dump(response, sys.stdout)
        sys.stdout.write("\n")
    except (ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
        print(f"discovery_api_agent: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
