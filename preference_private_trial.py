#!/usr/bin/env python3
"""Trusted HTTP-only evaluator for an unrevealed private preference holdout.

No model-controlled subprocess is run. The model receives an arm-specific
opaque ID, alternatives, its own action history/ledger, and permitted feedback.
This is a model-channel boundary, not an OS or provider-isolation guarantee.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import random
from pathlib import Path
from urllib.parse import urlsplit

from holdout_commitment import canonical_bytes
from pilot import CONDITIONS, arm_schedule, write_json
from preference_holdout import code_hashes, verify
from preference_pilot import OPTIONS, SCHEMA, TURN_LIMIT, run_one


def secret_digest(manifest, *fields):
    return hmac.new(bytes.fromhex(manifest["secret_key"]),
                    canonical_bytes(["kloop-private-preference-trial-v1", *fields]),
                    hashlib.sha256).digest()


def task_from_private_manifest(manifest, repetition, index):
    """Derive a pseudorandom, evaluator-only favorite; never serialize it."""
    favorite = OPTIONS[secret_digest(manifest, "favorite", repetition, index)[0] % len(OPTIONS)]
    return {"id": f"r{repetition:03d}p{index:04d}",
            "alternatives": list(OPTIONS), "_preference": favorite}


def arm_public_id(manifest, repetition, index, condition):
    """Break easy correlation of rich and K arms at the model-facing layer."""
    return secret_digest(manifest, "arm-id", repetition, index,
                         condition[0], condition[1])[:16].hex()


def run_private(manifest, public, out, adapter, *, arm_seed, max_turns,
                max_total_tokens, model_metadata=None):
    verify(manifest, public)
    if code_hashes() != {key: manifest[key] for key in code_hashes()}:
        raise ValueError("Preference generator or runner changed since commitment")
    if not 1 <= max_turns <= TURN_LIMIT or not 1 <= max_total_tokens:
        raise ValueError("Positive measured-token cap and turn limit 1..5 required")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be new or empty")
    out.mkdir(parents=True, exist_ok=True)

    tasks = [(rep, index) for rep in range(manifest["repetitions"])
             for index in range(manifest["task_count"])]
    task_ids = [f"r{rep:03d}p{index:04d}" for rep, index in tasks]
    schedule = arm_schedule(task_ids, mode="balanced", seed=arm_seed)
    runs = []
    dispatch_order = []
    dispatcher = random.Random(arm_seed)
    # Interleave tasks across arms. Opaque IDs alone do not prevent a stateful
    # provider from correlating four immediately adjacent arm runs.
    for position in range(len(CONDITIONS)):
        phase = list(tasks)
        dispatcher.shuffle(phase)
        for rep, index in phase:
            hidden_task = task_from_private_manifest(manifest, rep, index)
            task_id = hidden_task["id"]
            condition = schedule[task_id][position]
            arm = f"{condition[0]}_{condition[1]}"
            dispatch_order.append([task_id, arm])
            public_id = arm_public_id(manifest, rep, index, condition)
            # run_one constructs the agent-visible projection; never pass the
            # hidden_task object to the HTTP adapter directly.
            arm_task = {**hidden_task, "id": public_id}
            record = run_one(arm_task, condition, adapter, max_turns,
                             max_total_tokens=max_total_tokens)
            record["task"] = task_id  # evaluator-side pairing only
            record["arm_public_id"] = public_id
            runs.append(record)
            run_dir = out / task_id / arm
            run_dir.mkdir(parents=True, exist_ok=True)
            write_json(run_dir / "trace.json", record)

    summary = {"schema": SCHEMA,
               "execution": "private-preference-trusted-http-adapter",
               "manifest_sha256": public["manifest_sha256"],
               **code_hashes(),
               "paired_tasks": len(task_ids), "arm_order": "balanced",
               "arm_seed": arm_seed, "max_turns": max_turns,
               "max_total_tokens": max_total_tokens,
               "dispatch_strategy": "position-interleaved-permuted-tasks",
               "dispatch_order": dispatch_order,
               "execution_schedule": {task: [f"{a}_{b}" for a, b in order]
                                      for task, order in schedule.items()},
               "model_metadata": model_metadata or {},
               "conditions": {f"{a}_{b}": {
                   "n": len(task_ids),
                   "successes": sum(r["hidden_pass"] for r in runs
                                    if r["condition"] == f"{a}_{b}"),
                   "errors": sum(r["error"] is not None for r in runs
                                 if r["condition"] == f"{a}_{b}"),
                   "tokens_reported": sum(r["total_tokens"] is not None for r in runs
                                          if r["condition"] == f"{a}_{b}")}
                   for a, b in CONDITIONS},
               "warning": "Trusted HTTP model channel only; no arbitrary adapter sandboxing."}
    write_json(out / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--commitment", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arm-seed", type=int, required=True)
    parser.add_argument("--max-turns", type=int, default=TURN_LIMIT)
    parser.add_argument("--max-total-tokens", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        from api_agent import call_model, configuration
        from preference_api_agent import INSTRUCTIONS

        fixed_config = configuration()
        url, _secret_key, params, timeout = fixed_config
        private = json.loads(args.private.read_text(encoding="utf-8"))
        public = json.loads(args.commitment.read_text(encoding="utf-8"))
        endpoint = urlsplit(url)
        observed_model = [None]

        def pinned_adapter(request):
            response = call_model(request, resolved_config=fixed_config,
                                  instructions=INSTRUCTIONS)
            reported_model = response.get("metrics", {}).get("model")
            if not isinstance(reported_model, str) or not reported_model:
                raise RuntimeError("Provider did not identify the model")
            if observed_model[0] is None:
                observed_model[0] = reported_model
            elif observed_model[0] != reported_model:
                raise RuntimeError("Provider model identity drifted during trial")
            return response

        summary = run_private(private, public, args.out, pinned_adapter,
                              arm_seed=args.arm_seed, max_turns=args.max_turns,
                              max_total_tokens=args.max_total_tokens,
                              model_metadata={"model": params["model"],
                                              "endpoint_origin": f"{endpoint.scheme}://{endpoint.hostname}",
                                              "requested_parameters": params,
                                              "http_timeout": timeout})
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Completed {summary['paired_tasks']} paired private-preference tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
