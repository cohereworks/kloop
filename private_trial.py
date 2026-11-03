#!/usr/bin/env python3
"""Trusted in-process evaluator for an unpublished K-loop holdout.

The model receives only request_for() projections through api_agent.call_model.
No model-controlled subprocess is launched next to hidden cases. This is a
logical model-channel boundary, not a host/container security sandbox.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import urlsplit

from holdout_commitment import canonical_bytes, verify
from pilot import (SCHEMA, arm_schedule, canonical, make_tasks,
                   run_one, write_json, aggregate)


def task_from_private_manifest(manifest, repetition, index):
    """Derive a distinct pseudorandom task seed without publishing the root."""
    payload = canonical(["kloop-task-v1", manifest["seed"], repetition, index])
    digest = hmac.new(bytes.fromhex(manifest["nonce"]),
                      payload.encode("utf-8"), hashlib.sha256).digest()
    seed = int.from_bytes(digest[:8], "big")
    task = make_tasks(seed, 1)["tasks"][0]
    task["id"] = f"r{repetition:03d}t{index:04d}"
    return task


def run_private(manifest, public, out, adapter, *, arm_seed, max_turns,
                max_total_tokens, model_metadata=None):
    """Run all paired arms with hidden cases held only by this trusted worker."""
    verify(manifest, public)
    if not 1 <= max_turns <= 100 or not 1 <= max_total_tokens:
        raise ValueError("Positive bounded turns and measured-token cap required")
    local_pilot_sha = hashlib.sha256(Path(__file__).with_name("pilot.py").read_bytes()).hexdigest()
    if manifest["pilot_sha256"] != local_pilot_sha:
        raise ValueError("Generator has changed since holdout commitment")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be new or empty")
    out.mkdir(parents=True, exist_ok=True)

    task_ids = [f"r{rep:03d}t{index:04d}"
                for rep in range(manifest["repetitions"])
                for index in range(manifest["task_count"])]
    schedule = arm_schedule(task_ids, mode="balanced", seed=arm_seed)
    task_hash = hashlib.sha256()
    runs = []
    for rep in range(manifest["repetitions"]):
        for index in range(manifest["task_count"]):
            task = task_from_private_manifest(manifest, rep, index)
            task_hash.update(canonical_bytes(task))
            task_hash.update(b"\n")
            for condition in schedule[task["id"]]:
                dirname = f"{condition[0]}_{condition[1]}"
                run_dir = out / task["id"] / dirname
                record = run_one(task, condition, None, run_dir, max_turns, 0,
                                 max_total_tokens=max_total_tokens, adapter=adapter)
                runs.append(record)
                write_json(run_dir / "trace.json", record)

    summary = {
        "schema": SCHEMA,
        "execution": "private-trusted-http-adapter",
        "manifest_sha256": public["manifest_sha256"],
        "pilot_sha256": local_pilot_sha,
        "generated_tasks_sha256": task_hash.hexdigest(),
        "paired_tasks": len(task_ids),
        "arm_order": "balanced", "arm_seed": arm_seed,
        "execution_schedule": {key: [f"{a}_{b}" for a, b in value]
                               for key, value in schedule.items()},
        "model_metadata": model_metadata or {},
        "max_turns": max_turns, "max_total_tokens": max_total_tokens,
        "conditions": aggregate(runs),
        "warning": "The evaluator is trusted; it does not OS-sandbox arbitrary Python dependencies.",
    }
    write_json(out / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--commitment", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arm-seed", type=int, required=True)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--max-total-tokens", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        from api_agent import call_model, configuration

        # Validate endpoint/credentials before touching the output directory.
        fixed_config = configuration()
        url, _secret_key, params, timeout = fixed_config
        private = json.loads(args.private.read_text(encoding="utf-8"))
        public = json.loads(args.commitment.read_text(encoding="utf-8"))
        endpoint = urlsplit(url)
        observed_model = [None]

        def pinned_adapter(request):
            response = call_model(request, resolved_config=fixed_config)
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
    print(f"Completed {summary['paired_tasks']} paired tasks at {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
