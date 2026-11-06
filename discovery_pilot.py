#!/usr/bin/env python3
"""Discoverable-uncertainty stratum: active probing of a modular function.

Unlike the expression-repair pilot, the initial observations are deliberately
insufficient to identify the target. Agents may spend turns on probes to
obtain new environmental evidence before submitting a final hypothesis.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import shlex
import subprocess
import sys
import time
from pathlib import Path

from api_agent import ModelResponseError
from pilot import CONDITIONS, STATE_FIELDS, arm_schedule, canonical, write_json


SCHEMA = "kloop-discovery-v1"
MODULUS = 11
DOMAIN = tuple(range(-3, 4))
PROBE_BUDGET = 3
COEFFICIENTS = ("a", "b", "c", "d")
INITIAL_POINTS = ((0, 0), (1, 0))


def evaluate(coefficients, x, y):
    return (coefficients["a"] * x + coefficients["b"] * y +
            coefficients["c"] * x * y + coefficients["d"]) % MODULUS


def validate_coefficients(value):
    if (not isinstance(value, dict) or set(value) != set(COEFFICIENTS) or
            any(type(value[name]) is not int or not 0 <= value[name] < MODULUS
                for name in COEFFICIENTS)):
        raise ValueError("Submit all four integer coefficients in 0..10")
    return value


def make_tasks(seed, count):
    if not 1 <= count <= 1000:
        raise ValueError("Task count must be 1..1000")
    rng = random.Random(seed)
    tasks = []
    for index in range(count):
        target = {name: rng.randrange(MODULUS) for name in COEFFICIENTS}
        initial = [{"x": x, "y": y, "value": evaluate(target, x, y)}
                   for x, y in INITIAL_POINTS]
        tasks.append({"id": f"u{index:04d}", "family": "modular_bilinear",
                      "modulus": MODULUS, "initial": initial, "_target": target})
    return {"schema": SCHEMA, "seed": seed, "tasks": tasks}


def rich_feedback(observations):
    coordinates = {(item["x"], item["y"]) for item in observations}
    if not any(y != 0 for _, y in coordinates):
        return "Only y=0 has been observed; terms involving y remain unresolved."
    if (0, 1) in coordinates and (1, 1) not in coordinates:
        return "The y term can be isolated, but the x*y interaction remains unresolved."
    return "Review whether the observations identify every coefficient before submitting."


def request_for(task, condition, turn, observations, ledger, history, remaining,
                last_tool_error=None):
    feedback, state = condition
    request = {
        "schema": SCHEMA, "condition": {"feedback": feedback, "state": state},
        "turn": turn,
        "task": {"id": task["id"], "family": task["family"],
                 "modulus": task["modulus"],
                 "model": "f(x,y)=(a*x+b*y+c*x*y+d) mod 11; coefficients in 0..10",
                 "domain": [-3, 3]},
        "observations": copy.deepcopy(observations),
        "probe_budget_remaining": remaining,
        "actions": ["probe", "submit"],
        "human_signal": "K" if feedback == "k" else rich_feedback(observations),
        "ledger": ledger if state == "explicit" else None,
        "history": history[-5:] if state == "implicit" else [],
    }
    # Both state modes need the same error evidence. In explicit mode the
    # history is intentionally absent, and ledgers are agent-controlled.
    if last_tool_error is not None:
        request["last_tool_error"] = copy.deepcopy(last_tool_error)
    return request


def validate_response(response, condition):
    if not isinstance(response, dict) or not isinstance(response.get("action"), dict):
        raise ValueError("Action object required")
    message = response.get("message", "")
    if not isinstance(message, str) or len(message) > 4000:
        raise ValueError("Invalid message")
    if condition[1] == "explicit":
        ledger = response.get("ledger")
        if (not isinstance(ledger, dict) or
                any(field not in ledger for field in STATE_FIELDS) or
                len(canonical(ledger)) > 4000):
            raise ValueError("Explicit-state ledger required")
    action = response["action"]
    if action.get("type") == "probe" and set(action) == {"type", "x", "y"}:
        if (type(action["x"]) is not int or type(action["y"]) is not int or
                action["x"] not in DOMAIN or action["y"] not in DOMAIN):
            raise ValueError("Probe must use integer coordinates in -3..3")
    elif action.get("type") == "submit" and set(action) == {"type", "coefficients"}:
        validate_coefficients(action["coefficients"])
    else:
        raise ValueError("Expected a probe or submit action")
    return response


def invoke_agent(command, request, cwd, timeout):
    start = time.monotonic()
    try:
        result = subprocess.run(command, input=canonical(request), text=True,
                                capture_output=True, cwd=cwd, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Agent timed out after {timeout}s") from exc
    if result.returncode:
        raise RuntimeError(f"Agent exit {result.returncode}: {result.stderr[:400]}")
    if len(result.stdout) > 100_000:
        raise RuntimeError("Agent output exceeds 100 KB")
    return json.loads(result.stdout), time.monotonic() - start


def run_one(task, condition, adapter, max_turns=6, max_probes=PROBE_BUDGET,
            max_total_tokens=None, inject_probe_failure_at=None,
            request_projection=None, response_validator=validate_response):
    if (inject_probe_failure_at is not None and
            (type(inject_probe_failure_at) is not int or
             not 1 <= inject_probe_failure_at <= PROBE_BUDGET)):
        raise ValueError("Fault injection probe attempt must be in 1..3")
    observations = copy.deepcopy(task["initial"])
    seen = {(row["x"], row["y"]) for row in observations}
    ledger, history, trace, error = None, [], [], None
    submitted = None
    usage_by_turn = []
    budget_exhausted = False
    probe_attempts, injected_faults = 0, 0
    pending_tool_error = None
    for turn in range(1, max_turns + 1):
        request = request_for(task, condition, turn, observations, ledger,
                              history, max_probes, pending_tool_error)
        # Optional diagnostic boundary: transform the model-facing request,
        # never the evaluator's accumulated observations or hidden target.
        # The default protocol passes the unmodified cumulative request.
        if request_projection is not None:
            request = request_projection(request)
        pending_tool_error = None
        measured, error_metrics = None, None
        try:
            raw = adapter(request)
            error_metrics = raw.get("metrics") if isinstance(raw, dict) else None
            candidate = (error_metrics or {}).get("total_tokens") if isinstance(
                error_metrics, dict) else None
            if type(candidate) is int and candidate >= 0:
                measured = candidate
            elif max_total_tokens is not None:
                raise ValueError("Measured token usage required under a token cap")
            raw = response_validator(raw, condition)
            action = raw["action"]
            if action["type"] == "probe":
                point = (action["x"], action["y"])
                if max_probes <= 0 or point in seen:
                    raise ValueError("Probe budget exhausted or duplicate probe")
                probe_attempts += 1
                if probe_attempts == inject_probe_failure_at:
                    # A failed environmental call consumes a turn, but neither
                    # discloses a target value nor spends a successful probe.
                    pending_tool_error = {"kind": "transient_probe_failure",
                                          "retryable": True,
                                          "x": point[0], "y": point[1]}
                    feedback = {"tool_error": pending_tool_error}
                    injected_faults += 1
                else:
                    max_probes -= 1
                    seen.add(point)
                    observation = {"x": point[0], "y": point[1],
                                   "value": evaluate(task["_target"], *point)}
                    observations.append(observation)
                    feedback = {"observation": observation}
            else:
                submitted = action["coefficients"]
                feedback = {"submitted": True}
            if condition[1] == "explicit":
                ledger = raw["ledger"]
            history.append({"turn": turn, "action": action,
                            "message": raw.get("message", ""), "feedback": feedback})
            trace.append({"request": request, "response": raw,
                          "environment_feedback": feedback})
            if (max_total_tokens is not None and
                    sum(t for t in usage_by_turn if t is not None) +
                    (measured or 0) >= max_total_tokens):
                budget_exhausted = True
                break
            if submitted is not None:
                break
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            if isinstance(exc, ModelResponseError):
                error_metrics = exc.metrics
                candidate = error_metrics.get("total_tokens")
                if type(candidate) is int and candidate >= 0:
                    measured = candidate
            error = f"{type(exc).__name__}: {exc}"
            event = {"request": request, "error": error}
            if isinstance(error_metrics, dict):
                event["error_metrics"] = error_metrics
            trace.append(event)
            if (max_total_tokens is not None and
                    sum(t for t in usage_by_turn if t is not None) +
                    (measured or 0) >= max_total_tokens):
                budget_exhausted = True
            break
        finally:
            usage_by_turn.append(measured)
    public_pass = (submitted is not None and
                   all(evaluate(submitted, row["x"], row["y"]) == row["value"]
                       for row in observations))
    fully_metered = bool(usage_by_turn) and all(v is not None for v in usage_by_turn)
    reported_total = sum(v for v in usage_by_turn if v is not None)
    within_budget = (True if max_total_tokens is None else
                     False if reported_total > max_total_tokens else
                     None if not fully_metered else True)
    hidden_pass = (error is None and public_pass and within_budget and
                   all(evaluate(submitted, x, y) == evaluate(task["_target"], x, y)
                       for x in DOMAIN for y in DOMAIN))
    result = {"task": task["id"], "condition": f"{condition[0]}_{condition[1]}",
            "hidden_pass": hidden_pass, "public_pass": public_pass,
            "error": error, "turns": len(trace),
            "probes": len(observations) - len(task["initial"]),
            "probe_attempts": probe_attempts,
            "injected_faults": injected_faults,
            "submitted": submitted is not None,
            "total_tokens": reported_total if fully_metered else None,
            "within_budget": within_budget, "budget_exhausted": budget_exhausted,
            "trace": trace}
    # Additive only on capped routes: historical uncapped trace digests and
    # serialized deterministic calibrations retain their exact schema.
    if max_total_tokens is not None:
        result["reported_token_lower_bound"] = reported_total
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--max-total-tokens", type=int)
    parser.add_argument("--inject-probe-failure-at", type=int,
                        help="Inject one retryable error on this probe attempt (1..3)")
    parser.add_argument("--arm-seed", type=int, default=20261103)
    args = parser.parse_args(argv)
    if not 1 <= args.max_turns <= 100 or (args.max_total_tokens is not None and
                                         args.max_total_tokens < 1):
        parser.error("Invalid resource limits")
    if (args.inject_probe_failure_at is not None and
            not 1 <= args.inject_probe_failure_at <= PROBE_BUDGET):
        parser.error("Fault injection probe attempt must be in 1..3")
    command = shlex.split(args.agent)
    if not command:
        parser.error("Agent command must not be empty")
    data = make_tasks(args.seed, args.count)
    schedule = arm_schedule([task["id"] for task in data["tasks"]],
                            mode="balanced", seed=args.arm_seed)
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("Output directory must be empty")
    runs = []
    for task in data["tasks"]:
        for condition in schedule[task["id"]]:
            run_dir = args.out / task["id"] / f"{condition[0]}_{condition[1]}"
            run_dir.mkdir(parents=True, exist_ok=True)

            def subprocess_adapter(request):
                response, _duration = invoke_agent(command, request, run_dir, 30)
                return response

            run = run_one(task, condition, subprocess_adapter, args.max_turns,
                          max_total_tokens=args.max_total_tokens,
                          inject_probe_failure_at=args.inject_probe_failure_at)
            runs.append(run)
            write_json(run_dir / "trace.json", run)
    summary = {"schema": SCHEMA, "seed": args.seed, "task_count": args.count,
               "generated_tasks_sha256": hashlib.sha256(canonical(data).encode()).hexdigest(),
               "max_turns": args.max_turns, "arm_seed": args.arm_seed,
               "max_total_tokens": args.max_total_tokens,
               "inject_probe_failure_at": args.inject_probe_failure_at,
               "execution_schedule": {task: [f"{a}_{b}" for a, b in order]
                                      for task, order in schedule.items()},
               "conditions": {f"{a}_{b}": {
                   "successes": sum(r["hidden_pass"] for r in runs
                                    if r["condition"] == f"{a}_{b}"),
                   "public_passes": sum(r["public_pass"] for r in runs
                                        if r["condition"] == f"{a}_{b}"),
                   "n": args.count} for a, b in CONDITIONS},
               "warning": "Deterministic baseline is only a negative control."}
    write_json(args.out / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
