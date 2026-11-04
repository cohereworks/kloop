#!/usr/bin/env python3
"""Audit discovery traces for transient-tool recovery and false-public-success.

This is a trace-derived, descriptive diagnostic, not a causal estimate or
model-reliability certification. The preference stratum is intentionally
excluded: there ``public_pass`` means commitment rather than success.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_trial import ARMS, load_runs, pair_runs
from discovery_pilot import SCHEMA


def audit_run(run):
    """Verify fault/probe accounting against the immutable run trace."""
    arm = run["condition"]
    if (type(run.get("public_pass")) is not bool or
            type(run.get("hidden_pass")) is not bool or
            type(run.get("turns")) is not int or
            type(run.get("probes")) is not int or
            not isinstance(run.get("trace"), list) or
            run["turns"] != len(run["trace"])):
        raise ValueError(f"Malformed discovery outcome for {run['task']}/{arm}")
    events = run["trace"]
    if not events:
        raise ValueError(f"Empty trace for {run['task']}/{arm}")
    fault_events, probe_successes, attempts = [], 0, 0
    expected_observations, expected_remaining, expected_error = None, None, None
    seen = set()
    for index, event in enumerate(events):
        request = event.get("request")
        if (not isinstance(request, dict) or request.get("schema") != SCHEMA or
                not isinstance(request.get("condition"), dict) or
                f'{request["condition"].get("feedback")}_'
                f'{request["condition"].get("state")}' != arm or
                request.get("turn") != index + 1):
            raise ValueError(f"Unexpected stratum/condition/turn in {run['task']}/{arm}")
        if expected_observations is None:
            initial = request.get("observations")
            if not isinstance(initial, list) or not initial:
                raise ValueError("Missing initial observations")
            expected_observations = initial.copy()
            expected_remaining = request.get("probe_budget_remaining")
            if type(expected_remaining) is not int or expected_remaining < 0:
                raise ValueError("Invalid initial probe budget")
            seen = {(row["x"], row["y"]) for row in initial}
        if (request.get("observations") != expected_observations or
                request.get("probe_budget_remaining") != expected_remaining):
            raise ValueError("Observations or probe budget changed without evidence")
        if request.get("last_tool_error") != expected_error:
            raise ValueError("Next request did not receive correct fault evidence")
        expected_error = None
        response = event.get("response")
        feedback = event.get("environment_feedback")
        if response is None:
            if "error" not in event or index != len(events) - 1:
                raise ValueError("Unexplained missing response or nonterminal error")
            continue
        if not isinstance(response, dict) or not isinstance(feedback, dict):
            raise ValueError("Missing response or environment feedback")
        action = response.get("action", {})
        if not isinstance(action, dict):
            raise ValueError("Malformed action")
        if action.get("type") == "probe":
            attempts += 1
            point = (action.get("x"), action.get("y"))
            if expected_remaining <= 0 or point in seen:
                raise ValueError("Probe violates available budget or duplicates evidence")
            if "tool_error" in feedback:
                fault = feedback["tool_error"]
                if (not isinstance(fault, dict) or
                        fault.get("kind") != "transient_probe_failure" or
                        fault.get("retryable") is not True or
                        any(fault.get(key) != action.get(key) for key in ("x", "y")) or
                        set(feedback) != {"tool_error"}):
                    raise ValueError("Malformed or inconsistent injected fault")
                fault_events.append((index, fault))
                expected_error = fault
            elif "observation" in feedback:
                observation = feedback["observation"]
                if (not isinstance(observation, dict) or
                        any(observation.get(key) != action.get(key)
                            for key in ("x", "y")) or
                        type(observation.get("value")) is not int):
                    raise ValueError("Malformed probe observation")
                probe_successes += 1
                expected_remaining -= 1
                expected_observations.append(observation)
                seen.add(point)
            else:
                raise ValueError("Probe without observation or fault")
        elif action.get("type") == "submit":
            if feedback != {"submitted": True}:
                raise ValueError("Submission without acknowledgement")
        else:
            raise ValueError("Unknown trace action")
    if (run["public_pass"] and not run.get("submitted", False)):
        raise ValueError("Public pass without submission")
    if (run["probes"] != probe_successes or
            run.get("probe_attempts", attempts) != attempts or
            run.get("injected_faults", len(fault_events)) != len(fault_events)):
        raise ValueError("Runner metrics disagree with trace evidence")
    # Distinguish retry from merely choosing another valid coordinate.
    # The retry can occur after intervening actions; first retry latency is
    # measured in turns from fault to same-coordinate action.
    retries = []
    for index, fault in fault_events:
        later = [j for j in range(index + 1, len(events))
                 if events[j].get("response", {}).get("action") ==
                 {"type": "probe", "x": fault["x"], "y": fault["y"]}]
        retries.append(later[0] - index if later else None)
    return {"faults": len(fault_events), "probe_attempts": attempts,
            "successful_probes": probe_successes,
            "retries": sum(latency is not None for latency in retries),
            "next_turn_retries": sum(latency == 1 for latency in retries),
            "retry_latencies_turns": [latency for latency in retries if latency is not None],
            "recovered_runs": int(bool(fault_events) and run["hidden_pass"]),
            "false_public_success": int(run["public_pass"] and not run["hidden_pass"])}


def analyze(runs, *, control_runs=None):
    paired = pair_runs(runs)
    control = dict(pair_runs(control_runs)) if control_runs is not None else None
    if control is not None and set(control) != {task for task, _ in paired}:
        raise ValueError("Control and faulted tasks do not match")
    by_arm = {}
    for arm in ARMS:
        selected = [(task, group[arm]) for task, group in paired]
        audited = [audit_run(run) for _, run in selected]
        control_deltas = None
        if control is not None:
            control_metrics = [audit_run(control[task][arm]) for task, _ in selected]
            if any(item["faults"] for item in control_metrics):
                raise ValueError("Control dataset contains injected faults")
            control_deltas = [run["turns"] - control[task][arm]["turns"]
                              for task, run in selected]
        faulted_runs = sum(item["faults"] > 0 for item in audited)
        fault_count = sum(item["faults"] for item in audited)
        retried = sum(item["retries"] for item in audited)
        by_arm[arm] = {
            "n": len(selected),
            "hidden_successes": sum(run["hidden_pass"] for _, run in selected),
            "false_public_successes": sum(item["false_public_success"] for item in audited),
            "faulted_runs": faulted_runs, "faults": fault_count,
            "retried_faults": retried,
            "next_turn_retries": sum(item["next_turn_retries"] for item in audited),
            "retry_rate": retried / fault_count if fault_count else None,
            "recovered_runs": sum(item["recovered_runs"] for item in audited),
            "recovery_rate": (sum(item["recovered_runs"] for item in audited) /
                              faulted_runs if faulted_runs else None),
            "retry_latency_turns": [latency for item in audited
                                     for latency in item["retry_latencies_turns"]],
            "mean_extra_turns_vs_control": (sum(control_deltas) / len(control_deltas)
                                            if control_deltas is not None else None),
        }
    return {
        "schema": "kloop-discovery-recovery-analysis-v1",
        "stratum": SCHEMA, "n_paired_tasks": len(paired),
        "control_comparison": control is not None, "by_arm": by_arm,
        "limitations": ("Synthetic retryable probe errors and deterministic controls measure "
                        "harness behavior, not model robustness. Public-pass means "
                        "observation-consistent only for discovery; private-preference "
                        "runs are rejected. Control deltas are descriptive, not causal."),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Fault-injected discovery trace tree")
    parser.add_argument("--control", type=Path, help="Paired no-fault discovery trace tree")
    parser.add_argument("--expected-tasks", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        runs, evidence_sha = load_runs(args.input)
        control_runs, control_sha = load_runs(args.control) if args.control else (None, None)
        report = analyze(runs, control_runs=control_runs)
        if args.expected_tasks is not None and report["n_paired_tasks"] != args.expected_tasks:
            raise ValueError("Unexpected paired task count")
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    report["evidence_sha256"] = evidence_sha
    report["control_evidence_sha256"] = control_sha
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
