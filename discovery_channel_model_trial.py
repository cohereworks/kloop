#!/usr/bin/env python3
"""Exploratory matched-channel trial through the trusted in-process HTTP adapter.

This is not a confirmatory study: no preregistered estimand, private holdout,
endpoint isolation, calibrated sample size, or actual tokenizer equivalence.
Arms can naturally take different actions; unlike the deterministic paired
positive control, success and response equality are NOT required here.
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from discovery_channel_api_agent import INSTRUCTIONS, call_channel_model
from discovery_channel_codec import EMPTY_PAYLOAD
from discovery_channel_match import audit_matched_run, run_matched
from discovery_pilot import CONDITIONS, make_tasks
from pilot import arm_schedule, canonical, write_json


SCHEMA = "kloop-discovery-channel-hosted-exploratory-v1"


def run_trial(out, adapter, *, seed, arm_seed, count, state_bytes,
              max_total_tokens, max_turns=6, inject_probe_failure_at=None,
              model_metadata=None, execution="injected-adapter-test"):
    """Adapter injection is for mocked tests; the CLI pins direct HTTP only."""
    if (type(seed) is not int or type(arm_seed) is not int or
            type(state_bytes) is not int or
            state_bytes < len(EMPTY_PAYLOAD.encode("utf-8")) or
            type(max_total_tokens) is not int or max_total_tokens < 1 or
            type(max_turns) is not int or not 1 <= max_turns <= 6):
        raise ValueError("Invalid seed, state capacity, turn or token cap")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be new or empty")
    tasks = make_tasks(seed, count)
    schedule = arm_schedule([t["id"] for t in tasks["tasks"]],
                            mode="balanced", seed=arm_seed)
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for task in tasks["tasks"]:
        for condition in schedule[task["id"]]:
            run = run_matched(task, condition, adapter, state_bytes,
                              inject_probe_failure_at=inject_probe_failure_at,
                              max_total_tokens=max_total_tokens,
                              max_turns=max_turns)
            # A completed provider envelope can meter even malformed model
            # content. Network/HTTP/envelope failures still have unknown cost.
            if any("response" not in event for event in run["trace"]):
                run["channel_audit"] = None
            else:
                try:
                    run["channel_audit"] = audit_matched_run(run)
                except ValueError as exc:
                    run["error"] = f"ChannelAuditError: {exc}"
                    run["hidden_pass"] = False
                    run["channel_audit"] = None
            runs.append(run)
            directory = out / task["id"] / run["condition"]
            write_json(directory / "trace.json", run)
            if (execution == "trusted-direct-http" and run["error"] and
                    "Provider model identity drifted" in run["error"]):
                # A changed model invalidates *all* subsequent cross-arm
                # comparisons. Save the partial record and stop spending calls.
                write_json(out / "abort.json", {
                    "schema": SCHEMA, "reason": "provider_model_identity_drift",
                    "runs_recorded": len(runs), "last_trace": str(
                        (Path(task["id"]) / run["condition"] / "trace.json")),
                    "partial_runs_sha256": hashlib.sha256(
                        canonical(runs).encode()).hexdigest(),
                    "model_metadata": model_metadata or {},
                    "warning": "Aborted before complete four-arm pairing; no trial summary."})
                raise RuntimeError("Provider model identity drifted; trial aborted")
    by_arm = {}
    for condition in CONDITIONS:
        name = "_".join(condition)
        selected = [r for r in runs if r["condition"] == name]
        metered = all(r["total_tokens"] is not None for r in selected)
        by_arm[name] = {"n": len(selected),
                        "hidden_successes": sum(r["hidden_pass"] for r in selected),
                        "protocol_errors": sum(r["error"] is not None for r in selected),
                        "over_budget": sum(r["within_budget"] is False for r in selected),
                        "usage_complete": metered,
                        "provider_reported_token_lower_bound": sum(
                            r["reported_token_lower_bound"] for r in selected),
                        "provider_reported_total_tokens": (
                            sum(r["total_tokens"] for r in selected)
                            if metered else None)}
    summary = {"schema": SCHEMA, "execution": execution,
               "seed": seed, "arm_seed": arm_seed, "count": count,
               "task_set_sha256": hashlib.sha256(canonical(tasks).encode()).hexdigest(),
               "runs_sha256": hashlib.sha256(canonical(runs).encode()).hexdigest(),
               "state_budget_bytes": state_bytes, "max_turns": max_turns,
               "max_total_tokens": max_total_tokens,
               "inject_probe_failure_at": inject_probe_failure_at,
               "model_metadata": model_metadata or {},
               "developer_instructions_sha256": hashlib.sha256(
                   INSTRUCTIONS.encode("utf-8")).hexdigest(),
               "by_arm": by_arm,
               "warning": ("Public exploratory generator; no private-holdout "
                           "or causal claim. Provider usage is unverified. "
                           "Metered invalid model outputs retain usage; "
                           "failed HTTP/envelope calls may incur unmeasured "
                           "tokens and report unknown budget compliance.")}
    write_json(out / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int,
                        help="Optional replay seed; otherwise random and saved after running")
    parser.add_argument("--arm-seed", type=int, default=20261106)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--state-bytes", type=int, required=True)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--max-total-tokens", type=int, required=True)
    parser.add_argument("--inject-probe-failure-at", type=int)
    args = parser.parse_args(argv)
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("Output directory must be new or empty")
    try:
        from api_agent import configuration
        from api_agent import ModelResponseError
        fixed_config = configuration()  # Pin parameters and credentials once.
        url, _key, params, timeout = fixed_config
        observed_model = [None]

        def adapter(request):
            response = call_channel_model(request, resolved_config=fixed_config)
            identity = response["metrics"]["model"]
            if observed_model[0] is None:
                observed_model[0] = identity
            elif observed_model[0] != identity:
                raise ModelResponseError("Provider model identity drifted during trial",
                                         response["metrics"])
            return response

        endpoint = urlsplit(url)
        summary = run_trial(args.out, adapter,
                            seed=args.seed if args.seed is not None
                            else secrets.randbits(128),
                            arm_seed=args.arm_seed, count=args.count,
                            state_bytes=args.state_bytes,
                            max_total_tokens=args.max_total_tokens,
                            max_turns=args.max_turns,
                            inject_probe_failure_at=args.inject_probe_failure_at,
                            model_metadata={"requested_model": params["model"],
                                            "endpoint_origin":
                                                f"{endpoint.scheme}://{endpoint.hostname}",
                                            "requested_parameters": params,
                                            "http_timeout": timeout},
                            execution="trusted-direct-http")
    except (ValueError, OSError, TypeError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Exploratory matched-channel trial: {summary['count']} tasks at {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
