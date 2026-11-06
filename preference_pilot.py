#!/usr/bin/env python3
"""Private-preference stratum: evaluate the information limit of all-K feedback.

There is no environmental oracle for the preferred option. The preference is
sampled independently of the public task data. In rich arms, the preference
holder accepts/rejects proposals; in K-only arms, every proposal gets K.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shlex
import subprocess
import sys
from pathlib import Path

from api_agent import ModelResponseError
from pilot import CONDITIONS, STATE_FIELDS, arm_schedule, canonical, write_json


SCHEMA = "kloop-private-preference-v1"
OPTIONS = tuple(range(8))
PROPOSAL_LIMIT = 4
TURN_LIMIT = 5


def make_tasks(seed, count):
    if not 1 <= count <= 1000:
        raise ValueError("Task count must be 1..1000")
    rng = random.Random(seed)
    tasks = []
    for start in range(0, count, len(OPTIONS)):
        choices = list(OPTIONS)
        rng.shuffle(choices)
        for preference in choices[:count - start]:
            tasks.append({"id": f"p{len(tasks):04d}",
                          "alternatives": list(OPTIONS),
                          "_preference": preference})
    return {"schema": SCHEMA, "seed": seed, "tasks": tasks}


def request_for(task, condition, turn, proposals_made, last_proposal,
                previous_response, ledger, history):
    feedback, state = condition
    if feedback == "k":
        signal = "K"
    elif previous_response is None:
        signal = "No proposal to review yet."
    else:
        signal = ("Accepted: this is the preferred option." if previous_response
                  else "Rejected: this is not the preferred option.")
    return {"schema": SCHEMA,
            "condition": {"feedback": feedback, "state": state},
            "turn": turn,
            "task": {"id": task["id"], "alternatives": task["alternatives"],
                     "goal": "Commit the preference holder's favorite option."},
            "proposals_made": proposals_made,
            "proposals_remaining": PROPOSAL_LIMIT - proposals_made,
            "last_proposal": last_proposal,
            "human_signal": signal,
            "actions": ["propose", "commit"],
            "ledger": ledger if state == "explicit" else None,
            "history": history[-5:] if state == "implicit" else []}


def validate_response(response, condition):
    if not isinstance(response, dict) or not isinstance(response.get("action"), dict):
        raise ValueError("Action object required")
    action = response["action"]
    if (set(action) != {"type", "option"} or
            action["type"] not in ("propose", "commit") or
            type(action["option"]) is not int or action["option"] not in OPTIONS):
        raise ValueError("Expected propose/commit with option 0..7")
    message = response.get("message", "")
    if not isinstance(message, str) or len(message) > 4000:
        raise ValueError("Invalid message")
    if condition[1] == "explicit":
        ledger = response.get("ledger")
        if (not isinstance(ledger, dict) or
                any(name not in ledger for name in STATE_FIELDS) or
                len(canonical(ledger)) > 4000):
            raise ValueError("Explicit-state ledger required")
    return response


def run_one(task, condition, adapter, max_turns=TURN_LIMIT,
            max_total_tokens=None):
    proposals_made, last_proposal, previous_response = 0, None, None
    ledger, history, trace, error, committed = None, [], [], None, None
    tokens = []
    capped_usage = []
    budget_exhausted = False
    for turn in range(1, max_turns + 1):
        request = request_for(task, condition, turn, proposals_made,
                              last_proposal, previous_response, ledger, history)
        measured, error_metrics = None, None
        try:
            response = adapter(request)
            error_metrics = (response.get("metrics")
                             if isinstance(response, dict) else None)
            measured = (error_metrics.get("total_tokens")
                        if isinstance(error_metrics, dict) else None)
            response = validate_response(response, condition)
            if type(measured) is int and measured >= 0:
                tokens.append(measured)
            elif max_total_tokens is not None:
                raise ValueError("Measured token usage required under a token cap")
            action = response["action"]
            if action["type"] == "propose":
                if proposals_made >= PROPOSAL_LIMIT:
                    raise ValueError("Proposal budget exhausted")
                proposals_made += 1
                last_proposal = action["option"]
                previous_response = (last_proposal == task["_preference"])
            else:
                committed = action["option"]
            if condition[1] == "explicit":
                ledger = response["ledger"]
            # Only the selected feedback channel is recorded into agent history.
            if condition[0] == "k":
                signal = "K"
            elif action["type"] == "propose":
                signal = "Accepted" if previous_response else "Rejected"
            else:
                signal = "Committed"
            history.append({"turn": turn, "action": action,
                            "human_signal": signal,
                            "message": response.get("message", "")})
            trace.append({"request": request, "response": response,
                          "human_feedback": signal})
            if max_total_tokens is not None and sum(tokens) >= max_total_tokens:
                budget_exhausted = True
                break
            if committed is not None:
                break
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            if isinstance(exc, ModelResponseError):
                error_metrics = exc.metrics
                measured = (error_metrics.get("total_tokens")
                            if isinstance(error_metrics, dict) else None)
            error = f"{type(exc).__name__}: {exc}"
            event = {"request": request, "error": error}
            if max_total_tokens is not None and isinstance(error_metrics, dict):
                event["error_metrics"] = error_metrics
            trace.append(event)
            if (max_total_tokens is not None and
                    sum(tokens) + (measured if type(measured) is int and
                                   measured >= 0 else 0) >= max_total_tokens):
                budget_exhausted = True
            break
        finally:
            if max_total_tokens is not None:
                capped_usage.append(measured if type(measured) is int and measured >= 0
                                    else None)
    known_subtotal = sum(v for v in capped_usage if v is not None)
    fully_metered = bool(capped_usage) and all(v is not None for v in capped_usage)
    within_budget = (True if max_total_tokens is None else
                     False if known_subtotal > max_total_tokens else
                     None if not fully_metered else True)
    hidden_pass = (error is None and committed == task["_preference"] and
                   within_budget is True)
    result = {"task": task["id"], "condition": f"{condition[0]}_{condition[1]}",
            "hidden_pass": hidden_pass, "public_pass": committed is not None,
            "error": error, "turns": len(trace),
            "proposals": proposals_made, "committed": committed is not None,
            "total_tokens": (known_subtotal if fully_metered else None)
            if max_total_tokens is not None else
            (sum(tokens) if len(tokens) == sum("response" in t for t in trace)
             else None), "within_budget": within_budget,
            "budget_exhausted": budget_exhausted, "trace": trace}
    if max_total_tokens is not None:
        result["reported_token_lower_bound"] = known_subtotal
    return result


def invoke_agent(command, request, cwd, timeout):
    try:
        result = subprocess.run(command, input=canonical(request), text=True,
                                capture_output=True, cwd=cwd, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Agent timed out after {timeout}s") from exc
    if result.returncode:
        raise RuntimeError(f"Agent exit {result.returncode}: {result.stderr[:400]}")
    if len(result.stdout) > 100_000:
        raise RuntimeError("Agent output exceeds 100 KB")
    return json.loads(result.stdout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--count", type=int, default=80)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-turns", type=int, default=TURN_LIMIT)
    parser.add_argument("--max-total-tokens", type=int)
    parser.add_argument("--arm-seed", type=int, default=20261103)
    args = parser.parse_args(argv)
    if (not 1 <= args.max_turns <= TURN_LIMIT or
            (args.max_total_tokens is not None and args.max_total_tokens < 1)):
        parser.error("Invalid resource limits")
    command = shlex.split(args.agent)
    if not command:
        parser.error("Agent command must not be empty")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("Output directory must be empty")
    data = make_tasks(args.seed, args.count)
    schedule = arm_schedule([t["id"] for t in data["tasks"]],
                            mode="balanced", seed=args.arm_seed)
    runs = []
    for task in data["tasks"]:
        for condition in schedule[task["id"]]:
            run_dir = args.out / task["id"] / f"{condition[0]}_{condition[1]}"
            run_dir.mkdir(parents=True, exist_ok=True)

            def adapter(request):
                return invoke_agent(command, request, run_dir, 30)

            record = run_one(task, condition, adapter, args.max_turns,
                             max_total_tokens=args.max_total_tokens)
            runs.append(record)
            write_json(run_dir / "trace.json", record)
    summary = {"schema": SCHEMA, "seed": args.seed, "task_count": args.count,
               "max_turns": args.max_turns, "max_total_tokens": args.max_total_tokens,
               "arm_seed": args.arm_seed,
               "task_manifest_sha256": hashlib.sha256(canonical(data).encode()).hexdigest(),
               "execution_schedule": {task: [f"{a}_{b}" for a, b in order]
                                      for task, order in schedule.items()},
               "conditions": {f"{a}_{b}": {
                   "n": args.count,
                   "successes": sum(r["hidden_pass"] for r in runs
                                    if r["condition"] == f"{a}_{b}")}
                   for a, b in CONDITIONS},
               "warning": "Synthetic preference baseline; no model inference."}
    write_json(args.out / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
