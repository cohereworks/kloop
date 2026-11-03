import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from holdout_commitment import commitment, make_manifest
from private_trial import run_private, task_from_private_manifest


def manifest_for_test(count=4):
    digest = hashlib.sha256(Path(__file__).with_name("pilot.py").read_bytes()).hexdigest()
    return make_manifest(count=count, repetitions=1, pilot_sha256=digest)


class PrivateTrialTests(unittest.TestCase):
    def test_private_task_derivation_is_deterministic_and_separate(self):
        manifest = manifest_for_test()
        task0 = task_from_private_manifest(manifest, 0, 0)
        self.assertEqual(task0, task_from_private_manifest(manifest, 0, 0))
        self.assertEqual(task0["id"], "r000t0000")
        self.assertEqual(task_from_private_manifest(manifest, 0, 1)["id"], "r000t0001")

    def test_trusted_adapter_receives_public_only_and_schedule_is_balanced(self):
        manifest = manifest_for_test()
        public = commitment(manifest)
        sent = []

        def agent(request):
            wire = json.dumps(request)
            self.assertNotIn("_target", wire)
            self.assertNotIn("_hidden", wire)
            self.assertNotIn(manifest["nonce"], wire)
            sent.append(request)
            return {"candidate": request["candidate"], "message": "no edit",
                    "ledger": {field: "unresolved" for field in (
                        "objective", "established", "falsified", "unresolved",
                        "next_action", "verification")},
                    "metrics": {"total_tokens": 25}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            summary = run_private(manifest, public, root, agent,
                                  arm_seed=2026, max_turns=2,
                                  max_total_tokens=50,
                                  model_metadata={"model": "mock"})
            self.assertEqual(summary["paired_tasks"], 4)
            self.assertEqual(summary["arm_order"], "balanced")
            self.assertEqual(len(sent), 32)
            self.assertEqual(len(list(root.glob("*/*/trace.json"))), 16)
            self.assertEqual(summary["model_metadata"], {"model": "mock"})
            self.assertNotIn(manifest["nonce"], (root / "summary.json").read_text())
            self.assertNotIn(str(manifest["seed"]), (root / "summary.json").read_text())
            orders = list(summary["execution_schedule"].values())
            for position in range(4):
                self.assertEqual(len({order[position] for order in orders}), 4)
            for path in root.glob("*/*/trace.json"):
                trace = path.read_text()
                self.assertNotIn("_target", trace)
                self.assertNotIn("_hidden", trace)
            with self.assertRaisesRegex(ValueError, "new or empty"):
                run_private(manifest, public, root, agent, arm_seed=2026,
                            max_turns=2, max_total_tokens=50)

    def test_reject_stale_or_tampered_manifest(self):
        manifest = manifest_for_test(count=1)
        public = commitment(manifest)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Generator has changed"):
                bad = {**manifest, "pilot_sha256": "0" * 64}
                run_private(bad, commitment(bad), Path(directory) / "run",
                            lambda _: {}, arm_seed=1, max_turns=1, max_total_tokens=1)
            with self.assertRaisesRegex(ValueError, "does not match"):
                run_private({**manifest, "seed": manifest["seed"] + 1}, public,
                            Path(directory) / "run", lambda _: {}, arm_seed=1,
                            max_turns=1, max_total_tokens=1)


if __name__ == "__main__":
    unittest.main()
