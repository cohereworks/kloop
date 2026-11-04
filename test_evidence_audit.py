import copy
import json
import tempfile
import unittest
from pathlib import Path

from discovery_baseline_agent import respond
from discovery_pilot import CONDITIONS, evaluate, make_tasks, run_one
from evidence_audit import (analyze, certify_run, evidence_certificate,
                            ledger_certificate, main as evidence_main, matrix_rank)
from pilot import write_json


class EvidenceAuditTests(unittest.TestCase):
    def setUp(self):
        self.task = make_tasks(73, 1)["tasks"][0]

    def test_rank_and_solution_count_are_independently_verifiable(self):
        points = copy.deepcopy(self.task["initial"])
        c = evidence_certificate(points)
        self.assertTrue(c["consistent"])
        self.assertEqual(c["coefficient_rank"], 2)
        self.assertEqual(c["compatible_hypotheses"], 121)
        points.append({"x": 2, "y": 0,
                       "value": evaluate(self.task["_target"], 2, 0)})
        self.assertEqual(evidence_certificate(points)["compatible_hypotheses"], 121)
        points.append({"x": 0, "y": 1,
                       "value": evaluate(self.task["_target"], 0, 1)})
        self.assertEqual(evidence_certificate(points)["compatible_hypotheses"], 11)
        points.append({"x": 1, "y": 1,
                       "value": evaluate(self.task["_target"], 1, 1)})
        self.assertEqual(evidence_certificate(points)["compatible_hypotheses"], 1)
        self.assertEqual(evidence_certificate(points)["basis_pivot_columns"], [0, 1, 2, 3])
        self.assertEqual(matrix_rank([[1, 0], [2, 0], [0, 1]]), (2, [0, 1]))
        wrong = copy.deepcopy(points)
        wrong[2]["value"] = (wrong[2]["value"] + 1) % 11
        self.assertFalse(evidence_certificate(wrong)["consistent"])
        self.assertEqual(evidence_certificate(wrong)["compatible_hypotheses"], 0)

    def test_baseline_certificates_are_consistent_across_arms(self):
        for condition in CONDITIONS:
            with self.subTest(condition=condition):
                run = run_one(self.task, condition, respond,
                              inject_probe_failure_at=1)
                cert = certify_run(run)
                self.assertEqual(cert["relevant_probes"], 2)
                self.assertEqual(cert["redundant_probes"], 0)
                self.assertEqual(cert["underidentified_submissions"], 0)
                self.assertEqual([turn["before"]["coefficient_rank"]
                                  for turn in cert["turn_certificates"]], [2, 2, 3, 4])
                self.assertEqual([turn["rank_gain"]
                                  for turn in cert["turn_certificates"]], [0, 1, 1, None])
                if condition[1] == "explicit":
                    self.assertTrue(all(turn["ledger"]["shape_valid"]
                                        for turn in cert["turn_certificates"]))
                    self.assertTrue(all(turn["ledger"]["observation_reference_coverage"] == 1
                                        for turn in cert["turn_certificates"]))
                else:
                    self.assertTrue(all(turn["ledger"] is None
                                        for turn in cert["turn_certificates"]))

    def test_redundant_probe_detected_without_revealing_hidden_target(self):
        def redundant_then_solve(request):
            result = respond(request)
            observations = {(p["x"], p["y"]) for p in request["observations"]}
            if (2, 0) not in observations:
                result["action"] = {"type": "probe", "x": 2, "y": 0}
            return result

        run = run_one(self.task, ("k", "explicit"), redundant_then_solve)
        self.assertTrue(run["hidden_pass"])
        self.assertEqual(run["probes"], 3)
        cert = certify_run(run)
        self.assertEqual(cert["relevant_probes"], 2)
        self.assertEqual(cert["redundant_probes"], 1)
        self.assertEqual(cert["probe_relevance_rate"], 2 / 3)
        self.assertNotIn("_target", json.dumps(cert))

    def test_ledger_claims_are_scored_conservatively(self):
        obs = self.task["initial"]
        wrong = (obs[0]["value"] + 1) % 11
        claims = {"established": ["0,0", "1,0", "2,2", f"0,0={wrong}",
                                  "I know the answer", {"x": 1, "y": 0,
                                                        "value": obs[1]["value"]}],
                  "next_action": "probe", "unresolved": ["unknown"],
                  "falsified": []}
        cert = ledger_certificate(claims, obs, {"type": "submit"})
        self.assertEqual(cert["verified_references"], 2)
        self.assertEqual(cert["verified_values"], 1)
        self.assertEqual(cert["duplicate_references"], 1)
        self.assertEqual(cert["unsupported_references"], 1)
        self.assertEqual(cert["contradicted_values"], 1)
        self.assertEqual(cert["uncertifiable_claims"], 1)
        self.assertEqual(cert["observation_reference_coverage"], 1)
        self.assertFalse(cert["next_action_alignment"])
        invalid = ledger_certificate({"established": "I know", "next_action": "probe"},
                                     obs, {"type": "probe"})
        self.assertFalse(invalid["shape_valid"])
        self.assertIsNone(invalid["claim_certification_rate"])
        self.assertTrue(invalid["next_action_alignment"])

    def test_underidentified_submission_even_when_public_passes(self):
        def guessing(request):
            result = respond(request)
            d = request["observations"][0]["value"]
            a = (request["observations"][1]["value"] - d) % 11
            result["action"] = {"type": "submit", "coefficients": {
                "a": a, "b": 0, "c": 0, "d": d}}
            return result

        run = run_one(self.task, ("k", "implicit"), guessing)
        self.assertTrue(run["public_pass"])
        self.assertFalse(run["hidden_pass"])
        self.assertEqual(certify_run(run)["underidentified_submissions"], 1)

    def test_paired_summary_and_stratum_rejection(self):
        runs = [run_one(self.task, arm, respond) for arm in CONDITIONS]
        summary = analyze(runs)
        self.assertEqual(summary["n_paired_tasks"], 1)
        self.assertEqual(summary["by_arm"]["k_explicit"]["ledger_fidelity"]
                         ["mean_observation_reference_coverage"], 1)
        self.assertIsNone(summary["by_arm"]["k_implicit"]["ledger_fidelity"])
        self.assertEqual(summary["by_arm"]["rich_explicit"]["relevant_probes"], 2)
        tampered = copy.deepcopy(runs)
        tampered[0]["trace"][0]["request"]["schema"] = "kloop-private-preference-v1"
        with self.assertRaisesRegex(ValueError, "stratum"):
            analyze(tampered)

    def test_cli_preserves_evidence_digest_and_omits_only_certificate_detail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for arm in CONDITIONS:
                path = root / "runs" / self.task["id"] / "_".join(arm) / "trace.json"
                write_json(path, run_one(self.task, arm, respond))
            detail = root / "detail.json"
            summary = root / "summary.json"
            base = [str(root / "runs"), "--expected-tasks", "1"]
            self.assertEqual(evidence_main(base + ["--out", str(detail)]), 0)
            self.assertEqual(evidence_main(base + ["--aggregate-only", "--out",
                                                   str(summary)]), 0)
            full, compact = [json.loads(path.read_text()) for path in (detail, summary)]
            self.assertEqual(full["evidence_sha256"], compact["evidence_sha256"])
            self.assertEqual(full["by_arm"], compact["by_arm"])
            self.assertEqual(len(full["certificates"]), 4)
            self.assertNotIn("certificates", compact)


if __name__ == "__main__":
    unittest.main()
