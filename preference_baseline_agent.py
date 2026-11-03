#!/usr/bin/env python3
"""Deterministic negative control; observes acceptance only in rich arms."""

import json
import sys


def respond(request):
    signal = request["human_signal"]
    if signal.startswith("Accepted"):
        action = {"type": "commit", "option": request["last_proposal"]}
        reason = "Preference holder accepted the previous proposal."
    elif request["proposals_remaining"]:
        action = {"type": "propose", "option": request["proposals_made"]}
        reason = "Try the next option; no acceptance is yet known."
    else:
        action = {"type": "commit", "option": 4}
        reason = "No further proposals allowed; make a fixed final guess."
    return {"action": action, "message": reason,
            "ledger": {"objective": "Identify the private favorite",
                       "established": [signal] if signal != "K" else [],
                       "falsified": [], "unresolved": ["Preference not fully observed"],
                       "next_action": action["type"],
                       "verification": "Only actual acceptance is preference evidence"}}


if __name__ == "__main__":
    json.dump(respond(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")
