#!/usr/bin/env python3
"""Separate state-retention stress diagnostic for the discovery pilot.

The standard discovery protocol stays unchanged: it always repeats cumulative
evidence. This instrument exposes the latest evidence only, optionally hides
prior assistant messages, and preserves full evaluator-side evidence. It is a
mechanistic positive control, NOT a balanced treatment-effect comparison.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shlex
from pathlib import Path

from discovery_pilot import (CONDITIONS, SCHEMA, invoke_agent, make_tasks,
                             run_one)
from pilot import arm_schedule, canonical, write_json


RETENTION_SCHEMA = "kloop-discovery-retention-v1"


def project_visible_request(view="latest", history_window=1):
    """Return a fresh per-run model-facing request projection.

    The closure remembers how many observations were already disclosed, not
    their values. No hidden evaluator state or target crosses the boundary.
    """
    if view not in ("latest", "cumulative"):
        raise ValueError("Unknown observation view")
    if type(history_window) is not int or not 0 <= history_window <= 5:
        raise ValueError("History window must be 0..5")
    previously_disclosed = 0

    def project(request):
        nonlocal previously_disclosed
        public = copy.deepcopy(request)
        observations = public["observations"]
        if view == "latest":
            public["observations"] = observations[previously_disclosed:]
        previously_disclosed = len(observations)
        if public["condition"]["state"] == "implicit":
            public["history"] = (public["history"][-history_window:]
                                 if history_window else [])
        public["schema"] = RETENTION_SCHEMA
        public["evidence_view"] = view
        public["history_window"] = history_window
        return public

    return project


def run_retention(task, condition, adapter, view="latest", history_window=1,
                  inject_probe_failure_at=None):
    run = run_one(task, condition, adapter, max_turns=6,
                  inject_probe_failure_at=inject_probe_failure_at,
                  request_projection=project_visible_request(view, history_window))
    run["schema"] = RETENTION_SCHEMA
    run["evidence_view"] = view
    run["history_window"] = history_window
    return run


def audit_projection(run):
    """Independently replay what the agent could see, without hidden targets."""
    if run.get("schema") != RETENTION_SCHEMA:
        raise ValueError("Wrong diagnostic schema")
    previous_known, previous_feedback = [], None
    expected_ledger, expected_history = None, []
    for index, event in enumerate(run["trace"]):
        request = event["request"]
        if request.get("schema") != RETENTION_SCHEMA:
            raise ValueError("Unexpected model-facing request schema")
        if index == 0:
            if len(request["observations"]) != 2:
                raise ValueError("Initial evidence must be delivered")
            previous_known = copy.deepcopy(request["observations"])
        else:
            new = ([previous_feedback["observation"]]
                   if "observation" in previous_feedback else [])
            expected = (previous_known + new
                        if run["evidence_view"] == "cumulative" else new)
            if request["observations"] != expected:
                raise ValueError("Model-visible evidence differs from projection")
            previous_known.extend(new)
        if request.get("evidence_view") != run["evidence_view"] or (
                request.get("history_window") != run["history_window"]):
            raise ValueError("Projection metadata mismatch")
        if len(request["history"]) > (run["history_window"] if
                                      request["condition"]["state"] == "implicit"
                                      else 0):
            raise ValueError("Excess historical messages disclosed")
        if request["condition"]["state"] == "explicit":
            if request["ledger"] != expected_ledger or request["history"]:
                raise ValueError("Explicit state handoff does not match predecessor")
        elif (request["ledger"] is not None or
              request["history"] != (expected_history[-run["history_window"]:]
                                     if run["history_window"] else [])):
            raise ValueError("Implicit history handoff does not match predecessor")
        if "response" not in event:
            raise ValueError("Protocol error cannot be calibrated")
        previous_feedback = event["environment_feedback"]
        if "observation" in previous_feedback:
            action = event["response"]["action"]
            row = previous_feedback["observation"]
            if action != {"type": "probe", "x": row["x"], "y": row["y"]}:
                raise ValueError("Observation lacks matching public probe")
        expected_ledger = event["response"].get("ledger")
        expected_history.append({"turn": request["turn"],
                                 "action": event["response"]["action"],
                                 "message": event["response"].get("message", ""),
                                 "feedback": previous_feedback})
    return {"verified_requests": len(run["trace"]),
            "cumulative_observation_count_at_last_request": len(previous_known)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--arm-seed", type=int, default=20261103)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--view", choices=("latest", "cumulative"), default="latest")
    parser.add_argument("--history-window", type=int, default=1)
    parser.add_argument("--inject-probe-failure-at", type=int)
    args = parser.parse_args(argv)
    if not 0 <= args.history_window <= 5:
        parser.error("History window must be 0..5")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("Output directory must be empty")
    command = shlex.split(args.agent)
    if not command:
        parser.error("Agent command must not be empty")
    tasks = make_tasks(args.seed, args.count)
    schedule = arm_schedule([task["id"] for task in tasks["tasks"]],
                            mode="balanced", seed=args.arm_seed)
    runs = []
    for task in tasks["tasks"]:
        for condition in schedule[task["id"]]:
            target = args.out / task["id"] / f"{condition[0]}_{condition[1]}"
            target.mkdir(parents=True, exist_ok=True)

            def adapter(request):
                result, _ = invoke_agent(command, request, target, 30)
                return result

            run = run_retention(task, condition, adapter, args.view,
                                args.history_window, args.inject_probe_failure_at)
            run["projection_audit"] = audit_projection(run)
            runs.append(run)
            write_json(target / "trace.json", run)
    summary = {"schema": RETENTION_SCHEMA, "parent_schema": SCHEMA,
               "seed": args.seed, "arm_seed": args.arm_seed,
               "generated_tasks_sha256": hashlib.sha256(canonical(tasks).encode()).hexdigest(),
               "runs_sha256": hashlib.sha256(canonical(runs).encode()).hexdigest(),
               "count": args.count, "view": args.view,
               "history_window": args.history_window,
               "inject_probe_failure_at": args.inject_probe_failure_at,
               "by_arm": {f"{a}_{b}": {
                   "n": args.count,
                   "hidden_successes": sum(run["hidden_pass"] for run in runs
                                           if run["condition"] == f"{a}_{b}"),
                   "errors": sum(run["error"] is not None for run in runs
                                 if run["condition"] == f"{a}_{b}")}
                   for a, b in CONDITIONS},
               "interpretation": "Mechanistic information-availability calibration; "
                                 "not a balanced causal treatment comparison."}
    write_json(args.out / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
