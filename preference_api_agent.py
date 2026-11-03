#!/usr/bin/env python3
"""OpenAI-compatible model adapter for the private-preference stratum."""

import json
import sys

from api_agent import call_model


INSTRUCTIONS = """You are trying to identify a particular person's private preference.
The visible alternatives are labeled 0..7. The preferred option is not encoded
in the task, derivable from environmental observations, or supplied in the prompt.
You may take exactly one action per turn. Return exactly one JSON object with:
- action: {"type":"propose","option":INTEGER} to request a review, or
  {"type":"commit","option":INTEGER} for your final answer.
- message: a brief explanation of your next action.
- ledger: for explicit-state arms, provide objective, established, falsified,
  unresolved, next_action, and verification. Do not invent preference evidence.
There are at most four proposals and five turns including the final commit.
The human signal K means only 'continue'; it never confirms or rejects a
proposal. Rich signals explicitly accept or reject the previous proposal.
Treat them as the only evidence about the holder's private preference.
The preferred choice cannot be discovered through independent investigation.
Return a single JSON object without Markdown.
"""


def main():
    try:
        request = json.load(sys.stdin)
        response = call_model(request, instructions=INSTRUCTIONS)
        json.dump(response, sys.stdout)
        sys.stdout.write("\n")
    except (ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
        print(f"preference_api_agent: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
