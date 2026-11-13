import json
import tempfile
import unittest
from pathlib import Path

from api_agent import ModelResponseError
from cpu_openweight_pilot import CpuAdapter, execute


class CpuOpenweightTests(unittest.TestCase):
    @staticmethod
    def reply(system, user):
        request = json.loads(user)
        assert "_hidden" not in user and "_target" not in user
        return json.dumps({
            "candidate": request["candidate"],
            "message": "No change",
            "ledger": {"objective": "fit", "established": [], "falsified": [],
                       "unresolved": [], "next_action": "retry", "verification": "public"},
            "metrics": {"total_tokens": 0, "model": "forged"}
        }), 13, 8

    def test_json_and_unforgeable_metering(self):
        adapter = CpuAdapter(self.reply)
        result = adapter({"candidate": {"var": "x"}})
        self.assertEqual(result["metrics"]["total_tokens"], 21)
        self.assertEqual(result["metrics"]["usage_provenance"], "local_tokenizer_exact")
        self.assertEqual(len(adapter.events), 1)
        self.assertIn('"candidate"', adapter.events[0]["raw_model_text"])

    def test_malformed_keeps_local_token_counts_and_raw_evidence(self):
        adapter = CpuAdapter(lambda a, b: ("no JSON", 15, 5))
        with self.assertRaises(ModelResponseError) as caught:
            adapter({"candidate": {"var": "x"}})
        self.assertEqual(caught.exception.metrics["total_tokens"], 20)
        self.assertEqual(adapter.events[0]["raw_model_text"], "no JSON")

    def test_one_task_four_arms_and_source_separation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            runs = execute(out, max_turns=2, generate=self.reply)
            self.assertEqual(len(runs), 4)
            self.assertEqual({r["condition"] for r in runs},
                             {"k_explicit", "k_implicit", "rich_explicit", "rich_implicit"})
            self.assertTrue(all(r["error"] is None and r["total_tokens"] == 42 for r in runs))
            self.assertEqual(len((out / "raw-responses.jsonl").read_text().splitlines()), 8)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["runs_completed"], 4)
            self.assertEqual(summary["manifest"]["kind"],
                             "cpu_openweight_exploratory_not_confirmatory")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                execute(out, generate=self.reply)

    def test_malformed_still_yields_auditable_four_arm_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            runs = execute(out, generate=lambda a, b: ("invalid", 11, 4))
            self.assertTrue(all(r["error"] and r["total_tokens"] == 15 for r in runs))
            self.assertEqual(len((out / "raw-responses.jsonl").read_text().splitlines()), 4)


if __name__ == "__main__":
    unittest.main()
