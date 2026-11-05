#!/usr/bin/env python3
"""Independent replay and aggregation of retention-diagnostic traces.

Read-only: no hidden task target is needed to verify what was disclosed.
Synthetic deterministic success counts are descriptive, not causal estimands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from discovery_retention import RETENTION_SCHEMA, audit_projection
from pilot import CONDITIONS, arm_schedule, canonical, write_json


def analyze(root):
    root = Path(root)
    scenarios = {}
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        summary = json.loads((directory / "summary.json").read_text())
        if summary.get("schema") != RETENTION_SCHEMA:
            raise ValueError(f"Wrong schema in {directory.name}")
        runs = [json.loads(path.read_text())
                for path in directory.glob("*/*/trace.json")]
        indexed = {(r["task"], r["condition"]): r for r in runs}
        task_ids = sorted({r["task"] for r in runs})
        if len(indexed) != len(runs) or len(task_ids) != summary["count"]:
            raise ValueError("Duplicate or missing diagnostic runs")
        schedule = arm_schedule(task_ids, mode="balanced", seed=summary["arm_seed"])
        ordered = []
        for task_id in task_ids:
            for condition in schedule[task_id]:
                key = (task_id, "_".join(condition))
                if key not in indexed:
                    raise ValueError("Incomplete four-arm pairing")
                ordered.append(indexed[key])
        digest = hashlib.sha256(canonical(ordered).encode()).hexdigest()
        if digest != summary["runs_sha256"]:
            raise ValueError("Run digest does not match archived summary")
        for run in ordered:
            if (run.get("evidence_view") != summary["view"] or
                    run.get("history_window") != summary["history_window"] or
                    "_target" in canonical(run)):
                raise ValueError("Model-facing trace metadata or privacy violation")
            if audit_projection(run) != run["projection_audit"]:
                raise ValueError("Projection proof changed after execution")
        by_arm = {"_".join(arm): {
            "n": len(task_ids),
            "hidden_successes": sum(indexed[(tid, "_".join(arm))]["hidden_pass"]
                                    for tid in task_ids),
            "errors": sum(indexed[(tid, "_".join(arm))]["error"] is not None
                          for tid in task_ids),
            "mean_turns": sum(indexed[(tid, "_".join(arm))]["turns"]
                              for tid in task_ids) / len(task_ids),
            "faulted_runs": sum(indexed[(tid, "_".join(arm))]["injected_faults"] > 0
                                for tid in task_ids)} for arm in CONDITIONS}
        for arm, counts in by_arm.items():
            declared = summary["by_arm"][arm]
            if any(counts[field] != declared[field]
                   for field in ("n", "hidden_successes", "errors")):
                raise ValueError("Summary and replay differ")
        scenarios[directory.name] = {
            "view": summary["view"], "history_window": summary["history_window"],
            "injected_fault_at": summary["inject_probe_failure_at"],
            "runs_sha256": digest,
            "verified_request_count": sum(r["projection_audit"]["verified_requests"]
                                          for r in ordered),
            "by_arm": by_arm}
    return {"schema": "kloop-discovery-retention-analysis-v1",
            "n_scenarios": len(scenarios), "scenarios": scenarios,
            "limitations": ("Public deterministic positive and ablation controls; "
                            "not model inference, not a preregistered treatment "
                            "comparison. Removing history or evidence changes "
                            "information availability across arms. A one-message "
                            "implicit history may recursively encode a full state, "
                            "so ledger presence is not synonymous with memory.")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    write_json(args.out, analyze(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
