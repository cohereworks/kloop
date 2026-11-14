import json
import tempfile
import unittest
from pathlib import Path

from cpu_choice_permutation import execute, permutation_probe
from pilot import make_tasks, request_for


class PermutationProbeTests(unittest.TestCase):
    def setUp(self):
        task = make_tasks(1337, 1)["tasks"][0]
        self.request = request_for(task, ("k", "implicit"), 1,
                                   task["starter"], None, [])

    def test_position_biased_positive_control(self):
        probe = permutation_probe(lambda p: (0, 50, [5., 4., 3., 2., 1.]),
                                  self.request)
        self.assertTrue(probe["all_choose_first_label"])
        self.assertEqual(probe["chosen_edit_unique_count"], 5)
        self.assertFalse(probe["semantic_choice_invariant"])
        self.assertEqual({r["original_option_index"] for r in probe["rows"]},
                         set(range(5)))

    def test_semantic_anchor_positive_control(self):
        def anchored(prompt):
            items = json.loads(prompt.split("EDIT_CHOICES:\n")[1].split("\nAnswer")[0])
            idx = next(i for i, obj in enumerate(items)
                       if obj["field"] == "op" and obj["path"] == [] and
                       obj["value"] == "add")
            return idx, 50, [0.] * 5
        probe = permutation_probe(anchored, self.request)
        self.assertTrue(probe["semantic_choice_invariant"])
        self.assertFalse(probe["all_choose_first_label"])
        self.assertEqual(probe["chosen_edit_unique_count"], 1)
        self.assertEqual(probe["chosen_index_unique_count"], 5)

    def test_malformed_choice_fails_closed(self):
        with self.assertRaises(RuntimeError):
            permutation_probe(lambda p: ("0", 50, [1.] * 5), self.request)
        with self.assertRaises(RuntimeError):
            permutation_probe(lambda p: (0, 50, [1.] * 4), self.request)

    def test_complete_probe_preserves_prompt_and_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "results"
            result = execute(root, infer=lambda p: (0, 60, [3., 2., 1., 0., -1.]))
            recorded = json.loads((root / "rotation-analysis.json").read_text())
            self.assertEqual(result, recorded)
            self.assertEqual(len(recorded["rows"]), 5)
            self.assertTrue(all("_target" not in r["prompt"] and
                                "_hidden" not in r["prompt"]
                                for r in recorded["rows"]))
            self.assertEqual(len({r["prompt_sha256"] for r in recorded["rows"]}), 5)
            with self.assertRaisesRegex(ValueError, "empty"):
                execute(root, infer=lambda p: (0, 60, [3., 2., 1., 0., -1.]))


if __name__ == "__main__":
    unittest.main()
