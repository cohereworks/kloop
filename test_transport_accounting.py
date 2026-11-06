import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from discovery_channel_control import respond
from discovery_channel_match import main as make_calibration, run_matched
from discovery_pilot import make_tasks
from transport_accounting import (SCHEMA, audit_archive, audit_directory,
                                  deltas_for_pair, sizes)


class TransportAccountingTests(unittest.TestCase):
    def test_body_framing_differs_from_canonical_request_size(self):
        task = make_tasks(1337, 1)["tasks"][0]
        i = run_matched(task, ("k", "implicit"), respond, 48)
        e = run_matched(task, ("k", "explicit"), respond, 48)
        deltas = deltas_for_pair(i, e)
        self.assertEqual(len(deltas), 3)
        # In this schema the serialization overhead is constant across arms,
        # so it cancels exactly; the absolute payload is still much larger.
        self.assertEqual(deltas[1][0], deltas[1][2])
        self.assertLess(sizes(i["trace"][0]["request"])[0],
                        sizes(i["trace"][0]["request"])[2])

    def test_forged_or_unmatched_response_is_rejected(self):
        task = make_tasks(1337, 1)["tasks"][0]
        i = run_matched(task, ("k", "implicit"), respond, 48)
        e = run_matched(task, ("k", "explicit"), respond, 48)
        broken = copy.deepcopy(e)
        broken["trace"][0]["response"]["message"] = "forged"
        with self.assertRaisesRegex(ValueError, "Unequal channel outputs"):
            deltas_for_pair(i, broken)
        with self.assertRaisesRegex(ValueError, "Unpaired"):
            deltas_for_pair(i, i)

    def test_replay_verifies_source_digest_before_reporting_cost(self):
        agent = Path(__file__).with_name("discovery_channel_control.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            target = root / "scenario"
            self.assertEqual(make_calibration(["--agent", f"{sys.executable} {agent}",
                                               "--out", str(target), "--count", "2",
                                               "--state-bytes", "48"]), 0)
            report = audit_directory(root)
            self.assertEqual(report["schema"], SCHEMA)
            self.assertEqual(report["scenario_count"], 1)
            self.assertEqual(report["combined"]["matched_turn_pairs"], 12)
            self.assertGreater(report["scenarios"]["scenario"]["by_feedback"]["k"]
                               ["by_state"]["implicit"]["bytes"]
                               ["serialized_http_body_utf8"]["mean"], 1000)
            self.assertIsNone(report["reference_framing"]["provider_tokens_measured"])
            self.assertEqual(report["reference_framing"]["real_model_requests"], 0)
            trace_path = next(target.glob("*/k_implicit/trace.json"))
            record = json.loads(trace_path.read_text())
            record["trace"][0]["request"]["human_signal"] = "fabricated"
            trace_path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "digest"):
                audit_directory(root)

    def test_zip_replay_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attack.zip"
            with zipfile.ZipFile(path, "w") as out:
                out.writestr("../escaped.json", "{}")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                audit_archive(path)

    def test_committed_archive_reference_accounting(self):
        archive = Path(__file__).with_name("reports") / "discovery-channel-matched-calibration-traces.zip"
        report = audit_archive(archive)
        self.assertEqual(report["source_archive_sha256"],
                         "0d650dc75d2be21d3faf5f8e061f9f7a5fdbc9f8d0cba892ed8aea3fd6810fc7")
        self.assertEqual(report["scenario_count"], 6)
        self.assertEqual(report["combined"]["matched_turn_pairs"], 456)


if __name__ == "__main__":
    unittest.main()
