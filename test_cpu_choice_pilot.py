import json
import tempfile
import unittest
from pathlib import Path

from cpu_choice_pilot import FiniteChoiceAdapter, edit_options, execute, model_prompt
from pilot import CONDITIONS, make_tasks, validate_expr


class CpuChoicePilotTests(unittest.TestCase):
    def test_options_are_legal_and_reproducible_without_hidden_targets(self):
        task = make_tasks(1337, 1)["tasks"][0]
        options = edit_options(task["starter"])
        self.assertEqual(len(options), 5)
        self.assertEqual(options, edit_options(task["starter"]))
        self.assertEqual(options[4]["candidate"], task["starter"])
        self.assertTrue(all(validate_expr(option["candidate"]) for option in options))
        self.assertNotIn("_target", json.dumps(options))
        self.assertNotIn("_hidden", json.dumps(options))

    def test_prompt_excludes_evaluator_only_state_and_target(self):
        task = make_tasks(1337, 1)["tasks"][0]
        from pilot import request_for
        req = request_for(task, ("rich", "explicit"), 1, task["starter"], None, [])
        prompt = model_prompt(req, edit_options(req["candidate"]))
        self.assertIn("EDIT_CHOICES", prompt)
        self.assertNotIn("_hidden", prompt)
        self.assertNotIn("_target", prompt)
        self.assertNotIn("public_evaluation", prompt)

    def test_model_digit_not_model_authored_ast_or_usage(self):
        choices = []
        def rank(prompt):
            choices.append(prompt)
            return 2, 134, [0.1, 0.2, 0.9, -1.0, 0.0]
        task = make_tasks(1337, 1)["tasks"][0]
        from pilot import request_for
        req = request_for(task, ("k", "explicit"), 1, task["starter"], None, [])
        adapter = FiniteChoiceAdapter(rank)
        output = adapter(req)
        self.assertEqual(output["candidate"], edit_options(task["starter"])[2]["candidate"])
        self.assertEqual(output["metrics"]["total_tokens"], 134)
        self.assertEqual(output["metrics"]["completion_tokens"], 0)
        self.assertIn("established", output["ledger"])
        self.assertEqual(adapter.events[0]["choice_token"], "2")
        self.assertEqual(adapter.events[0]["choice_logits"][2], 0.9)
        self.assertEqual(len(choices), 1)

    def test_fail_closed_on_invalid_selected_index(self):
        task = make_tasks(1337, 1)["tasks"][0]
        from pilot import request_for
        req = request_for(task, ("k", "implicit"), 1, task["starter"], None, [])
        for bad in (-1, 5, "2", True):
            with self.subTest(bad=bad):
                adapter = FiniteChoiceAdapter(lambda p: (bad, 80, [1.0] * 5))
                with self.assertRaisesRegex(RuntimeError, "Invalid model decision"):
                    adapter(req)
                self.assertEqual(adapter.events, [])

    def test_entire_four_arm_path_model_selects_one_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "experiment"
            runs = execute(out, max_turns=2,
                           infer=lambda prompt: (1, 137, [0., 4., 1., -1., 0.]))
            self.assertEqual({r["condition"] for r in runs},
                             {f"{a}_{b}" for a, b in CONDITIONS})
            self.assertTrue(all(r["error"] is None for r in runs))
            self.assertTrue(all(r["total_tokens"] in (137, 274) for r in runs))
            self.assertTrue(all(r["turns"] in (1, 2) for r in runs))
            raw = (out / "model-decisions.jsonl").read_text().splitlines()
            self.assertEqual(len(raw), sum(r["turns"] for r in runs))
            events = [json.loads(line) for line in raw]
            self.assertTrue(all(event["metrics"]["completion_tokens"] == 0
                                for event in events))
            self.assertTrue(all("_target" not in event["prompt"] for event in events))
            self.assertTrue(all("_hidden" not in event["prompt"] for event in events))
            self.assertEqual(json.loads((out / "summary.json").read_text())["runs_completed"], 4)


if __name__ == "__main__":
    unittest.main()
