import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from analyze_channel_match import analyze
from discovery_channel_codec import (EMPTY_PAYLOAD, PREFIX, decode_facts,
                                     encode_facts, fit_facts)
from discovery_channel_control import respond
from discovery_channel_match import (MATCHED_SCHEMA, audit_matched_run, main,
                                     run_matched, validate_carriers)
from discovery_pilot import CONDITIONS, make_tasks


class MatchedChannelTests(unittest.TestCase):
    def test_canonical_codec_and_capacity(self):
        facts = {(1, 0): 7, (0, 0): 9, (0, 1): 6}
        encoded = encode_facts(facts)
        self.assertEqual(decode_facts(encoded, 100), facts)
        self.assertEqual(fit_facts(facts, len(encoded)), encoded)
        self.assertEqual(fit_facts(facts, 12), EMPTY_PAYLOAD)
        for malformed in ('{"facts":[[0,0,1],[0,0,2]]}',
                          '{"facts":[[0,0,true]]}',
                          '{"facts":[[0,0,11]]}',
                          '{"facts":[[0,0,1]], "extra":1}',
                          '{"facts":[[1,0,7],[0,0,9]]}'):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    decode_facts(malformed, 100)
        with self.assertRaises(ValueError):
            decode_facts(encoded, len(encoded) - 1)
        with self.assertRaises(ValueError):
            encode_facts({(0, 0): True})

    def test_equal_information_and_actions_in_both_carriers(self):
        for task in make_tasks(1337, 12)["tasks"]:
            for feedback in ("k", "rich"):
                i = run_matched(task, (feedback, "implicit"), respond, 48)
                e = run_matched(task, (feedback, "explicit"), respond, 48)
                with self.subTest(task=task["id"], feedback=feedback):
                    self.assertTrue(i["hidden_pass"] and e["hidden_pass"])
                    self.assertEqual(i["turns"], 3)
                    self.assertEqual(i["trace"][2]["response"],
                                     e["trace"][2]["response"])
                    self.assertEqual(audit_matched_run(i)["incoming_payloads"],
                                     audit_matched_run(e)["incoming_payloads"])
                    self.assertEqual([len(t["request"]["observations"])
                                      for t in e["trace"]], [2, 1, 1])
                    self.assertNotIn("_target", json.dumps(i))

    def test_capacity_regime_changes_outcomes_symmetrically(self):
        counts = {}
        for cap in (12, 20, 27, 35, 48):
            successes = {arm: 0 for arm in CONDITIONS}
            for task in make_tasks(1337, 12)["tasks"]:
                for arm in CONDITIONS:
                    run = run_matched(task, arm, respond, cap)
                    self.assertIsNone(run["error"])
                    successes[arm] += run["hidden_pass"]
                    audit_matched_run(run)
            self.assertEqual(len(set(successes.values())), 1)
            counts[cap] = next(iter(successes.values()))
        self.assertEqual(counts[12], 0)
        self.assertEqual(counts[48], 12)
        self.assertLess(counts[27], counts[48])

    def test_retryable_failure_preserves_payload_parity(self):
        task = make_tasks(1337, 1)["tasks"][0]
        for feedback in ("k", "rich"):
            runs = [run_matched(task, (feedback, state), respond, 48, 1)
                    for state in ("implicit", "explicit")]
            self.assertTrue(all(run["hidden_pass"] for run in runs))
            self.assertEqual([len(event["request"]["observations"])
                              for event in runs[0]["trace"]], [2, 0, 1, 1])
            self.assertEqual(audit_matched_run(runs[0])["incoming_payloads"],
                             audit_matched_run(runs[1])["incoming_payloads"])

    def test_mismatched_payload_and_unsupported_fact_rejected(self):
        task = make_tasks(1337, 1)["tasks"][0]
        run = run_matched(task, ("k", "explicit"), respond, 48)
        tampered = copy.deepcopy(run)
        tampered["trace"][0]["response"]["message"] = PREFIX + EMPTY_PAYLOAD
        with self.assertRaisesRegex(ValueError, "Mismatched"):
            audit_matched_run(tampered)
        tampered = copy.deepcopy(run)
        invented = encode_facts({(3, 3): 1})
        tampered["trace"][0]["response"]["message"] = PREFIX + invented
        tampered["trace"][0]["response"]["ledger"]["carry"] = invented
        with self.assertRaisesRegex(ValueError, "public observational support"):
            audit_matched_run(tampered)
        with self.assertRaises(ValueError):
            validate_carriers({"message": PREFIX + EMPTY_PAYLOAD,
                               "ledger": {"carry": EMPTY_PAYLOAD},
                               "action": {}, "backdoor": 7}, 48)

    def test_subprocess_cli_and_paired_auditor_detect_tampering(self):
        agent = Path(__file__).with_name("discovery_channel_control.py")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "matched"
            args = ["--agent", f"{sys.executable} {agent}",
                    "--out", str(out), "--seed", "1337", "--count", "2",
                    "--state-bytes", "48"]
            self.assertEqual(main(args), 0)
            report = analyze(Path(tmp))
            self.assertEqual(report["scenario_count"], 1)
            case = report["scenarios"]["matched"]
            self.assertEqual(case["matched_information_turn_pairs"], 12)
            self.assertTrue(all(x["successes"] == 2
                                for x in case["by_arm"].values()))
            target = next(out.glob("*/*/trace.json"))
            old = json.loads(target.read_text())
            old["trace"][1]["request"]["observations"] = []
            target.write_text(json.dumps(old))
            with self.assertRaisesRegex(ValueError, "digest"):
                analyze(Path(tmp))


if __name__ == "__main__":
    unittest.main()
