import json
import sys
import tempfile
import unittest
from pathlib import Path

from discovery_baseline_agent import respond
from discovery_pilot import (CONDITIONS, MODULUS, make_tasks, main,
                             request_for, run_one, validate_response)


class DiscoveryPilotTests(unittest.TestCase):
    def test_seeded_generator_has_real_discoverable_ambiguity(self):
        a = make_tasks(1337, 12)
        self.assertEqual(a, make_tasks(1337, 12))
        self.assertNotEqual(a, make_tasks(1338, 12))
        task = a["tasks"][0]
        self.assertEqual(len(task["initial"]), 2)
        # Two initial points determine a,d but leave b,c completely open.
        self.assertEqual(MODULUS ** 2, 121)
        for b in range(MODULUS):
            for c in range(MODULUS):
                candidate = {**task["_target"], "b": b, "c": c}
                for row in task["initial"]:
                    from discovery_pilot import evaluate
                    self.assertEqual(evaluate(candidate, row["x"], row["y"]),
                                     row["value"])

    def test_four_arm_public_projection_and_baseline(self):
        tasks = make_tasks(97, 12)["tasks"]
        for task in tasks:
            for condition in CONDITIONS:
                first = request_for(task, condition, 1, task["initial"],
                                    None, [], 3)
                wire = json.dumps(first)
                self.assertNotIn("_target", wire)
                self.assertEqual(first["human_signal"] == "K", condition[0] == "k")
                run = run_one(task, condition, respond, max_turns=6)
                self.assertTrue(run["hidden_pass"])
                self.assertEqual(run["probes"], 2)
                self.assertEqual(run["turns"], 3)
                self.assertIsNone(run["error"])
                self.assertNotIn("_target", json.dumps(run))

    def test_reject_invalid_or_duplicate_probes(self):
        task = make_tasks(11, 1)["tasks"][0]

        def repetitive(request):
            result = respond(request)
            result["action"] = {"type": "probe", "x": 0, "y": 1}
            return result

        run = run_one(task, ("k", "implicit"), repetitive)
        self.assertFalse(run["hidden_pass"])
        self.assertEqual(run["probes"], 1)
        self.assertIn("duplicate", run["error"])
        with self.assertRaisesRegex(ValueError, "0..10"):
            validate_response({"action": {"type": "submit", "coefficients": {
                "a": 99, "b": 0, "c": 0, "d": 0}}}, ("k", "implicit"))

    def test_measured_token_cap_and_unknown_usage(self):
        task = make_tasks(11, 1)["tasks"][0]

        def measured(request):
            return {**respond(request), "metrics": {"total_tokens": 12}}

        over = run_one(task, ("k", "implicit"), measured,
                       max_total_tokens=25)
        self.assertTrue(over["budget_exhausted"])
        self.assertEqual(over["total_tokens"], 36)
        self.assertFalse(over["hidden_pass"])
        unknown = run_one(task, ("k", "implicit"), respond,
                          max_total_tokens=25)
        self.assertIn("Measured token usage", unknown["error"])
        self.assertFalse(unknown["hidden_pass"])

    def test_cli_subprocess_and_trace_outputs(self):
        agent = Path(__file__).with_name("discovery_baseline_agent.py").resolve()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "run"
            self.assertEqual(main(["--seed", "79", "--count", "4",
                                   "--agent", f"{sys.executable} {agent}",
                                   "--out", str(out), "--arm-seed", "17"]), 0)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual({name: value["successes"] for name, value
                              in summary["conditions"].items()},
                             {f"{a}_{b}": 4 for a, b in CONDITIONS})
            self.assertEqual(len(list(out.glob("*/*/trace.json"))), 16)


if __name__ == "__main__":
    unittest.main()
