import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from discovery_pilot import CONDITIONS, evaluate, main as discovery_main, make_tasks, run_one
from discovery_semantic_control import respond
from evidence_audit import (analyze, evidence_certificate, inference_certificate,
                            main as evidence_main)


class SemanticInferenceTests(unittest.TestCase):
    def setUp(self):
        self.task = make_tasks(191, 1)["tasks"][0]
        self.initial = self.task["initial"]

    def test_entailment_is_not_hidden_target_agreement(self):
        coefficients = self.task["_target"]
        ledger = {"inferences": [
            {"coefficient": "a", "value": coefficients["a"]},
            {"coefficient": "d", "value": coefficients["d"]},
            {"coefficient": "b", "value": coefficients["b"]},
            {"coefficient": "c", "value": coefficients["c"]}]}
        audit = inference_certificate(ledger, self.initial)
        self.assertEqual(audit["identifiable_coefficients"], ["a", "d"])
        self.assertEqual([c["classification"] for c in audit["claims"]],
                         ["entailed", "entailed", "underdetermined", "underdetermined"])
        self.assertEqual(audit["entailed_coefficient_coverage"], 1)
        self.assertEqual(audit["entailed"], 2)

    def test_wrong_identifiable_values_and_duplicate_claims(self):
        a = self.task["_target"]["a"]
        audit = inference_certificate({"inferences": [
            {"coefficient": "a", "value": (a + 1) % 11},
            {"coefficient": "a", "value": a},
            {"coefficient": "a", "value": a},
            {"coefficient": "a", "value": True},
            {"coefficient": "z", "value": 1},
            "a=5"]}, self.initial)
        self.assertEqual(audit["contradicted"], 1)
        self.assertEqual(audit["entailed"], 1)
        self.assertEqual(audit["duplicates"], 1)
        self.assertEqual(audit["malformed"], 3)
        self.assertEqual(audit["entailed_coefficient_coverage"], 0.5)

    def test_entailment_progression_and_inconsistent_premises(self):
        target = self.task["_target"]
        observations = copy.deepcopy(self.initial)
        for coordinate, identified, still_unknown in [
                ((0, 1), "b", "c"), ((1, 1), "c", None)]:
            x, y = coordinate
            observations.append({"x": x, "y": y,
                                 "value": evaluate(target, x, y)})
            claims = {"inferences": [
                {"coefficient": identified, "value": target[identified]}]}
            result = inference_certificate(claims, observations)
            self.assertEqual(result["entailed"], 1)
            if still_unknown:
                result = inference_certificate({"inferences": [
                    {"coefficient": still_unknown, "value": target[still_unknown]}]},
                    observations)
                self.assertEqual(result["underdetermined"], 1)
        duplicate = copy.deepcopy(self.initial)
        duplicate.append({"x": 2, "y": 0,
                          "value": (evaluate(target, 2, 0) + 1) % 11})
        self.assertFalse(evidence_certificate(duplicate)["consistent"])
        self.assertEqual(inference_certificate({"inferences": []}, duplicate)
                         ["status"], "inconsistent_evidence")

    def test_absent_and_empty_contracts_are_not_equated(self):
        self.assertEqual(inference_certificate({}, self.initial)["status"], "absent")
        self.assertEqual(inference_certificate({"inferences": "a=1"}, self.initial)
                         ["status"], "malformed_shape")
        empty = inference_certificate({"inferences": []}, self.initial)
        self.assertEqual(empty["status"], "scored")
        self.assertEqual(empty["entailed_coefficient_coverage"], 0)

    def test_semantic_control_reaches_full_coverage_without_hidden_access(self):
        for condition in CONDITIONS:
            with self.subTest(condition=condition):
                run = run_one(self.task, condition, respond,
                              inject_probe_failure_at=1)
                self.assertTrue(run["hidden_pass"])
                self.assertNotIn("_target", json.dumps(run))
                summary = analyze([run_one(self.task, arm, respond,
                                           inject_probe_failure_at=1)
                                   for arm in CONDITIONS])
                if condition[1] == "explicit":
                    state = summary["by_arm"]["_".join(condition)]["ledger_fidelity"]
                    inferences = state["semantic_inferences"]
                    self.assertEqual(inferences["declared_turns"], 4)
                    self.assertEqual(inferences["entailed"], 11)
                    self.assertEqual(inferences["contradicted"], 0)
                    self.assertEqual(inferences["underdetermined"], 0)
                    self.assertEqual(inferences["mean_entailed_coefficient_coverage"], 1)
                else:
                    self.assertIsNone(summary["by_arm"]["_".join(condition)]
                                      ["ledger_fidelity"])

    def test_subprocess_control_and_audit_cli(self):
        agent = Path(__file__).with_name("discovery_semantic_control.py").resolve()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            traces = root / "runs"
            report = root / "summary.json"
            self.assertEqual(discovery_main(["--seed", "9", "--count", "2",
                                             "--agent", f"{sys.executable} {agent}",
                                             "--out", str(traces),
                                             "--inject-probe-failure-at", "1"]), 0)
            self.assertEqual(evidence_main([str(traces), "--expected-tasks", "2",
                                            "--aggregate-only", "--out", str(report)]), 0)
            payload = json.loads(report.read_text())
            self.assertEqual(payload["schema"], "kloop-discovery-evidence-audit-v2")
            self.assertEqual(payload["by_arm"]["k_explicit"]["ledger_fidelity"]
                             ["semantic_inferences"]["mean_entailed_coefficient_coverage"], 1)


if __name__ == "__main__":
    unittest.main()
