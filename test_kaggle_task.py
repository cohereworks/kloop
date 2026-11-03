import contextlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pilot
from build_kaggle_task import build


class EchoLLM:
    def __init__(self):
        self.requests = []

    def prompt(self, prompt):
        req = json.loads(prompt.split("REQUEST_JSON:\n", 1)[1])
        self.requests.append(req)
        return json.dumps({
            "candidate": req["candidate"],
            "message": "Mock: no edit",
            "ledger": {"objective": "Match outputs", "established": [],
                       "falsified": [], "unresolved": [],
                       "next_action": "Try another edit",
                       "verification": "Public examples only"},
        })


class FakeChats:
    def __init__(self):
        self.names = []

    def new(self, name):
        self.names.append(name)
        usage = types.SimpleNamespace(input_tokens=12, output_tokens=8,
                                      input_tokens_cost_nanodollars=120,
                                      output_tokens_cost_nanodollars=80,
                                      total_backend_latency_ms=25)
        return contextlib.nullcontext(types.SimpleNamespace(usage=usage))


class KaggleBuilderTests(unittest.TestCase):
    def test_generated_script_is_self_contained_and_parity_checked(self):
        source = build()
        self.assertIn('@kbench.task(name="kloop-pilot")', source)
        self.assertNotIn("from pilot import", source)
        compile(source, "generated_kaggle.py", "exec")

        mock = types.ModuleType("kaggle_benchmarks")
        mock.task = lambda **kwargs: lambda fn: fn
        mock.chats = FakeChats()
        agent = EchoLLM()
        mock.llm = agent
        namespace = {"__name__": "kloop_benchmark_test"}
        with patch.dict(sys.modules, {"kaggle_benchmarks": mock}):
            exec(compile(source, "generated_kaggle.py", "exec"), namespace)

        self.assertEqual(namespace["make_tasks"](42, 2), pilot.make_tasks(42, 2))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"KLOOP_OUTPUT_DIR": tmp}):
            score = namespace["kloop_benchmark"](agent, seed=42, count=1, max_turns=2)
            summary = json.loads((Path(tmp) / "kloop-kaggle-results.json").read_text())
        self.assertEqual(score, 0.0)
        self.assertEqual(set(summary["conditions"]), {f"{a}_{b}" for a, b in pilot.CONDITIONS})
        self.assertEqual(len(agent.requests), 8)
        self.assertEqual(len(mock.chats.names), 8)
        self.assertEqual(len(set(mock.chats.names)), 8)
        self.assertTrue(all(run["total_tokens"] == 40 for run in summary["runs"]))
        self.assertTrue(all(len(run["trace"]) == 2 for run in summary["runs"]))
        self.assertTrue(all(item["total_tokens"] == 40
                            for item in summary["conditions"].values()))
        for request in agent.requests:
            wire = json.dumps(request)
            self.assertNotIn("_hidden", wire)
            self.assertNotIn("_target", wire)


if __name__ == "__main__":
    unittest.main()
