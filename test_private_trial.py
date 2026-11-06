import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from api_agent import ModelResponseError, ProviderModelDriftError
from holdout_commitment import commitment, make_manifest
from private_trial import make_pinned_adapter, run_private, task_from_private_manifest


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

    def test_pinned_model_detects_drift_even_on_malformed_content(self):
        identities = iter(("original", "different"))

        def malformed(_request, *, resolved_config):
            self.assertEqual(resolved_config, ("fixed",))
            raise ModelResponseError("Malformed model JSON",
                                     {"model": next(identities), "total_tokens": 17})

        pinned = make_pinned_adapter(malformed, ("fixed",))
        with self.assertRaises(ModelResponseError) as first:
            pinned({"turn": 1})
        self.assertNotIsInstance(first.exception, ProviderModelDriftError)
        with self.assertRaisesRegex(ProviderModelDriftError, "identity drifted") as second:
            pinned({"turn": 2})
        self.assertEqual(second.exception.metrics["total_tokens"], 17)

    def test_model_drift_aborts_private_trial_with_partial_trace(self):
        manifest = manifest_for_test(count=1)
        public = commitment(manifest)
        calls = [0]

        def drift(request):
            calls[0] += 1
            if calls[0] == 2:
                raise ProviderModelDriftError("Provider model identity drifted during trial",
                                              {"model": "different", "total_tokens": 25})
            return {"candidate": request["candidate"], "metrics": {"total_tokens": 25},
                    "ledger": {field: "unresolved" for field in (
                        "objective", "established", "falsified", "unresolved",
                        "next_action", "verification")}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            with self.assertRaisesRegex(RuntimeError, "private trial aborted"):
                run_private(manifest, public, root, drift, arm_seed=5,
                            max_turns=2, max_total_tokens=100)
            self.assertEqual(calls[0], 2)
            self.assertFalse((root / "summary.json").exists())
            abort = json.loads((root / "abort.json").read_text())
            self.assertEqual(abort["reason"], "provider_model_identity_drift")
            self.assertEqual(abort["runs_recorded"], 1)
            record = json.loads((root / abort["last_trace"]).read_text())
            self.assertEqual(record["total_tokens"], 50)
            self.assertEqual(record["reported_token_lower_bound"], 50)
            self.assertIn("different", json.dumps(record["trace"][-1]["error_metrics"]))
            self.assertNotIn(manifest["nonce"], (root / "abort.json").read_text())

    def test_unmetered_error_does_not_claim_private_budget_compliance(self):
        manifest = manifest_for_test(count=1)
        public = commitment(manifest)

        def unavailable(_):
            raise RuntimeError("HTTP endpoint unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            summary = run_private(manifest, public, root, unavailable,
                                  arm_seed=5, max_turns=1, max_total_tokens=100)
            self.assertTrue(all(row["total_tokens"] is None
                                for row in summary["conditions"].values()))
            self.assertEqual(len(list(root.glob("*/*/trace.json"))), 4)
            for path in root.glob("*/*/trace.json"):
                record = json.loads(path.read_text())
                self.assertIsNone(record["total_tokens"])
                self.assertIsNone(record["within_budget"])
                self.assertEqual(record["reported_token_lower_bound"], 0)
                self.assertFalse(record["hidden_pass"])


if __name__ == "__main__":
    unittest.main()
