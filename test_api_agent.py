import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from api_agent import configuration
from pilot import CONDITIONS, make_tasks, run_one


class ModelStub(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.__class__.received.append(payload)
        task_request = json.loads(payload["messages"][1]["content"])
        candidate = task_request["candidate"]
        answer = {
            "candidate": candidate, "message": "Mock model: no edit",
            "ledger": {
                "objective": "Match the function", "established": [],
                "falsified": [], "unresolved": ["Candidate not repaired"],
                "next_action": "Try an edit", "verification": "Public data only",
            },
        }
        response = {
            "id": "stub-001", "model": payload["model"],
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 11, "total_tokens": 51},
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
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(len(ModelStub.received), 5)
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


if __name__ == "__main__":
    unittest.main()
