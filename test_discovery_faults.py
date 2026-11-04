import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from analyze_recovery import analyze, audit_run, main as audit_main
from discovery_baseline_agent import respond
from discovery_pilot import CONDITIONS, main as discovery_main, make_tasks, run_one


class DiscoveryFaultTests(unittest.TestCase):
    def setUp(self):
        self.task = make_tasks(73, 1)["tasks"][0]

    def test_all_arms_recover_without_consuming_probe_budget(self):
        for condition in CONDITIONS:
            with self.subTest(condition=condition):
                clean = run_one(self.task, condition, respond)
                requests = []

                def recorded(request):
                    requests.append(copy.deepcopy(request))
                    return respond(request)

                faulted = run_one(self.task, condition, recorded,
                                  inject_probe_failure_at=1)
                self.assertTrue(clean["hidden_pass"])
                self.assertEqual(clean["turns"], 3)
                self.assertTrue(faulted["hidden_pass"])
                self.assertEqual(faulted["turns"], 4)
                self.assertEqual(faulted["probe_attempts"], 3)
                self.assertEqual(faulted["injected_faults"], 1)
                self.assertEqual(faulted["probes"], 2)
                self.assertEqual(requests[1]["probe_budget_remaining"], 3)
                self.assertEqual(requests[1]["observations"], requests[0]["observations"])
                self.assertEqual(requests[1]["last_tool_error"],
                                 {"kind": "transient_probe_failure", "retryable": True,
                                  "x": 0, "y": 1})
                self.assertNotIn("last_tool_error", requests[2])
                self.assertNotIn("_target", json.dumps(faulted))
                metrics = audit_run(faulted)
                self.assertEqual(metrics["retries"], 1)
                self.assertEqual(metrics["next_turn_retries"], 1)
                self.assertEqual(metrics["recovered_runs"], 1)

    def test_later_probe_injection_and_resource_exhaustion(self):
        case = run_one(self.task, ("k", "implicit"), respond,
                       inject_probe_failure_at=2)
        self.assertEqual(case["trace"][1]["environment_feedback"]["tool_error"]["x"], 1)
        self.assertEqual(case["probes"], 2)
        self.assertTrue(case["hidden_pass"])
        short = run_one(self.task, ("k", "implicit"), respond, max_turns=3,
                        inject_probe_failure_at=1)
        self.assertFalse(short["hidden_pass"])
        self.assertEqual(short["probes"], 2)
        self.assertEqual(short["injected_faults"], 1)
        self.assertIsNone(short["error"])

    def test_false_public_success_not_treated_as_recovery(self):
        def premature(request):
            result = respond(request)
            if "last_tool_error" in request:
                d = request["observations"][0]["value"]
                a = (request["observations"][1]["value"] - d) % 11
                result["action"] = {"type": "submit", "coefficients": {
                    "a": a, "b": 0, "c": 0, "d": d}}
            return result

        run = run_one(self.task, ("k", "implicit"), premature,
                      inject_probe_failure_at=1)
        self.assertTrue(run["public_pass"])
        self.assertFalse(run["hidden_pass"])
        audit = audit_run(run)
        self.assertEqual(audit["false_public_success"], 1)
        self.assertEqual(audit["retries"], 0)
        self.assertEqual(audit["recovered_runs"], 0)

    def test_strict_auditing_rejects_hidden_fault_and_preference(self):
        run = run_one(self.task, ("k", "explicit"), respond,
                      inject_probe_failure_at=1)
        tampered = copy.deepcopy(run)
        del tampered["trace"][1]["request"]["last_tool_error"]
        with self.assertRaisesRegex(ValueError, "fault evidence"):
            audit_run(tampered)
        tampered = copy.deepcopy(run)
        tampered["trace"][0]["environment_feedback"]["tool_error"]["x"] = 2
        with self.assertRaisesRegex(ValueError, "injected fault"):
            audit_run(tampered)
        tampered = copy.deepcopy(run)
        tampered["trace"][0]["request"]["schema"] = "kloop-private-preference-v1"
        with self.assertRaisesRegex(ValueError, "stratum"):
            audit_run(tampered)

    def test_paired_cli_and_control_delta(self):
        agent = Path(__file__).with_name("discovery_baseline_agent.py").resolve()
        with tempfile.TemporaryDirectory() as temp:
            clean, fault, report = [Path(temp) / name for name in
                                    ("clean", "fault", "report.json")]
            base_args = ["--seed", "31", "--count", "4", "--agent",
                         f"{sys.executable} {agent}", "--arm-seed", "19"]
            self.assertEqual(discovery_main(base_args + ["--out", str(clean)]), 0)
            self.assertEqual(discovery_main(base_args + ["--out", str(fault),
                                            "--inject-probe-failure-at", "1"]), 0)
            self.assertEqual(audit_main([str(fault), "--control", str(clean),
                                         "--expected-tasks", "4", "--out", str(report)]), 0)
            payload = json.loads(report.read_text())
            self.assertEqual(len(payload["evidence_sha256"]), 64)
            for arm in payload["by_arm"].values():
                self.assertEqual(arm["faults"], 4)
                self.assertEqual(arm["recovery_rate"], 1)
                self.assertEqual(arm["retry_rate"], 1)
                self.assertEqual(arm["mean_extra_turns_vs_control"], 1)
                self.assertEqual(arm["false_public_successes"], 0)
            fault_runs = [json.loads(p.read_text()) for p in fault.glob("*/*/trace.json")]
            with self.assertRaisesRegex(ValueError, "Unpaired"):
                analyze(fault_runs[:-1])

    def test_fault_parameter_validation(self):
        for invalid in (True, 0, -1, 4, "1"):
            with self.assertRaisesRegex(ValueError, "Fault injection"):
                run_one(self.task, ("k", "implicit"), respond,
                        inject_probe_failure_at=invalid)


if __name__ == "__main__":
    unittest.main()
