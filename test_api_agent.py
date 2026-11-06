import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from api_agent import (ModelResponseError, call_model, configuration,
                       provider_usage, request_body)
from pilot import CONDITIONS, make_tasks, request_for, run_one


class ModelStub(BaseHTTPRequestHandler):
    received = []
    bodies = []
    usage = {"prompt_tokens": 40, "completion_tokens": 11, "total_tokens": 51}
    reported_model = None
    content_override = None

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body_bytes = self.rfile.read(length)
        self.__class__.bodies.append(body_bytes)
        payload = json.loads(body_bytes)
        self.__class__.received.append(payload)
        task_request = json.loads(payload["messages"][1]["content"])
        candidate = task_request["candidate"]
        answer = {
            "candidate": candidate, "message": "Mock model: no edit",
            "metrics": {"total_tokens": -1000, "model": "model-content-forgery"},
            "ledger": {
                "objective": "Match the function", "established": [],
                "falsified": [], "unresolved": ["Candidate not repaired"],
                "next_action": "Try an edit", "verification": "Public data only",
            },
        }
        response = {
            "id": "stub-001", "model": (self.__class__.reported_model
                                         if self.__class__.reported_model is not None
                                         else payload["model"]),
            "choices": [{"finish_reason": "stop", "message": {
                "content": (json.dumps(answer) if self.__class__.content_override is None
                            else self.__class__.content_override)}}],
            "usage": self.__class__.usage,
        }
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ApiAgentTests(unittest.TestCase):
    def test_model_required(self):
        with patch.dict(os.environ, {"KLOOP_MODEL": ""}):
            with self.assertRaisesRegex(ValueError, "KLOOP_MODEL"):
                configuration()

    def test_url_restriction(self):
        with patch.dict(os.environ, {"KLOOP_MODEL": "test", "KLOOP_API_URL": "http://example.org/v1/chat/completions"}):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                configuration()

    def test_http_adapter_full_protocol(self):
        ModelStub.received = []
        ModelStub.bodies = []
        ModelStub.usage = {"prompt_tokens": 40, "completion_tokens": 11,
                           "total_tokens": 51}
        ModelStub.reported_model = None
        ModelStub.content_override = None
        server = ThreadingHTTPServer(("127.0.0.1", 0), ModelStub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        task = make_tasks(123, 1)["tasks"][0]
        adapter = str(Path(__file__).with_name("api_agent.py").resolve())
        settings = {
            "KLOOP_MODEL": "stub-model", "KLOOP_API_KEY": "not-a-real-key",
            "KLOOP_API_URL": f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            "KLOOP_JSON_MODE": "1", "KLOOP_MAX_COMPLETION_TOKENS": "123",
        }
        try:
            with patch.dict(os.environ, settings), tempfile.TemporaryDirectory() as tmp:
                runs = [run_one(task, c, [sys.executable, adapter],
                                Path(tmp) / f"{c[0]}_{c[1]}", 1, 8, 100)
                        for c in CONDITIONS]
                over_budget = run_one(task, CONDITIONS[0], [sys.executable, adapter],
                                      Path(tmp) / "over_budget", 1, 8, 40)
                frozen = configuration()
                req = request_for(task, CONDITIONS[0], 1, task["starter"], None, [])
                with patch("api_agent.configuration", side_effect=AssertionError("unexpected reread")):
                    direct = call_model(req, resolved_config=frozen,
                                        instructions="DISCOVERY_TEST_INSTRUCTIONS")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(len(ModelStub.received), 6)
        self.assertEqual(direct["metrics"]["model"], "stub-model")
        self.assertEqual(direct["metrics"]["total_tokens"], 51)
        self.assertEqual(ModelStub.received[-1]["messages"][0]["content"],
                         "DISCOVERY_TEST_INSTRUCTIONS")
        self.assertEqual(ModelStub.bodies[-1], request_body(
            req, frozen[2], "DISCOVERY_TEST_INSTRUCTIONS"))
        self.assertEqual(direct["metrics"]["usage_provenance"],
                         "provider_response_envelope_unverified")
        self.assertTrue(all(r["error"] is None for r in runs))
        self.assertTrue(all(r["total_tokens"] == 51 for r in runs))
        self.assertTrue(all(r["trace"][0]["response"]["metrics"]["model"] == "stub-model"
                            for r in runs))
        self.assertFalse(over_budget["within_budget"])
        self.assertTrue(over_budget["budget_exhausted"])
        self.assertFalse(over_budget["hidden_pass"])
        for payload in ModelStub.received:
            wire = json.dumps(payload)
            self.assertNotIn("_hidden", wire)
            self.assertNotIn("_target", wire)
            self.assertEqual(payload["max_completion_tokens"], 123)

    def test_serialization_keeps_unicode_without_falsely_claiming_token_parity(self):
        request = {"message": "π", "nested": {"z": 1, "a": 2}}
        body = request_body(request, {"model": "example", "max_completion_tokens": 7},
                            "a constant instruction")
        self.assertEqual(json.loads(body)["messages"][1]["content"],
                         json.dumps(request, sort_keys=True, ensure_ascii=False))
        self.assertIn(b"\\u03c0", body)  # Outer serializer escapes the inner Unicode.

    def test_provider_usage_rejects_partial_forged_or_inconsistent_counts(self):
        self.assertEqual(provider_usage({})["total_tokens"], None)
        self.assertEqual(provider_usage({"usage": {"prompt_tokens": 2,
                       "completion_tokens": 3, "total_tokens": 5}})["total_tokens"], 5)
        for value in ({"prompt_tokens": 2, "total_tokens": 2},
                      {"prompt_tokens": True, "completion_tokens": 2,
                       "total_tokens": 3},
                      {"prompt_tokens": -1, "completion_tokens": 4,
                       "total_tokens": 3},
                      {"prompt_tokens": 2, "completion_tokens": 2,
                       "total_tokens": 5}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider_usage({"usage": value})

    def test_model_identity_and_usage_are_provider_observations_not_request_echoes(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), ModelStub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = (f"http://127.0.0.1:{server.server_port}/", None,
                  {"model": "requested", "max_completion_tokens": 5}, 5)
        try:
            ModelStub.reported_model = ""  # Missing identity must not silently use requested.
            with self.assertRaisesRegex(ValueError, "identity missing"):
                call_model({"candidate": {"var": "x"}}, resolved_config=config)
            ModelStub.reported_model = "observed-other-model"
            ModelStub.usage = {"prompt_tokens": 9, "completion_tokens": 2,
                               "total_tokens": 100}
            with self.assertRaisesRegex(ValueError, "disagrees"):
                call_model({"candidate": {"var": "x"}}, resolved_config=config)
            ModelStub.usage = {"prompt_tokens": 9, "completion_tokens": 2,
                               "total_tokens": 11}
            result = call_model({"candidate": {"var": "x"}}, resolved_config=config)
            self.assertEqual(result["metrics"]["model"], "observed-other-model")
        finally:
            ModelStub.reported_model = None
            ModelStub.content_override = None
            ModelStub.usage = {"prompt_tokens": 40, "completion_tokens": 11,
                               "total_tokens": 51}
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_bad_model_json_preserves_provider_usage_without_exposing_content(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), ModelStub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = (f"http://127.0.0.1:{server.server_port}/", None,
                  {"model": "requested", "max_completion_tokens": 5}, 5)
        try:
            ModelStub.reported_model = None
            ModelStub.content_override = "PRIVATE_INVALID_CONTENT {"
            ModelStub.usage = {"prompt_tokens": 20, "completion_tokens": 9,
                               "total_tokens": 29}
            with self.assertRaises(ModelResponseError) as raised:
                call_model({"candidate": {"var": "x"}}, resolved_config=config)
            self.assertEqual(raised.exception.metrics["total_tokens"], 29)
            self.assertEqual(raised.exception.metrics["model"], "requested")
            self.assertNotIn("PRIVATE_INVALID_CONTENT", str(raised.exception))
            ModelStub.content_override = '[]'
            with self.assertRaisesRegex(ModelResponseError, "JSON object") as other:
                call_model({"candidate": {"var": "x"}}, resolved_config=config)
            self.assertEqual(other.exception.metrics["total_tokens"], 29)
            ModelStub.usage = None
            with self.assertRaises(ModelResponseError) as unknown:
                call_model({"candidate": {"var": "x"}}, resolved_config=config)
            self.assertIsNone(unknown.exception.metrics["total_tokens"])
        finally:
            ModelStub.content_override = None
            ModelStub.usage = {"prompt_tokens": 40, "completion_tokens": 11,
                               "total_tokens": 51}
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
