import json
import os
import copy
import contextlib
import io
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from discovery_channel_api_agent import INSTRUCTIONS, call_channel_model
from analyze_channel_hosted import analyze
from discovery_channel_codec import PREFIX, encode_facts
from discovery_channel_control import respond
from discovery_channel_match import MATCHED_SCHEMA
from discovery_channel_model_trial import main, run_trial


class ChannelProviderStub(BaseHTTPRequestHandler):
    requests = []
    reported_tokens = 30
    drift_after = None
    bad_content_at = None
    missing_usage_at = None

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        envelope = json.loads(body)
        self.__class__.requests.append(envelope)
        request = json.loads(envelope["messages"][1]["content"])
        answer = respond(request)
        # Adapter must overwrite model-generated metrics, not trust this claim.
        answer["metrics"] = {"total_tokens": -9999, "model": "fake"}
        identity = ("drifted" if self.drift_after is not None and
                    len(self.requests) > self.drift_after else envelope["model"])
        content = ("INVALID_MODEL_JSON"
                   if len(self.requests) == self.bad_content_at
                   else json.dumps(answer))
        reply = {"id": f"stub-{len(self.requests)}", "model": identity,
                 "choices": [{"finish_reason": "stop", "message": {
                     "content": content}}],
                 "usage": (None if len(self.requests) == self.missing_usage_at
                           else {"prompt_tokens": self.reported_tokens - 10,
                                 "completion_tokens": 10,
                                 "total_tokens": self.reported_tokens})}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class ChannelHostedTrialTests(unittest.TestCase):
    def test_contract_prompt_identical_for_both_carriers(self):
        for state in ("explicit", "implicit"):
            request = {"schema": MATCHED_SCHEMA, "condition": {"state": state}}
            with patch("discovery_channel_api_agent.call_model",
                       return_value={"action": {}}) as stub:
                call_channel_model(request)
                self.assertEqual(stub.call_args.kwargs["instructions"], INSTRUCTIONS)
        with self.assertRaisesRegex(ValueError, "matched-channel"):
            call_channel_model({"schema": "wrong"})
        self.assertIn("same capacity-limited set", INSTRUCTIONS)

    def test_mock_http_full_route_with_response_metering(self):
        ChannelProviderStub.requests = []
        ChannelProviderStub.reported_tokens = 30
        ChannelProviderStub.drift_after = None
        ChannelProviderStub.bad_content_at = None
        ChannelProviderStub.missing_usage_at = None
        server = ThreadingHTTPServer(("127.0.0.1", 0), ChannelProviderStub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = (f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                  None, {"model": "mock-constant", "max_completion_tokens": 256,
                         "response_format": {"type": "json_object"}}, 5)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "mock-calibration"
                result = run_trial(out, lambda req: call_channel_model(
                    req, resolved_config=config), seed=1337, arm_seed=20261106,
                    count=4, state_bytes=48, max_total_tokens=100)
                self.assertEqual(len(ChannelProviderStub.requests), 48)
                self.assertTrue(all(v["hidden_successes"] == 4
                                    for v in result["by_arm"].values()))
                self.assertTrue(all(v["provider_reported_total_tokens"] == 360
                                    and v["usage_complete"]
                                    for v in result["by_arm"].values()))
                self.assertEqual(len(list(out.glob("*/*/trace.json"))), 16)
                replay = analyze(out)
                self.assertEqual(replay["runs_replayed"], 16)
                self.assertEqual(replay["response_turns_audited"], 48)
                self.assertEqual(replay["unmetered_error_runs"], 0)
                for file in out.glob("*/*/trace.json"):
                    record = json.loads(file.read_text())
                    self.assertIsNotNone(record["channel_audit"])
                    self.assertEqual(record["total_tokens"], 90)
                    self.assertNotIn("_target", file.read_text())
                    self.assertTrue(all(event["response"]["metrics"]["model"]
                                        == "mock-constant" for event in record["trace"]))
                self.assertTrue(all(payload["messages"][0]["content"] == INSTRUCTIONS
                                    for payload in ChannelProviderStub.requests))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_budget_excess_and_missing_usage_cannot_score_as_success(self):
        def metered(request):
            return {**respond(request), "metrics": {"total_tokens": 60,
                                                    "model": "mock"}}

        def unmetered(request):
            return respond(request)

        with tempfile.TemporaryDirectory() as tmp:
            excessive = run_trial(Path(tmp) / "excess", metered, seed=1337,
                                  arm_seed=17, count=1, state_bytes=48,
                                  max_total_tokens=100)
            self.assertTrue(all(v["over_budget"] == 1 and v["hidden_successes"] == 0
                                for v in excessive["by_arm"].values()))
            missing = run_trial(Path(tmp) / "missing", unmetered, seed=1337,
                                arm_seed=17, count=1, state_bytes=48,
                                max_total_tokens=100)
            self.assertTrue(all(v["protocol_errors"] == 1 and not v["usage_complete"]
                                for v in missing["by_arm"].values()))
            one = json.loads(next((Path(tmp) / "missing").glob("*/*/trace.json")).read_text())
            self.assertIsNone(one["total_tokens"])
            self.assertIsNone(one["within_budget"])
            replay = analyze(Path(tmp) / "missing")
            self.assertEqual(replay["unmetered_error_runs"], 4)

    def test_invalid_carrier_and_action_keep_billed_usage(self):
        def broken_carrier(request):
            result = respond(request)
            result["message"] = "MISMATCHED"
            result["metrics"] = {"total_tokens": 41, "model": "mock"}
            return result

        def broken_action(request):
            result = respond(request)
            result["action"] = {"type": "submit", "coefficients": {"a": 99}}
            result["metrics"] = {"total_tokens": 41, "model": "mock"}
            return result

        with tempfile.TemporaryDirectory() as tmp:
            for name, adapter in (("carrier", broken_carrier),
                                  ("action", broken_action)):
                with self.subTest(name=name):
                    out = Path(tmp) / name
                    summary = run_trial(out, adapter, seed=1337, arm_seed=3,
                                        count=1, state_bytes=48, max_total_tokens=40)
                    self.assertTrue(all(v["usage_complete"] and v["over_budget"] == 1
                                        and v["protocol_errors"] == 1
                                        for v in summary["by_arm"].values()))
                    result = analyze(out)
                    self.assertEqual(result["metered_error_calls"], 4)
                    self.assertEqual(result["unmetered_error_runs"], 0)

    def test_malformed_model_json_retains_metered_call_and_independent_replay(self):
        ChannelProviderStub.requests = []
        ChannelProviderStub.reported_tokens = 30
        ChannelProviderStub.drift_after = None
        ChannelProviderStub.bad_content_at = 1
        ChannelProviderStub.missing_usage_at = None
        server = ThreadingHTTPServer(("127.0.0.1", 0), ChannelProviderStub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = (f"http://127.0.0.1:{server.server_port}/", None,
                  {"model": "mock-constant", "max_completion_tokens": 128}, 5)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "malformed"
                result = run_trial(out, lambda req: call_channel_model(
                    req, resolved_config=config), seed=1337, arm_seed=3,
                    count=1, state_bytes=48, max_total_tokens=100)
                failed = [r for r in out.glob("*/*/trace.json")
                          if json.loads(r.read_text())["error"] is not None]
                self.assertEqual(len(failed), 1)
                record = json.loads(failed[0].read_text())
                self.assertEqual(record["total_tokens"], 30)
                self.assertTrue(record["within_budget"])
                self.assertEqual(record["trace"][0]["error_metrics"]["total_tokens"], 30)
                self.assertNotIn("INVALID_MODEL_JSON", failed[0].read_text())
                self.assertTrue(all(v["usage_complete"] for v in result["by_arm"].values()))
                replay = analyze(out)
                self.assertEqual(replay["metered_error_calls"], 1)
                self.assertEqual(replay["unmetered_error_runs"], 0)
        finally:
            ChannelProviderStub.bad_content_at = None
            ChannelProviderStub.missing_usage_at = None
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_malformed_json_without_usage_remains_unknown_cost(self):
        ChannelProviderStub.requests = []
        ChannelProviderStub.reported_tokens = 30
        ChannelProviderStub.drift_after = None
        ChannelProviderStub.bad_content_at = 1
        ChannelProviderStub.missing_usage_at = 1
        server = ThreadingHTTPServer(("127.0.0.1", 0), ChannelProviderStub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = (f"http://127.0.0.1:{server.server_port}/", None,
                  {"model": "mock-constant", "max_completion_tokens": 128}, 5)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "unmetered"
                run_trial(out, lambda req: call_channel_model(
                    req, resolved_config=config), seed=1337, arm_seed=3,
                    count=1, state_bytes=48, max_total_tokens=100)
                record = json.loads(next(p for p in out.glob("*/*/trace.json")
                                         if json.loads(p.read_text())["error"] is not None).read_text())
                self.assertIsNone(record["total_tokens"])
                self.assertIsNone(record["within_budget"])
                self.assertIsNone(record["trace"][0]["error_metrics"]["total_tokens"])
                replay = analyze(out)
                self.assertEqual(replay["metered_error_calls"], 0)
                self.assertEqual(replay["unmetered_error_runs"], 1)
        finally:
            ChannelProviderStub.bad_content_at = None
            ChannelProviderStub.missing_usage_at = None
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_mixed_metered_and_unknown_cost_replays_lower_bound(self):
        calls = [0]

        def intermittent(request):
            calls[0] += 1
            if calls[0] % 2 == 0:
                raise RuntimeError("Transport failed before response envelope")
            return {**respond(request), "metrics": {"total_tokens": 30,
                                                    "model": "mock"}}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "partial"
            summary = run_trial(out, intermittent, seed=1337, arm_seed=5,
                                count=1, state_bytes=48, max_total_tokens=100)
            self.assertEqual(calls[0], 8)
            self.assertTrue(all(v["provider_reported_token_lower_bound"] == 30
                                and v["provider_reported_total_tokens"] is None
                                and not v["usage_complete"]
                                for v in summary["by_arm"].values()))
            replay = analyze(out)
            self.assertEqual(replay["unmetered_error_runs"], 4)
            self.assertEqual(replay["metered_error_calls"], 0)
            path = next(out.glob("*/*/trace.json"))
            original = json.loads(path.read_text())
            self.assertEqual(original["reported_token_lower_bound"], 30)
            self.assertIsNone(original["total_tokens"])
            self.assertIsNone(original["within_budget"])
            altered = copy.deepcopy(original)
            altered["reported_token_lower_bound"] = 0
            path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError, "lower bound"):
                analyze(out)

    def test_unsupported_carried_claim_is_not_credited_as_success(self):
        carry = encode_facts({(3, 3): 1})

        def fabricating(request):
            result = respond(request)
            result["message"] = PREFIX + carry
            result["ledger"]["carry"] = carry
            result["metrics"] = {"total_tokens": 10, "model": "fake"}
            return result

        with tempfile.TemporaryDirectory() as tmp:
            result = run_trial(Path(tmp) / "fake", fabricating, seed=1337,
                               arm_seed=1, count=1, state_bytes=48,
                               max_total_tokens=100)
            self.assertTrue(all(v["hidden_successes"] == 0
                                and v["protocol_errors"] == 1
                                for v in result["by_arm"].values()))
            one = json.loads(next((Path(tmp) / "fake").glob("*/*/trace.json")).read_text())
            self.assertIn("lacks public observational support", one["error"])
            self.assertEqual(analyze(Path(tmp) / "fake")["runs_replayed"], 4)

    def test_independent_replay_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "trial"
            run_trial(root, lambda req: {**respond(req), "metrics": {
                "total_tokens": 10, "model": "mock"}}, seed=1337,
                arm_seed=0, count=1, state_bytes=48, max_total_tokens=100)
            self.assertEqual(analyze(root)["runs_replayed"], 4)
            path = next(root.glob("*/*/trace.json"))
            original = json.loads(path.read_text())
            modified = copy.deepcopy(original)
            modified["total_tokens"] = 1
            path.write_text(json.dumps(modified))
            with self.assertRaisesRegex(ValueError, "token-cap accounting"):
                analyze(root)
            path.write_text(json.dumps(original))
            modified = copy.deepcopy(original)
            modified["trace"][0]["request"]["human_signal"] = "invented feedback"
            path.write_text(json.dumps(modified))
            with self.assertRaisesRegex(ValueError, "replay|digest"):
                analyze(root)

    def test_cli_pins_and_checks_provider_model_identity(self):
        ChannelProviderStub.requests = []
        ChannelProviderStub.reported_tokens = 30
        ChannelProviderStub.drift_after = 1
        server = ThreadingHTTPServer(("127.0.0.1", 0), ChannelProviderStub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        settings = {"KLOOP_MODEL": "mock-constant", "KLOOP_API_URL":
                    f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                    "KLOOP_MAX_COMPLETION_TOKENS": "256", "KLOOP_JSON_MODE": "1"}
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, settings):
                out = Path(tmp) / "cli"
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
                    main(["--out", str(out), "--seed", "1337",
                          "--count", "1", "--state-bytes", "48",
                          "--max-total-tokens", "100"])
                self.assertEqual(stopped.exception.code, 2)
                self.assertIn("identity drifted", stderr.getvalue())
                abort = json.loads((out / "abort.json").read_text())
                self.assertEqual(abort["reason"], "provider_model_identity_drift")
                self.assertEqual(abort["runs_recorded"], 1)
                self.assertEqual(len(ChannelProviderStub.requests), 2)
                self.assertFalse((out / "summary.json").exists())
                affected = json.loads((out / abort["last_trace"]).read_text())
                self.assertEqual(affected["total_tokens"], 60)
                self.assertEqual(affected["trace"][-1]["error_metrics"]["total_tokens"], 30)
                self.assertEqual(abort["model_metadata"]["requested_model"],
                                 "mock-constant")
                self.assertNotIn("127.0.0.1:", abort["model_metadata"]["endpoint_origin"])
        finally:
            ChannelProviderStub.drift_after = None
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
