#!/usr/bin/env python3
"""Independent capacity, information-parity and provenance audit.

Only public traces are needed; no hidden target or provider account is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from discovery_channel_match import MATCHED_SCHEMA, audit_matched_run
from pilot import CONDITIONS, arm_schedule, canonical, write_json


def analyze(root):
    scenarios = {}
    for folder in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        summary = json.loads((folder / "summary.json").read_text())
        if summary.get("schema") != MATCHED_SCHEMA:
            raise ValueError("Unexpected channel-matched schema")
        runs = [json.loads(path.read_text())
                for path in folder.glob("*/*/trace.json")]
        indexed = {(run["task"], run["condition"]): run for run in runs}
        task_ids = sorted({run["task"] for run in runs})
        if len(indexed) != len(runs) or len(task_ids) != summary["count"]:
            raise ValueError("Missing or duplicated matched-channel traces")
        schedule = arm_schedule(task_ids, mode="balanced", seed=summary["arm_seed"])
        ordered = []
        for task in task_ids:
            for arm in schedule[task]:
                try:
                    ordered.append(indexed[task, "_".join(arm)])
                except KeyError as exc:
                    raise ValueError("Incomplete four-arm pairing") from exc
        digest = hashlib.sha256(canonical(ordered).encode()).hexdigest()
        if digest != summary["runs_sha256"]:
            raise ValueError("Archived run digest mismatch")
        audited = {}
        for key, run in indexed.items():
            if run["state_budget_bytes"] != summary["state_budget_bytes"]:
                raise ValueError("Inconsistent state budget")
            proof = audit_matched_run(run)
            if proof != run["channel_audit"]:
                raise ValueError("Altered channel proof")
            audited[key] = proof
        equivalent_turn_pairs = 0
        wire_delta = []
        for task in task_ids:
            for feedback in ("k", "rich"):
                implicit = indexed[task, f"{feedback}_implicit"]
                explicit = indexed[task, f"{feedback}_explicit"]
                i_audit = audited[task, f"{feedback}_implicit"]
                e_audit = audited[task, f"{feedback}_explicit"]
                if (implicit["hidden_pass"] != explicit["hidden_pass"] or
                        i_audit["incoming_payloads"] != e_audit["incoming_payloads"] or
                        implicit["turns"] != explicit["turns"]):
                    raise ValueError("State capacity or result differs across channels")
                for i_event, e_event, i_bytes, e_bytes in zip(
                        implicit["trace"], explicit["trace"],
                        i_audit["request_wire_utf8_bytes"],
                        e_audit["request_wire_utf8_bytes"]):
                    i_req = i_event["request"]
                    e_req = e_event["request"]
                    for key in ("task", "observations", "human_signal",
                                "probe_budget_remaining", "last_tool_error"):
                        if i_req.get(key) != e_req.get(key):
                            raise ValueError("Unequal task evidence or feedback")
                    if i_event["response"] != e_event["response"] or (
                            i_event["environment_feedback"] !=
                            e_event["environment_feedback"]):
                        raise ValueError("Unequal action, payload or environment result")
                    equivalent_turn_pairs += 1
                    wire_delta.append(e_bytes - i_bytes)
        by_arm = {}
        for arm in CONDITIONS:
            name = "_".join(arm)
            selected = [indexed[task, name] for task in task_ids]
            by_arm[name] = {"n": len(selected),
                            "successes": sum(run["hidden_pass"] for run in selected),
                            "errors": sum(run["error"] is not None for run in selected),
                            "mean_turns": sum(run["turns"] for run in selected)
                                          / len(selected)}
            if any(by_arm[name][k] != summary["by_arm"][name][k]
                   for k in ("n", "successes", "errors")):
                raise ValueError("Summary/trace disagreement")
        scenarios[folder.name] = {
            "state_budget_bytes": summary["state_budget_bytes"],
            "injected_fault_at": summary["inject_probe_failure_at"],
            "runs_sha256": digest,
            "matched_information_turn_pairs": equivalent_turn_pairs,
            "mean_explicit_minus_implicit_request_wire_bytes":
                sum(wire_delta) / len(wire_delta) if wire_delta else None,
            "by_arm": by_arm}
    return {"schema": "kloop-discovery-channel-parity-audit-v1",
            "scenario_count": len(scenarios), "scenarios": scenarios,
            "limitations": ("Exact public payload and observation equality is "
                            "established within each feedback pair; this is not "
                            "equal model tokenization, inference cost, latency, "
                            "representation processing cost or a live causal "
                            "treatment effect. Public deterministic controls "
                            "use a fixed greedy prefix state compressor.")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    write_json(args.out, analyze(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
