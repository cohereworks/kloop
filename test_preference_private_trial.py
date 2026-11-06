import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api_agent import ModelResponseError, ProviderModelDriftError
from holdout_commitment import write_new
from pilot import CONDITIONS
from preference_baseline_agent import respond
from preference_holdout import (code_hashes, commitment, main as holdout_main,
                               make_manifest, verify)
from preference_private_trial import (arm_public_id, main, make_pinned_adapter,
                                      run_private,
                                      task_from_private_manifest)


class PreferencePrivateTrialTests(unittest.TestCase):
    def test_manifest_secret_and_binding(self):
        manifest = make_manifest(count=8, repetitions=2)
        public = commitment(manifest)
        self.assertTrue(verify(manifest, public))
        self.assertEqual({key: public[key] for key in code_hashes()}, code_hashes())
        self.assertNotIn(manifest["secret_key"], json.dumps(public))
        self.assertNotIn("secret_key", json.dumps(public))
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify({**manifest, "secret_key": "f" * 64}, public)
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify(manifest, {**public, "task_count": 1})

    def test_private_derivation_is_stable_and_arm_ids_unlinkable(self):
        manifest = {**make_manifest(count=8, repetitions=1),
                    "secret_key": "ab" * 32}
        task = task_from_private_manifest(manifest, 0, 0)
        self.assertEqual(task, task_from_private_manifest(manifest, 0, 0))
        self.assertEqual(task["id"], "r000p0000")
        self.assertIn(task["_preference"], range(8))
        identifiers = [arm_public_id(manifest, rep, index, cond)
                       for rep in range(2) for index in range(8)
                       for cond in CONDITIONS]
        self.assertEqual(len(set(identifiers)), 64)
        self.assertTrue(all(len(value) == 32 for value in identifiers))
        self.assertTrue(all("r000p" not in value for value in identifiers))

    def test_trusted_projection_and_all_four_arm_baselines(self):
        manifest = make_manifest(count=8, repetitions=1)
        public = commitment(manifest)
        requests = []

        def agent(request):
            wire = json.dumps(request)
            self.assertNotIn(manifest["secret_key"], wire)
            self.assertNotIn("_preference", wire)
            self.assertNotIn("secret_key", wire)
            self.assertNotIn("r000p", wire)
            requests.append(request)
            return {**respond(request), "metrics": {"total_tokens": 7, "model": "mock"}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            summary = run_private(manifest, public, root, agent,
                                  arm_seed=20261103, max_turns=5,
                                  max_total_tokens=50,
                                  model_metadata={"model": "mock"})
            self.assertEqual(summary["paired_tasks"], 8)
            self.assertEqual(summary["arm_order"], "balanced")
            self.assertEqual(summary["model_metadata"], {"model": "mock"})
            self.assertEqual(len(list(root.glob("*/*/trace.json"))), 32)
            self.assertEqual({arm: entry["n"] for arm, entry in
                              summary["conditions"].items()},
                             {"k_implicit": 8, "k_explicit": 8,
                              "rich_implicit": 8, "rich_explicit": 8})
            favorites = [task_from_private_manifest(manifest, 0, index)["_preference"]
                         for index in range(8)]
            k_success = sum(preference == 4 for preference in favorites)
            rich_success = sum(preference in range(5) for preference in favorites)
            self.assertEqual(summary["conditions"]["k_implicit"]["successes"], k_success)
            self.assertEqual(summary["conditions"]["k_explicit"]["successes"], k_success)
            self.assertEqual(summary["conditions"]["rich_implicit"]["successes"], rich_success)
            self.assertEqual(summary["conditions"]["rich_explicit"]["successes"], rich_success)
            self.assertEqual(len(set(request["task"]["id"] for request in requests)), 32)
            self.assertEqual(len(set(request["task"]["id"] for request in requests
                                     if request["condition"]["feedback"] == "k")), 16)
            first_turn_ids = [request["task"]["id"] for request in requests
                              if request["turn"] == 1]
            self.assertEqual(len(set(first_turn_ids[:8])), 8)
            self.assertEqual(len(summary["dispatch_order"]), 32)
            self.assertEqual(summary["dispatch_strategy"],
                             "position-interleaved-permuted-tasks")
            self.assertNotIn(manifest["secret_key"], (root / "summary.json").read_text())
            for file in root.glob("*/*/trace.json"):
                record = json.loads(file.read_text())
                self.assertEqual(record["task"], file.parent.parent.name)
                self.assertNotEqual(record["arm_public_id"], record["task"])
                self.assertNotIn("_preference", file.read_text())
                self.assertNotIn(manifest["secret_key"], file.read_text())
            orders = list(summary["execution_schedule"].values())
            for position in range(4):
                self.assertEqual(len({order[position] for order in orders[:4]}), 4)
            with self.assertRaisesRegex(ValueError, "new or empty"):
                run_private(manifest, public, root, agent, arm_seed=1,
                            max_turns=5, max_total_tokens=50)

    def test_reject_manifest_tamper_and_changed_code(self):
        manifest = make_manifest(count=1, repetitions=1)
        public = commitment(manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            with self.assertRaisesRegex(ValueError, "does not match"):
                run_private({**manifest, "secret_key": "00" * 32}, public,
                            root, lambda _: {}, arm_seed=1, max_turns=1,
                            max_total_tokens=1)
            with patch("preference_private_trial.code_hashes", return_value={
                    **code_hashes(), "preference_pilot_sha256": "0" * 64}):
                with self.assertRaisesRegex(ValueError, "changed since commitment"):
                    run_private(manifest, public, root, lambda _: {},
                                arm_seed=1, max_turns=1, max_total_tokens=1)

    def test_cli_create_verify_and_pinned_model_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private.json"
            public = root / "public.json"
            self.assertEqual(holdout_main(["create", "--private", str(private),
                                           "--commitment", str(public),
                                           "--count", "2"]), 0)
            self.assertEqual(holdout_main(["verify", "--private", str(private),
                                           "--commitment", str(public)]), 0)
            config = ("https://example.org/v1/chat/completions", "placeholder",
                      {"model": "fixed", "max_completion_tokens": 10}, 2)
            calls = []

            def mock_model(request, *, resolved_config, instructions):
                self.assertIs(resolved_config, config)
                self.assertIn("private preference", instructions)
                calls.append(request)
                # Simulate an unexpected model switch on the second call.
                model = "fixed" if len(calls) == 1 else "unexpected"
                return {**respond(request), "metrics": {
                    "model": model, "total_tokens": 4}}

            with patch("api_agent.configuration", return_value=config), \
                    patch("api_agent.call_model", side_effect=mock_model):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), \
                        self.assertRaises(SystemExit) as stopped:
                    main(["--private", str(private),
                          "--commitment", str(public),
                          "--out", str(root / "run"),
                          "--arm-seed", "13", "--max-total-tokens", "50"])
                self.assertEqual(stopped.exception.code, 2)
                self.assertIn("identity drifted", stderr.getvalue())
            self.assertEqual(len(calls), 2)
            traces = list((root / "run").glob("*/*/trace.json"))
            self.assertLessEqual(len(traces), 2)
            self.assertTrue(any("model identity drifted" in path.read_text()
                                for path in traces))
            abort = json.loads((root / "run" / "abort.json").read_text())
            self.assertEqual(abort["reason"], "provider_model_identity_drift")
            self.assertEqual(abort["runs_recorded"], len(traces))
            self.assertFalse((root / "run" / "summary.json").exists())

    def test_preference_model_drift_in_malformed_message_is_detected(self):
        identities = iter(("original", "replacement"))

        def malformed(_request, *, resolved_config, instructions):
            self.assertEqual(resolved_config, "pinned")
            self.assertEqual(instructions, "fixed instructions")
            raise ModelResponseError("Invalid model JSON",
                                     {"model": next(identities), "total_tokens": 10})

        pinned = make_pinned_adapter(malformed, "pinned", "fixed instructions")
        with self.assertRaises(ModelResponseError) as first:
            pinned({})
        self.assertNotIsInstance(first.exception, ProviderModelDriftError)
        with self.assertRaises(ProviderModelDriftError) as second:
            pinned({})
        self.assertEqual(second.exception.metrics["total_tokens"], 10)

    def test_preference_private_unknown_cost_has_no_budget_verdict(self):
        manifest = make_manifest(count=1, repetitions=1)
        public = commitment(manifest)

        def unavailable(_):
            raise RuntimeError("HTTP transport failure")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "preference"
            summary = run_private(manifest, public, root, unavailable,
                                  arm_seed=1, max_turns=1, max_total_tokens=100)
            self.assertEqual(sum(row["tokens_reported"] for row in
                                 summary["conditions"].values()), 0)
            for path in root.glob("*/*/trace.json"):
                record = json.loads(path.read_text())
                self.assertIsNone(record["total_tokens"])
                self.assertIsNone(record["within_budget"])
                self.assertEqual(record["reported_token_lower_bound"], 0)


if __name__ == "__main__":
    unittest.main()
