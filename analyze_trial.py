#!/usr/bin/env python3
"""Paired, four-arm K-loop analysis. Exploratory until preregistration is locked.

Accepts either a Kaggle results JSON file (with a ``runs`` array) or the
canonical runner's tree of ``task/condition/trace.json`` files. No dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path


ARMS = ("k_implicit", "k_explicit", "rich_implicit", "rich_explicit")
CONTRASTS = {
    "H3_explicit_k_gain": (-1, 1, 0, 0),
    "H4_feedback_gap_reduction": (-1, 1, 1, -1),
    "H5_k_explicit_vs_rich_explicit": (0, 1, 0, -1),
}
CONTRAST_RANGES = {
    "H3_explicit_k_gain": 2,
    "H4_feedback_gap_reduction": 4,
    "H5_k_explicit_vs_rich_explicit": 2,
}
FAMILY_ALPHA = 0.05
NONINFERIORITY_MARGIN = -0.10


def load_runs(source: Path):
    """Return (run dictionaries, SHA-256 of all source evidence)."""
    if source.is_file():
        payload = source.read_bytes()
        parsed = json.loads(payload)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("runs"), list):
            raise ValueError("Expected a Kaggle results object containing 'runs'")
        return parsed["runs"], hashlib.sha256(payload).hexdigest()
    if not source.is_dir():
        raise ValueError("Input must be a Kaggle JSON file or a runner directory")
    files = sorted(source.glob("*/*/trace.json"))
    if not files:
        raise ValueError("No runner trace.json files found")
    digester = hashlib.sha256()
    runs = []
    for path in files:
        payload = path.read_bytes()
        digester.update(str(path.relative_to(source)).encode("utf-8"))
        digester.update(b"\0")
        digester.update(hashlib.sha256(payload).digest())
        runs.append(json.loads(payload))
    return runs, digester.hexdigest()


def pair_runs(runs):
    """Require every task to have exactly one result for each of four arms."""
    by_task = {}
    if not isinstance(runs, list) or not runs:
        raise ValueError("No run records")
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("Run records must be JSON objects")
        task, arm, passed = run.get("task"), run.get("condition"), run.get("hidden_pass")
        if not isinstance(task, str) or not task or arm not in ARMS:
            raise ValueError(f"Invalid task/condition: {task!r}/{arm!r}")
        if type(passed) is not bool:
            raise ValueError(f"Missing/non-boolean hidden_pass for {task}/{arm}")
        tokens = run.get("total_tokens")
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ValueError(f"Invalid total_tokens for {task}/{arm}")
        group = by_task.setdefault(task, {})
        if arm in group:
            raise ValueError(f"Duplicate arm for {task}/{arm}")
        group[arm] = run
    for task, group in by_task.items():
        if set(group) != set(ARMS):
            raise ValueError(f"Unpaired task {task}: missing {sorted(set(ARMS) - set(group))}")
    return [(task, by_task[task]) for task in sorted(by_task)]


def quantile(sorted_values, p):
    if not sorted_values or not 0 <= p <= 1:
        raise ValueError("Invalid quantile input")
    position = (len(sorted_values) - 1) * p
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] * (high - position) + sorted_values[high] * (position - low)


def analyze(runs, *, resamples=20000, bootstrap_seed=20261103,
            expected_tasks=None, max_tokens_per_run=None):
    if resamples < 1000:
        raise ValueError("At least 1000 bootstrap samples required")
    paired = pair_runs(runs)
    n = len(paired)
    if expected_tasks is not None and (expected_tasks < 1 or n != expected_tasks):
        raise ValueError(f"Expected {expected_tasks} paired tasks, found {n}")
    if max_tokens_per_run is not None:
        if max_tokens_per_run < 1:
            raise ValueError("Token cap must be positive")
        if any(group[arm].get("total_tokens") is None
               for _, group in paired for arm in ARMS):
            raise ValueError("Enforcing a token cap requires measured usage in every arm")

    def effective_pass(run):
        return run["hidden_pass"] and (max_tokens_per_run is None or
                                       run["total_tokens"] <= max_tokens_per_run)

    values = {}
    for name, coefficients in CONTRASTS.items():
        values[name] = [sum(coef * int(effective_pass(group[arm]))
                            for coef, arm in zip(coefficients, ARMS))
                        for _, group in paired]

    rng = random.Random(bootstrap_seed)
    sampled = {name: [] for name in CONTRASTS}
    for _ in range(resamples):
        indexes = [rng.randrange(n) for _ in range(n)]
        for name in CONTRASTS:
            vector = values[name]
            sampled[name].append(sum(vector[i] for i in indexes) / n)

    bounds = {"H3_explicit_k_gain": 0,
              "H4_feedback_gap_reduction": 0,
              "H5_k_explicit_vs_rich_explicit": NONINFERIORITY_MARGIN}
    contrasts = {}
    for name, vector in values.items():
        samples = sorted(sampled[name])
        estimate = sum(vector) / n
        # Unlike a percentile bootstrap, this finite-sample bound does not
        # collapse to zero width when every observed paired contrast is 0.
        # Valid for independent bounded paired-task observations.
        adjusted_lower = estimate - CONTRAST_RANGES[name] * math.sqrt(
            math.log(len(CONTRASTS) / FAMILY_ALPHA) / (2 * n))
        contrasts[name] = {
            "estimate": estimate,
            "ci_95_percentile_descriptive": [quantile(samples, 0.025),
                                             quantile(samples, 0.975)],
            "bonferroni_hoeffding_one_sided_lower": adjusted_lower,
            "threshold": bounds[name],
            "passes_conservative_bound_if_preregistered": adjusted_lower > bounds[name],
        }

    usage_complete = all(group[arm].get("total_tokens") is not None
                         for _, group in paired for arm in ARMS)
    by_arm = {arm: {
        "successes": sum(effective_pass(group[arm]) for _, group in paired),
        "raw_successes": sum(group[arm]["hidden_pass"] for _, group in paired),
        "budget_disqualifications": sum(group[arm]["hidden_pass"] and
                                        not effective_pass(group[arm]) for _, group in paired),
        "mean_tokens": (sum(group[arm]["total_tokens"] for _, group in paired) / n
                        if usage_complete else None),
        "errors": sum(group[arm].get("error") is not None for _, group in paired),
    } for arm in ARMS}
    return {
        "schema": "kloop-paired-analysis-v1",
        "status": "exploratory_without_external_preregistration_proof",
        "n_paired_tasks": n,
        "max_tokens_per_run": max_tokens_per_run,
        "bootstrap": {"seed": bootstrap_seed, "resamples": resamples,
                      "method": "paired-task percentile bootstrap",
                      "family_alpha": FAMILY_ALPHA, "tests": len(CONTRASTS),
                      "one_sided_adjustment": "Bonferroni"},
        "confirmatory_bound": ("one-sided Hoeffding lower bound with "
                               "Bonferroni family-wise adjustment; assumes "
                               "independent bounded paired-task units"),
        "hypotheses": contrasts,
        "by_arm": by_arm,
        "usage_complete": usage_complete,
        "warning": ("Lower bounds are descriptive unless sample size, model settings, "
                    "holdout commitment, analysis code, and cost limits were fixed "
                    "before seeing outcomes. Token parity is not established here."),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--resamples", type=int, default=20000)
    parser.add_argument("--bootstrap-seed", type=int, default=20261103)
    parser.add_argument("--expected-tasks", type=int)
    parser.add_argument("--max-tokens-per-run", type=int)
    parser.add_argument("--holdout-commitment", type=Path)
    args = parser.parse_args(argv)
    try:
        runs, evidence_sha = load_runs(args.input)
        expected = args.expected_tasks
        committed_sha = None
        if args.holdout_commitment:
            public = json.loads(args.holdout_commitment.read_text(encoding="utf-8"))
            if public.get("schema") != "kloop-holdout-commitment-v1":
                raise ValueError("Unsupported holdout commitment schema")
            committed_count = public["task_count"] * public["repetitions"]
            if expected is not None and expected != committed_count:
                raise ValueError("Expected count disagrees with holdout commitment")
            expected = committed_count
            committed_sha = public["manifest_sha256"]
        report = analyze(runs, resamples=args.resamples,
                         bootstrap_seed=args.bootstrap_seed,
                         expected_tasks=expected,
                         max_tokens_per_run=args.max_tokens_per_run)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    report["evidence_sha256"] = evidence_sha
    report["holdout_manifest_commitment_sha256"] = committed_sha
    output = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
