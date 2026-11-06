#!/usr/bin/env python3
"""Matched-capacity state-channel experiment, separate from preregistered arms.

The two interventions carry IDENTICAL canonical fact payloads with an equal
UTF-8 byte cap. Their JSON envelopes still differ, so this establishes
information parity, not token, latency, or causal treatment equivalence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shlex
from pathlib import Path

from discovery_channel_codec import EMPTY_PAYLOAD, PREFIX, decode_facts
from discovery_pilot import CONDITIONS, invoke_agent, make_tasks, run_one, validate_response
from pilot import arm_schedule, canonical, write_json


MATCHED_SCHEMA = "kloop-discovery-channel-matched-v1"


def matched_projection(max_bytes):
    if type(max_bytes) is not int or max_bytes < len(EMPTY_PAYLOAD.encode()):
        raise ValueError("State budget below minimum encoding size")
    disclosed = 0

    def project(request):
        nonlocal disclosed
        visible = copy.deepcopy(request)
        observations = visible["observations"]
        visible["observations"] = observations[disclosed:]
        disclosed = len(observations)
        if visible["condition"]["state"] == "explicit":
            ledger = visible["ledger"]
            visible["ledger"] = ({"carry": ledger["carry"]}
                                 if ledger is not None else None)
            visible["history"] = []
        else:
            records = visible["history"]
            visible["ledger"] = None
            visible["history"] = ([{"message": records[-1]["message"]}]
                                  if records else [])
        visible["schema"] = MATCHED_SCHEMA
        visible["state_budget_bytes"] = max_bytes
        visible["observation_view"] = "latest"
        return visible

    return project


def validate_carriers(response, max_bytes):
    """Require identical canonical payloads in both outgoing carriers."""
    ledger = response.get("ledger") if isinstance(response, dict) else None
    message = response.get("message") if isinstance(response, dict) else None
    # A direct hosted-model response carries adapter-owned, provider-reported
    # metrics in addition to the three model-authored fields. The synthetic
    # control emits only those three fields. Forbid any other side channel.
    keys = set(response) if isinstance(response, dict) else set()
    if (not isinstance(ledger, dict) or not isinstance(message, str) or
            keys not in ({"action", "message", "ledger"},
                         {"action", "message", "ledger", "metrics"}) or
            ("metrics" in keys and not isinstance(response["metrics"], dict)) or
            not message.startswith(PREFIX) or "carry" not in ledger or
            ledger["carry"] != message[len(PREFIX):]):
        raise ValueError("Mismatched or missing state carriers")
    decode_facts(ledger["carry"], max_bytes)
    return response


def run_matched(task, condition, adapter, max_bytes, inject_probe_failure_at=None,
                max_total_tokens=None, max_turns=6):
    def checked_response(response, state):
        validate_carriers(response, max_bytes)
        return validate_response(response, state)

    result = run_one(task, condition, adapter, max_turns=max_turns,
                     inject_probe_failure_at=inject_probe_failure_at,
                     request_projection=matched_projection(max_bytes),
                     max_total_tokens=max_total_tokens,
                     response_validator=checked_response)
    result["schema"] = MATCHED_SCHEMA
    result["state_budget_bytes"] = max_bytes
    return result


def audit_matched_run(run):
    """Prove disclosure and carrier wiring from public trace records alone."""
    if run.get("schema") != MATCHED_SCHEMA:
        raise ValueError("Wrong matched-channel schema")
    limit = run["state_budget_bytes"]
    previously_known = []
    previous_feedback = None
    previous_carry = None
    values = []
    request_bytes, response_bytes = [], []
    for index, event in enumerate(run["trace"]):
        if "response" not in event:
            raise ValueError("Protocol-error trace is not a positive control")
        req = event["request"]
        arm = req["condition"]["state"]
        if (req.get("schema") != MATCHED_SCHEMA or
                req.get("state_budget_bytes") != limit or
                req.get("observation_view") != "latest"):
            raise ValueError("Unexpected matched request metadata")
        observations = req["observations"]
        if index == 0:
            if len(observations) != 2:
                raise ValueError("Initial observations not disclosed")
            previously_known.extend(observations)
        else:
            fresh = ([previous_feedback["observation"]]
                     if "observation" in previous_feedback else [])
            if observations != fresh:
                raise ValueError("Evidence window leak or omission")
            previously_known.extend(fresh)
        if arm == "explicit":
            expected = {"carry": previous_carry} if index else None
            if req["ledger"] != expected or req["history"]:
                raise ValueError("Unexpected explicit carrier wiring")
            seen = req["ledger"]["carry"] if req["ledger"] else EMPTY_PAYLOAD
        elif arm == "implicit":
            expected = ([{"message": PREFIX + previous_carry}] if index else [])
            if req["ledger"] is not None or req["history"] != expected:
                raise ValueError("Unexpected implicit carrier wiring")
            seen = (req["history"][0]["message"][len(PREFIX):]
                    if req["history"] else EMPTY_PAYLOAD)
        else:
            raise ValueError("Invalid state arm")
        decode_facts(seen, limit)
        values.append(seen)
        result = validate_carriers(event["response"], limit)
        currently_known = {(row["x"], row["y"]): row["value"]
                           for row in previously_known}
        for point, value in decode_facts(result["ledger"]["carry"], limit).items():
            if currently_known.get(point) != value:
                raise ValueError("Carried claim lacks public observational support")
        previous_carry = result["ledger"]["carry"]
        previous_feedback = event["environment_feedback"]
        if "observation" in previous_feedback:
            probe = result["action"]
            row = previous_feedback["observation"]
            if probe != {"type": "probe", "x": row["x"], "y": row["y"]}:
                raise ValueError("Probe/observation mismatch")
        request_bytes.append(len(canonical(req).encode("utf-8")))
        response_bytes.append(len(canonical(result).encode("utf-8")))
        if "_target" in canonical(req):
            raise ValueError("Hidden target in public request")
    return {"turns": len(values), "incoming_payloads": values,
            "request_wire_utf8_bytes": request_bytes,
            "response_wire_utf8_bytes": response_bytes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--arm-seed", type=int, default=20261103)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--state-bytes", type=int, required=True)
    parser.add_argument("--inject-probe-failure-at", type=int)
    args = parser.parse_args(argv)
    if args.state_bytes < len(EMPTY_PAYLOAD.encode()):
        parser.error("State budget below empty encoding")
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
            directory = args.out / task["id"] / "_".join(condition)
            directory.mkdir(parents=True, exist_ok=True)

            def adapter(request):
                result, _ = invoke_agent(command, request, directory, 30)
                return result

            run = run_matched(task, condition, adapter, args.state_bytes,
                              args.inject_probe_failure_at)
            run["channel_audit"] = audit_matched_run(run)
            runs.append(run)
            write_json(directory / "trace.json", run)
    summary = {"schema": MATCHED_SCHEMA,
               "seed": args.seed, "arm_seed": args.arm_seed,
               "generated_tasks_sha256": hashlib.sha256(canonical(tasks).encode()).hexdigest(),
               "runs_sha256": hashlib.sha256(canonical(runs).encode()).hexdigest(),
               "count": args.count, "state_budget_bytes": args.state_bytes,
               "inject_probe_failure_at": args.inject_probe_failure_at,
               "by_arm": {"_".join(arm): {
                   "n": args.count,
                   "successes": sum(r["hidden_pass"] for r in runs
                                    if r["condition"] == "_".join(arm)),
                   "errors": sum(r["error"] is not None for r in runs
                                 if r["condition"] == "_".join(arm))}
                   for arm in CONDITIONS},
               "limitations": "Equal semantic state-payload bytes, not equal "
                              "wire-format bytes or model tokens. Deterministic "
                              "positive control only; not a model comparison."}
    write_json(args.out / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
