import json
import sys
import tempfile
import unittest
from pathlib import Path

from pilot import (CONDITIONS, aggregate, arm_schedule, evaluate, make_tasks,
                   request_for, results, run_one, validate_expr)


class PilotTests(unittest.TestCase):
    def test_deterministic_generation(self):
        self.assertEqual(make_tasks(1337, 4), make_tasks(1337, 4))
        self.assertNotEqual(make_tasks(1337, 4), make_tasks(1338, 4))

    def test_generated_tasks_valid_and_discriminating(self):
        for task in make_tasks(7, 20)["tasks"]:
            validate_expr(task["starter"])
            validate_expr(task["_target"])
            self.assertGreaterEqual(sum(not r["pass"] for r in
                                        results(task["starter"], task["public"])), 6)
            self.assertTrue(all(r["pass"] for r in results(task["_target"], task["_hidden"])))

    def test_no_hidden_or_target_leaks_into_requests(self):
        task = make_tasks(4, 1)["tasks"][0]
        for condition in CONDITIONS:
            request = request_for(task, condition, 1, task["starter"], None, [])
            self.assertNotIn("_hidden", json.dumps(request))
            self.assertNotIn("_target", json.dumps(request))
            self.assertEqual(request["human_signal"] == "K", condition[0] == "k")

    def test_reject_bad_expression(self):
        with self.assertRaises(ValueError):
            validate_expr({"op": "exec", "args": [{"var": "x"}, {"var": "y"}]})
        with self.assertRaises(ValueError):
            validate_expr({"const": True})
        with self.assertRaises(ValueError):
            validate_expr({"const": 100})

    def test_arithmetic(self):
        self.assertEqual(evaluate({"op": "sub", "args": [{"var": "x"},
                         {"op": "mul", "args": [{"var": "y"}, {"const": 2}]}]}, 4, 3), -2)

    def test_end_to_end_all_conditions(self):
        task = make_tasks(31, 1)["tasks"][0]
        agent = str(Path(__file__).with_name("baseline_agent.py").resolve())
        with tempfile.TemporaryDirectory() as tmp:
            runs = [run_one(task, c, [sys.executable, agent],
                            Path(tmp) / f"{c[0]}_{c[1]}", 5, 8) for c in CONDITIONS]
            self.assertEqual(len(runs), 4)
            self.assertTrue(all(r["error"] is None for r in runs))
            self.assertEqual(set(aggregate(runs)), {f"{a}_{b}" for a, b in CONDITIONS})

    def test_balanced_schedule_deterministic_and_positionally_balanced(self):
        task_ids = [f"t{i:04d}" for i in range(13)]
        first = arm_schedule(task_ids, mode="balanced", seed=125)
        self.assertEqual(first, arm_schedule(task_ids, mode="balanced", seed=125))
        self.assertNotEqual(first, arm_schedule(task_ids, mode="balanced", seed=126))
        for start in (0, 4, 8):
            block = [first[task] for task in task_ids[start:start + 4]]
            self.assertTrue(all(set(order) == set(CONDITIONS) for order in block))
            for position in range(4):
                self.assertEqual({order[position] for order in block}, set(CONDITIONS))
        with self.assertRaisesRegex(ValueError, "explicit integer seed"):
            arm_schedule(task_ids, mode="balanced")
        with self.assertRaisesRegex(ValueError, "unique"):
            arm_schedule(["t1", "t1"])

    def test_in_process_adapter_receives_public_only_request(self):
        task = make_tasks(88, 1)["tasks"][0]
        observed = []

        def adapter(request):
            wire = json.dumps(request)
            self.assertNotIn("_hidden", wire)
            self.assertNotIn("_target", wire)
            observed.append(request)
            return {"candidate": request["candidate"], "message": "No edit",
                    "ledger": {key: "unchanged" for key in (
                        "objective", "established", "falsified", "unresolved",
                        "next_action", "verification")},
                    "metrics": {"total_tokens": 30}}

        with tempfile.TemporaryDirectory() as tmp:
            run = run_one(task, ("k", "explicit"), None, Path(tmp),
                          2, 10, max_total_tokens=60, adapter=adapter)
        self.assertEqual(run["turns"], 2)
        self.assertEqual(run["total_tokens"], 60)
        self.assertEqual(len(observed), 2)
        self.assertIsNone(run["error"])


if __name__ == "__main__":
    unittest.main()
