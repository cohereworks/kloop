#!/usr/bin/env python3
"""Independent replay audit of exploratory matched-channel HTTP trials.

Unlike analyze_channel_match.py, this DOES NOT demand equal actions, outputs
or scores between the two channels. It verifies paired coverage, public
observations, per-run score/usage accounting and unchanged source digests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from api_agent import provider_usage
from discovery_channel_match import audit_matched_run
from discovery_channel_model_trial import SCHEMA
from discovery_pilot import DOMAIN, evaluate, make_tasks, validate_response
from pilot import CONDITIONS, arm_schedule, canonical, write_json


def replay_run(run, task, condition, max_tokens):
    if (run.get("task") != task["id"] or
            run.get("condition") != "_".join(condition) or
            run.get("turns") != len(run["trace"])):
        raise ValueError("Run metadata/turn count mismatch")
    trace = run["trace"]
    error_turns = [i for i, row in enumerate(trace) if "response" not in row]
    if error_turns not in ([], [len(trace) - 1]):
        raise ValueError("Invalid response/error trace sequence")
    prefix = trace[:-1] if error_turns else trace
    for event in prefix:
        validate_response(event["response"], condition)
    audit_error = None
    try:
        proof = audit_matched_run({**run, "trace": prefix})
    except ValueError as exc:
        audit_error = f"ChannelAuditError: {exc}"
        proof = None
    if error_turns:
        if (not isinstance(run["error"], str) or
                run["channel_audit"] is not None or audit_error):
            raise ValueError("Error or prefix audit discrepancy")
    elif audit_error is not None:
        if (run["error"] != audit_error or run["channel_audit"] is not None):
            raise ValueError("Missing channel audit disqualification")
    elif run["error"] is not None or run["channel_audit"] != proof:
        raise ValueError("Successful channel replay disagrees with trace")

    tokens = [event["response"].get("metrics", {}).get("total_tokens")
              for event in prefix]
    if any(type(value) is not int or value < 0 for value in tokens):
        raise ValueError("Unmetered successful response under token cap")
    error_metrics = (trace[-1].get("error_metrics") if error_turns else None)
    if error_turns:
        error_usage = (error_metrics.get("total_tokens")
                       if isinstance(error_metrics, dict) else None)
        tokens.append(error_usage)
    lower_bound = sum(value for value in tokens
                      if type(value) is int and value >= 0)
    if run.get("reported_token_lower_bound") != lower_bound:
        raise ValueError("Reported token lower bound disagrees with calls")
    metered = all(type(value) is int and value >= 0 for value in tokens)
    if metered:
        total = sum(tokens)
        if (run["total_tokens"] != total or
                run["within_budget"] != (total <= max_tokens) or
                run["budget_exhausted"] != (total >= max_tokens)):
            raise ValueError("Recorded token-cap accounting mismatch")
    elif (run["total_tokens"] is not None or
          run["within_budget"] != (False if lower_bound > max_tokens else None)):
        raise ValueError("Unknown-cost call incorrectly counted as metered")

    feedbacks = [event["environment_feedback"] for event in prefix]
    observed = task["initial"] + [feedback["observation"] for feedback in feedbacks
                                  if "observation" in feedback]
    submitted = [event["response"]["action"]["coefficients"]
                 for event in prefix if event["response"]["action"]["type"] == "submit"]
    if len(submitted) > 1:
        raise ValueError("Multiple submissions")
    guess = submitted[0] if submitted else None
    public_pass = guess is not None and all(
        evaluate(guess, row["x"], row["y"]) == row["value"] for row in observed)
    hidden_pass = (run["error"] is None and run["within_budget"] is True and
                   public_pass and all(evaluate(guess, x, y) ==
                                       evaluate(task["_target"], x, y)
                                       for x in DOMAIN for y in DOMAIN))
    if (run["probes"] != len(observed) - len(task["initial"]) or
            run["submitted"] != (guess is not None) or
            run["public_pass"] != public_pass or run["hidden_pass"] != hidden_pass or
            run["probe_attempts"] != sum(event["response"]["action"]["type"]
                                          == "probe" for event in prefix) or
            run["injected_faults"] != sum("tool_error" in x for x in feedbacks)):
        raise ValueError("Recorded environmental outcome/score mismatch")
    return {"usage_complete": metered,
            "metered_error_calls": int(bool(error_turns) and metered),
            "audited_turns": len(prefix), "error": run["error"]}


def analyze(root):
    root = Path(root)
    summary = json.loads((root / "summary.json").read_text())
    if summary.get("schema") != SCHEMA:
        raise ValueError("Wrong hosted-channel schema")
    tasks = make_tasks(summary["seed"], summary["count"])
    if hashlib.sha256(canonical(tasks).encode()).hexdigest() != summary["task_set_sha256"]:
        raise ValueError("Task generator digest mismatch")
    schedule = arm_schedule([t["id"] for t in tasks["tasks"]],
                            mode="balanced", seed=summary["arm_seed"])
    expected_paths = {root / task["id"] / "_".join(condition) / "trace.json"
                      for task in tasks["tasks"] for condition in schedule[task["id"]]}
    if set(root.glob("*/*/trace.json")) != expected_paths:
        raise ValueError("Incomplete or unexpected four-arm trace pairing")
    runs, checks = [], []
    for task in tasks["tasks"]:
        for condition in schedule[task["id"]]:
            path = root / task["id"] / "_".join(condition) / "trace.json"
            run = json.loads(path.read_text())
            if "_target" in json.dumps(run):
                raise ValueError("Hidden target appeared in a public trace")
            if run["state_budget_bytes"] != summary["state_budget_bytes"]:
                raise ValueError("State budget mismatch")
            checks.append(replay_run(run, task, condition, summary["max_total_tokens"]))
            runs.append(run)
    if summary["execution"] == "trusted-direct-http":
        observed_models = set()
        for run in runs:
            for event in run["trace"]:
                metrics = (event["response"].get("metrics", {})
                           if "response" in event else event.get("error_metrics"))
                if metrics is None:
                    continue  # No authenticated provider envelope was parsed.
                if (not isinstance(metrics.get("model"), str) or
                        not metrics["model"] or
                        metrics.get("usage_provenance") !=
                        "provider_response_envelope_unverified"):
                    raise ValueError("Missing trusted HTTP usage/model provenance")
                provider_usage({"usage": metrics})
                observed_models.add(metrics["model"])
        if len(observed_models) > 1:
            raise ValueError("Reported model identity drift in valid responses")
    digest = hashlib.sha256(canonical(runs).encode()).hexdigest()
    if digest != summary["runs_sha256"]:
        raise ValueError("Hosted trace digest mismatch")
    by_arm = {}
    for condition in CONDITIONS:
        key = "_".join(condition)
        selected = [r for r in runs if r["condition"] == key]
        metered = all(r["total_tokens"] is not None for r in selected)
        by_arm[key] = {"n": len(selected),
                       "hidden_successes": sum(r["hidden_pass"] for r in selected),
                       "protocol_errors": sum(r["error"] is not None for r in selected),
                       "over_budget": sum(r["within_budget"] is False for r in selected),
                       "usage_complete": metered,
                       "provider_reported_token_lower_bound": sum(
                           r["reported_token_lower_bound"] for r in selected),
                       "provider_reported_total_tokens": (
                           sum(r["total_tokens"] for r in selected) if metered else None)}
    if by_arm != summary["by_arm"]:
        raise ValueError("Hosted summary/trace disagreement")
    return {"schema": "kloop-channel-hosted-independent-audit-v1",
            "trace_digest": digest, "paired_tasks": len(tasks["tasks"]),
            "runs_replayed": len(runs),
            "response_turns_audited": sum(x["audited_turns"] for x in checks),
            "metered_error_calls": sum(x["metered_error_calls"] for x in checks),
            "unmetered_error_runs": sum(not x["usage_complete"] for x in checks),
            "by_arm": by_arm,
            "limitations": ("Provider tokens are asserted, not externally attested. "
                            "A transport/envelope failure may still be billed "
                            "without recoverable usage. "
                            "No causal inference, held-out target or provider "
                            "state isolation is certified.")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("Output file already exists")
    result = analyze(args.root)
    write_json(args.out, result)
    print(f"Independently replayed {result['runs_replayed']} hosted-channel runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
