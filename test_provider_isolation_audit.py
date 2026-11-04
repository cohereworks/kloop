import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from provider_isolation_audit import main, run_audit


def memoryless(request, instructions):
    if request["stage"] == "exposure":
        result = {"ack": True}
    else:
        result = {"remembered_canary": None}
    return {**result, "metrics": {"total_tokens": 4, "model": "mock"}}


class IsolationAuditTests(unittest.TestCase):
    def test_memoryless_provider_is_inconclusive_not_proven_isolated(self):
        report = run_audit(memoryless, rounds=2, max_total_tokens=100,
                           canary_factory=iter(["a" * 32, "b" * 32]).__next__)
        self.assertEqual(report["status"], "not_detected_in_test")
        self.assertEqual(report["rounds_completed"], 2)
        self.assertEqual(report["total_tokens"], 24)
        self.assertIn("does not prove", report["warning"])
        for entry in report["observations"]:
            canary = entry["synthetic_canary"]
            self.assertTrue(any(canary in json.dumps(event["request"])
                                for event in report["events"]
                                if event["stage"] == "exposure"))
            self.assertTrue(all(canary not in json.dumps(event["request"])
                                for event in report["events"]
                                if event["stage"] == "probe"))

    def test_stateful_provider_positive_control_detects_exact_leak(self):
        remembered = [None]

        def stateful(request, instructions):
            if request["stage"] == "exposure":
                remembered[0] = request["canary"]
                return {"ack": True, "metrics": {"total_tokens": 3, "model": "mock"}}
            return {"remembered_canary": remembered[0],
                    "metrics": {"total_tokens": 3, "model": "mock"}}

        report = run_audit(stateful, rounds=2, max_total_tokens=100,
                           canary_factory=iter(["c" * 32, "d" * 32]).__next__)
        self.assertEqual(report["status"], "leakage_observed")
        self.assertEqual(report["exact_leaks"], 2)
        self.assertEqual(report["rounds_completed"], 2)

    def test_unexpected_recall_and_protocol_fail_closed(self):
        def hallucinating(request, instructions):
            return {"ack": True, "remembered_canary": "f" * 32,
                    "metrics": {"total_tokens": 1, "model": "mock"}}

        result = run_audit(hallucinating, rounds=1, max_total_tokens=100,
                           canary_factory=lambda: "e" * 32)
        self.assertEqual(result["status"], "ambiguous_recall")

        def missing_usage(request, instructions):
            return {"remembered_canary": None, "metrics": {"model": "mock"}}

        failed = run_audit(missing_usage, rounds=1, max_total_tokens=100)
        self.assertEqual(failed["status"], "protocol_error")
        self.assertIn("measured token", failed["protocol_error"])

        capped = run_audit(memoryless, rounds=1, max_total_tokens=8,
                           canary_factory=lambda: "a" * 32)
        self.assertEqual(capped["status"], "protocol_error")
        self.assertIn("token cap", capped["protocol_error"])

    def test_provider_model_identity_drift(self):
        calls = [0]

        def drifting(request, instructions):
            calls[0] += 1
            response = memoryless(request, instructions)
            if calls[0] > 1:
                response["metrics"]["model"] = "other"
            return response

        report = run_audit(drifting, rounds=1, max_total_tokens=100)
        self.assertEqual(report["status"], "protocol_error")
        self.assertIn("identity drifted", report["protocol_error"])

    def test_cli_uses_pinned_http_config_without_secret_in_report(self):
        config = ("https://example.org/v1/chat/completions", "do-not-log",
                  {"model": "mock", "max_completion_tokens": 128}, 2)
        calls = []

        def mock_call(request, *, resolved_config, instructions):
            self.assertIs(resolved_config, config)
            calls.append((request, instructions))
            return memoryless(request, instructions)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "isolation.json"
            with patch("api_agent.configuration", return_value=config), \
                    patch("api_agent.call_model", side_effect=mock_call):
                self.assertEqual(main(["--out", str(output), "--rounds", "2",
                                       "--max-total-tokens", "100"]), 0)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "not_detected_in_test")
            self.assertEqual(len(calls), 6)
            self.assertNotIn("do-not-log", output.read_text())
            self.assertEqual(report["endpoint_origin"], "https://example.org")


if __name__ == "__main__":
    unittest.main()
