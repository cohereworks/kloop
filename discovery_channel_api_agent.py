#!/usr/bin/env python3
"""Matched-channel model adapter. Same instructions in every feedback/state arm.

The carrier protocol is *not* the original discovery agent's ledger schema.
This entrypoint is exploratory; it does not attest to provider-side isolation.
"""

from __future__ import annotations

import json
import sys

from api_agent import call_model
from discovery_channel_match import MATCHED_SCHEMA


INSTRUCTIONS = """You are investigating a function f(x,y)=(a*x+b*y+c*x*y+d) mod 11.
All coefficients are integers 0..10. You see current public observations and
may either probe an unobserved point in -3..3 (consuming one successful probe)
or submit all four coefficients. A retryable tool error is not an observation;
retry it if useful. K means permission to continue, not correctness feedback.

You receive the same capacity-limited set of previous public observations in
one of two equivalent state channels, determined by request.condition.state:
- explicit: request.ledger.carry is a JSON-encoded string of facts.
- implicit: request.history[0].message is 'CARRY:' followed by that string.
On the first turn neither carrier is populated. Add any current observations.
Do not invent facts. Retain a useful subset if the UTF-8 state byte cap requires
it. Neither state channel grants additional target information.

Return exactly one JSON object with three fields: action, message, ledger.
action is either {"type":"probe","x":INTEGER,"y":INTEGER} or
{"type":"submit","coefficients":{"a":INTEGER,"b":INTEGER,"c":INTEGER,"d":INTEGER}}.
Encode retained facts as a SINGLE canonical JSON string, e.g.
{"facts":[[-1,0,7],[0,0,2]]}. Sort by x then y; no spaces, duplicate
coordinates or unsupported observations. Each x,y is in -3..3 and each value
is in 0..10. The string's UTF-8 size must not exceed request.state_budget_bytes.
Let S be exactly that encoded string. Return message exactly 'CARRY:' + S,
without any explanation. Return a ledger object with fields objective (string),
established (array), falsified (array), unresolved (array), next_action (string),
verification (string), and carry (string S). Both carriers MUST contain exactly
the same S even though only one is supplied on the next turn. No Markdown.
"""


def call_channel_model(request, *, resolved_config=None):
    condition = request.get("condition") if isinstance(request, dict) else None
    if (not isinstance(request, dict) or
            request.get("schema") != MATCHED_SCHEMA or
            not isinstance(condition, dict) or
            condition.get("state") not in ("explicit", "implicit")):
        raise ValueError("Expected a matched-channel request")
    return call_model(request, instructions=INSTRUCTIONS,
                      resolved_config=resolved_config)


def main():
    try:
        request = json.load(sys.stdin)
        response = call_channel_model(request)
        json.dump(response, sys.stdout)
        sys.stdout.write("\n")
    except (ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
        print(f"discovery_channel_api_agent: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
