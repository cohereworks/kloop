import contextlib
import builtins
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
        self.assertNotIn("from api_agent import", source)
        self.assertNotIn("ModelResponseError", source)
        self.assertNotIn("def run_one(", source)
        self.assertTrue(source.startswith("# %%\n"))
        self.assertEqual(source.count("# %%"), 2)
        compile(source, "generated_kaggle.py", "exec")

        mock = types.ModuleType("kaggle_benchmarks")
        mock.task = lambda **kwargs: lambda fn: fn
        mock.chats = FakeChats()
        agent = EchoLLM()
        mock.llm = agent
        namespace = {"__name__": "kloop_benchmark_test"}
        local_modules = {p.stem for p in Path(__file__).parent.glob("*.py")}
        original_import = builtins.__import__

        def deny_repo_imports(name, *args, **kwargs):
            if name.split(".")[0] in local_modules:
                raise ModuleNotFoundError(f"Standalone task imported repository module: {name}")
            return original_import(name, *args, **kwargs)

        with (patch.dict(sys.modules, {"kaggle_benchmarks": mock}),
              patch("builtins.__import__", side_effect=deny_repo_imports)):
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

    def test_builder_fails_on_new_unbundled_local_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "custom.py").write_text(
                "from project_helper import something\nvalue = something\n",
                encoding="utf-8")
            (directory / "project_helper.py").write_text(
                "something = 42\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "retains local imports"):
                build(directory / "custom.py", Path(__file__).with_name("kaggle_task_template.py"))

    def test_builder_rejects_unreviewed_api_adapter_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Path(tmp) / "core.py"
            core.write_text("from api_agent import configuration\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unexpected api_agent import"):
                build(core, Path(__file__).with_name("kaggle_task_template.py"))


if __name__ == "__main__":
    unittest.main()
