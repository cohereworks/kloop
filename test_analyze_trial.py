import json
import tempfile
import unittest
from pathlib import Path

from analyze_trial import ARMS, analyze, load_runs, main, pair_runs, quantile
from pilot import CONDITIONS


def fake_runs():
    # Contrasts: H3 = .5, H4 = 1, H5 = .5.
    task_outcomes = {"t0000": (False, True, True, True),
                     "t0001": (True, True, True, False)}
    return [{"task": task, "condition": arm, "hidden_pass": passed,
             "total_tokens": 80, "error": None}
            for task, values in task_outcomes.items()
            for arm, passed in zip(ARMS, values)]


class PairedAnalysisTests(unittest.TestCase):
    def test_condition_contract_matches_canonical_pilot(self):
        self.assertEqual(set(ARMS), {f"{a}_{b}" for a, b in CONDITIONS})

    def test_quantile_handles_exact_and_interpolated_positions(self):
        self.assertEqual(quantile([1, 2, 3], 0.5), 2)
        self.assertEqual(quantile([1, 3], 0.25), 1.5)

    def test_contrasts_paired_bootstrap_and_usage(self):
        report = analyze(fake_runs(), resamples=1000, bootstrap_seed=17)
        self.assertEqual(report, analyze(fake_runs(), resamples=1000,
                                         bootstrap_seed=17))
        self.assertEqual(report["n_paired_tasks"], 2)
        estimates = {name: row["estimate"] for name, row in report["hypotheses"].items()}
        self.assertEqual(estimates, {
            "H3_explicit_k_gain": 0.5,
            "H4_feedback_gap_reduction": 1.0,
            "H5_k_explicit_vs_rich_explicit": 0.5,
        })
        self.assertEqual(report["hypotheses"]["H4_feedback_gap_reduction"]
                         ["ci_95_percentile_descriptive"], [1.0, 1.0])
        self.assertLess(report["hypotheses"]["H4_feedback_gap_reduction"]
                        ["bonferroni_hoeffding_one_sided_lower"], 1.0)
        self.assertTrue(report["usage_complete"])
        self.assertEqual(report["by_arm"]["k_explicit"]["mean_tokens"], 80)
        self.assertIn("exploratory", report["status"])

    def test_no_incomplete_duplicates_or_bad_outcomes(self):
        runs = fake_runs()
        with self.assertRaisesRegex(ValueError, "Unpaired"):
            pair_runs(runs[:-1])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            pair_runs(runs + [runs[0]])
        with self.assertRaisesRegex(ValueError, "non-boolean"):
            pair_runs([{**run, "hidden_pass": 1} if i == 0 else run
                       for i, run in enumerate(runs)])
        with self.assertRaisesRegex(ValueError, "total_tokens"):
            pair_runs([{**run, "total_tokens": -1} if i == 0 else run
                       for i, run in enumerate(runs)])

    def test_expected_count_and_posthoc_token_disqualification(self):
        runs = fake_runs()
        with self.assertRaisesRegex(ValueError, "Expected 3"):
            analyze(runs, resamples=1000, expected_tasks=3)
        report = analyze(runs, resamples=1000, max_tokens_per_run=70)
        self.assertEqual(report["by_arm"]["k_explicit"]["successes"], 0)
        self.assertEqual(report["by_arm"]["k_explicit"]["budget_disqualifications"], 2)
        with self.assertRaisesRegex(ValueError, "measured usage"):
            analyze([{**run, "total_tokens": None} if i == 0 else run
                     for i, run in enumerate(runs)],
                    resamples=1000, max_tokens_per_run=70)

    def test_identical_outcomes_do_not_fake_noninferiority(self):
        all_fail = [{"task": f"t{i:04d}", "condition": arm,
                     "hidden_pass": False, "total_tokens": None}
                    for i in range(12) for arm in ARMS]
        report = analyze(all_fail, resamples=1000)
        h5 = report["hypotheses"]["H5_k_explicit_vs_rich_explicit"]
        self.assertEqual(h5["ci_95_percentile_descriptive"], [0, 0])
        self.assertLess(h5["bonferroni_hoeffding_one_sided_lower"], -0.1)
        self.assertFalse(h5["passes_conservative_bound_if_preregistered"])

    def test_load_kaggle_file_and_local_trace_tree(self):
        runs = fake_runs()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "kaggle.json"
            results.write_text(json.dumps({"runs": runs}), encoding="utf-8")
            actual, digest = load_runs(results)
            self.assertEqual(actual, runs)
            self.assertEqual(len(digest), 64)
            for run in runs:
                target = root / "runner" / run["task"] / run["condition"] / "trace.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(run), encoding="utf-8")
            local, digest2 = load_runs(root / "runner")
            self.assertEqual(pair_runs(local), pair_runs(runs))
            self.assertEqual(len(digest2), 64)
            public = root / "commitment.json"
            public.write_text(json.dumps({"schema": "kloop-holdout-commitment-v1",
                                          "task_count": 2, "repetitions": 1,
                                          "manifest_sha256": "a" * 64}))
            report_file = root / "analysis.json"
            self.assertEqual(main([str(results), "--holdout-commitment", str(public),
                                   "--max-tokens-per-run", "100",
                                   "--resamples", "1000", "--out", str(report_file)]), 0)
            report = json.loads(report_file.read_text())
            self.assertEqual(report["holdout_manifest_commitment_sha256"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
