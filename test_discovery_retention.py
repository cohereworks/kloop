import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from discovery_pilot import CONDITIONS, make_tasks, run_one
from discovery_retention import (RETENTION_SCHEMA, audit_projection, main,
                                 project_visible_request, run_retention)
from discovery_retention_control import respond, respond_state_blind
from analyze_retention import analyze


class RetentionDiagnosticTests(unittest.TestCase):
    def test_default_discovery_remains_cumulative_and_unmodified(self):
        task = make_tasks(1337, 1)["tasks"][0]
        run = run_one(task, ("k", "implicit"), respond)
        self.assertTrue(run["hidden_pass"])
        self.assertEqual([len(e["request"]["observations"])
                          for e in run["trace"]], [2, 3, 4])
        self.assertTrue(all(e["request"]["schema"] != RETENTION_SCHEMA
                            for e in run["trace"]))

    def test_history_one_and_explicit_ledger_both_carry_sufficient_evidence(self):
        for task in make_tasks(1337, 12)["tasks"]:
            for arm in CONDITIONS:
                with self.subTest(task=task["id"], arm=arm):
                    run = run_retention(task, arm, respond, "latest", 1)
                    self.assertTrue(run["hidden_pass"])
                    self.assertEqual(run["turns"], 3)
                    self.assertEqual([len(e["request"]["observations"])
                                      for e in run["trace"]], [2, 1, 1])
                    self.assertEqual(audit_projection(run)["verified_requests"], 3)
                    self.assertNotIn("_target", json.dumps(run))

    def test_no_implicit_history_exposes_information_asymmetry(self):
        successes = {f"{a}_{b}": 0 for a, b in CONDITIONS}
        for task in make_tasks(1337, 12)["tasks"]:
            for arm in CONDITIONS:
                run = run_retention(task, arm, respond, "latest", 0)
                successes[f"{arm[0]}_{arm[1]}"] += run["hidden_pass"]
                audit_projection(run)
        self.assertEqual(successes["k_explicit"], 12)
        self.assertEqual(successes["rich_explicit"], 12)
        self.assertLess(successes["k_implicit"], 12)
        self.assertLess(successes["rich_implicit"], 12)

    def test_state_blind_ablation_fails_only_under_windowed_evidence(self):
        for task in make_tasks(1337, 12)["tasks"]:
            for arm in CONDITIONS:
                full = run_retention(task, arm, respond_state_blind,
                                     "cumulative", 0)
                latest = run_retention(task, arm, respond_state_blind,
                                       "latest", 1)
                self.assertTrue(full["hidden_pass"])
                self.assertFalse(latest["hidden_pass"])
                audit_projection(full)
                audit_projection(latest)

    def test_retry_fault_keeps_evidence_window_and_state_handoff(self):
        task = make_tasks(1337, 1)["tasks"][0]
        for arm in CONDITIONS:
            run = run_retention(task, arm, respond, "latest", 1,
                                inject_probe_failure_at=1)
            self.assertTrue(run["hidden_pass"])
            self.assertEqual(run["turns"], 4)
            self.assertEqual([len(e["request"]["observations"])
                              for e in run["trace"]], [2, 0, 1, 1])
            self.assertEqual(audit_projection(run)["verified_requests"], 4)

    def test_projection_auditor_rejects_old_evidence_leak(self):
        task = make_tasks(1337, 1)["tasks"][0]
        run = run_retention(task, ("k", "explicit"), respond)
        tampered = copy.deepcopy(run)
        tampered["trace"][1]["request"]["observations"].extend(task["initial"])
        with self.assertRaisesRegex(ValueError, "differs from projection"):
            audit_projection(tampered)
        tampered = copy.deepcopy(run)
        tampered["trace"][1]["request"]["ledger"]["established"] = []
        with self.assertRaisesRegex(ValueError, "handoff does not match"):
            audit_projection(tampered)
        with self.assertRaisesRegex(ValueError, "History window"):
            project_visible_request("latest", -1)

    def test_subprocess_cli_archives_model_visible_traces(self):
        agent = Path(__file__).with_name("discovery_retention_control.py")
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "retention"
            self.assertEqual(main(["--agent", f"{sys.executable} {agent}",
                                   "--out", str(destination),
                                   "--seed", "1337", "--count", "2",
                                   "--view", "latest", "--history-window", "1"]), 0)
            summary = json.loads((destination / "summary.json").read_text())
            self.assertEqual(summary["schema"], RETENTION_SCHEMA)
            self.assertEqual(len(list(destination.glob("*/*/trace.json"))), 8)
            self.assertTrue(all(entry["hidden_successes"] == 2
                                for entry in summary["by_arm"].values()))
            evidence = analyze(Path(temp))
            self.assertEqual(evidence["n_scenarios"], 1)
            self.assertEqual(evidence["scenarios"]["retention"]
                             ["verified_request_count"], 24)
            one = next(destination.glob("*/*/trace.json"))
            tampered = json.loads(one.read_text())
            tampered["trace"][1]["request"]["observations"].extend(
                tampered["trace"][0]["request"]["observations"])
            one.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "digest"):
                analyze(Path(temp))


if __name__ == "__main__":
    unittest.main()
