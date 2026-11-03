import json
import sys
import tempfile
import unittest
from pathlib import Path

from pilot import CONDITIONS
from preference_baseline_agent import respond
from preference_pilot import (OPTIONS, make_tasks, main, request_for,
                              run_one, validate_response)


class PreferencePilotTests(unittest.TestCase):
    def test_balanced_preference_targets_and_seed_reproduction(self):
        tasks = make_tasks(1337, 80)["tasks"]
        self.assertEqual(make_tasks(1337, 80), make_tasks(1337, 80))
        self.assertNotEqual(make_tasks(1337, 80), make_tasks(1338, 80))
        self.assertEqual({value: sum(t["_preference"] == value for t in tasks)
                          for value in OPTIONS}, {value: 10 for value in OPTIONS})

    def test_all_k_noninterference_and_rich_feedback_distinguishability(self):
        task = make_tasks(27, 1)["tasks"][0]
        target0 = {**task, "_preference": 0}
        target7 = {**task, "_preference": 7}
        for condition in (("k", "implicit"), ("k", "explicit")):
            trace0 = run_one(target0, condition, respond)["trace"]
            trace7 = run_one(target7, condition, respond)["trace"]
            self.assertEqual(trace0, trace7)
            self.assertNotIn("_preference", json.dumps(trace0))
            self.assertNotIn("Accepted", json.dumps(trace0))
            self.assertNotIn("Rejected", json.dumps(trace0))
        rich0 = run_one(target0, ("rich", "implicit"), respond)["trace"]
        rich7 = run_one(target7, ("rich", "implicit"), respond)["trace"]
        self.assertNotEqual(rich0[1]["request"]["human_signal"],
                            rich7[1]["request"]["human_signal"])

    def test_information_limit_and_rich_baseline_on_complete_blocks(self):
        tasks = make_tasks(1337, 80)["tasks"]
        results = {f"{a}_{b}": [] for a, b in CONDITIONS}
        for task in tasks:
            for condition in CONDITIONS:
                record = run_one(task, condition, respond)
                self.assertIsNone(record["error"])
                self.assertTrue(record["committed"])
                self.assertNotIn("_preference", json.dumps(record))
                results[f"{condition[0]}_{condition[1]}"].append(record["hidden_pass"])
        self.assertEqual(sum(results["k_implicit"]), 10)
        self.assertEqual(sum(results["k_explicit"]), 10)
        self.assertEqual(sum(results["rich_implicit"]), 50)
        self.assertEqual(sum(results["rich_explicit"]), 50)

    def test_protocol_errors_and_metered_budget(self):
        task = make_tasks(19, 1)["tasks"][0]
        with self.assertRaisesRegex(ValueError, "0..7"):
            validate_response({"action": {"type": "commit", "option": 11}},
                              ("k", "implicit"))

        def measured(request):
            return {**respond(request), "metrics": {"total_tokens": 13}}

        capped = run_one(task, ("k", "implicit"), measured,
                         max_total_tokens=25)
        self.assertTrue(capped["budget_exhausted"])
        self.assertFalse(capped["hidden_pass"])
        self.assertEqual(capped["total_tokens"], 26)
        unknown = run_one(task, ("k", "implicit"), respond,
                          max_total_tokens=25)
        self.assertIn("Measured token usage", unknown["error"])

    def test_cli_subprocess_four_arm_calibration(self):
        agent = Path(__file__).with_name("preference_baseline_agent.py").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            self.assertEqual(main(["--seed", "88", "--count", "8",
                                   "--agent", f"{sys.executable} {agent}",
                                   "--out", str(out), "--arm-seed", "17"]), 0)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["conditions"]["k_implicit"]["successes"], 1)
            self.assertEqual(summary["conditions"]["rich_explicit"]["successes"], 5)
            self.assertEqual(len(list(out.glob("*/*/trace.json"))), 32)


if __name__ == "__main__":
    unittest.main()
