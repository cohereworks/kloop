#!/usr/bin/env python3
"""Replay the matched-channel traces through the exact HTTP JSON serializer.

This is offline serialization accounting, NOT provider token measurement. It
reuses the channel auditor to reject altered/incomplete traces first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from analyze_channel_match import analyze
from api_agent import request_body
from discovery_api_agent import INSTRUCTIONS
from pilot import canonical, write_json


SCHEMA = "kloop-channel-transport-accounting-v1"
# A visible reference framing, not a selected or observed live model.
REFERENCE_PARAMS = {"model": "MODEL_NOT_SELECTED", "max_completion_tokens": 1600,
                    "response_format": {"type": "json_object"}}


def sizes(request, params=REFERENCE_PARAMS, instructions=INSTRUCTIONS):
    canonical_bytes = len(canonical(request).encode("utf-8"))
    inner_bytes = len(json.dumps(request, sort_keys=True,
                                 ensure_ascii=False).encode("utf-8"))
    body_bytes = len(request_body(request, params, instructions))
    return canonical_bytes, inner_bytes, body_bytes


def deltas_for_pair(implicit, explicit):
    if (implicit["task"] != explicit["task"] or
            implicit["condition"].split("_")[0] != explicit["condition"].split("_")[0] or
            not implicit["condition"].endswith("_implicit") or
            not explicit["condition"].endswith("_explicit") or
            len(implicit["trace"]) != len(explicit["trace"])):
        raise ValueError("Unpaired state-channel traces")
    differences = []
    for i_event, e_event in zip(implicit["trace"], explicit["trace"]):
        if (i_event["response"] != e_event["response"] or
                i_event["environment_feedback"] != e_event["environment_feedback"]):
            raise ValueError("Unequal channel outputs")
        i_sizes, e_sizes = sizes(i_event["request"]), sizes(e_event["request"])
        differences.append(tuple(e - i for i, e in zip(i_sizes, e_sizes)))
    return differences


def summary_of(differences):
    if not differences:
        raise ValueError("No matched turns to account for")
    fields = ("canonical_request_utf8", "adapter_user_content_utf8",
              "serialized_http_body_utf8")
    return {"matched_turn_pairs": len(differences),
            "explicit_minus_implicit": {
                field: {"sum": sum(values), "mean": sum(values) / len(values),
                        "min": min(values), "max": max(values)}
                for field, values in zip(fields, zip(*differences))}}


def absolute_sizes(readings):
    if not readings:
        raise ValueError("No requests to account for")
    fields = ("canonical_request_utf8", "adapter_user_content_utf8",
              "serialized_http_body_utf8")
    return {"request_count": len(readings),
            "bytes": {field: {"sum": sum(values),
                              "mean": sum(values) / len(values),
                              "min": min(values), "max": max(values)}
                      for field, values in zip(fields, zip(*readings))}}


def audit_directory(root):
    # Independent, strict prerequisite: verify run-set digests, replay the
    # evidence, validate the original outgoing/incoming matched carriers.
    verified = analyze(root)
    scenarios, global_deltas = {}, []
    for folder in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        task_ids = sorted({p.parent.parent.name
                           for p in folder.glob("*/k_implicit/trace.json")})
        by_feedback, scenario_deltas = {}, []
        for feedback in ("k", "rich"):
            differences, implicit_sizes, explicit_sizes = [], [], []
            for task in task_ids:
                implicit = json.loads((folder / task / f"{feedback}_implicit" /
                                       "trace.json").read_text())
                explicit = json.loads((folder / task / f"{feedback}_explicit" /
                                       "trace.json").read_text())
                differences.extend(deltas_for_pair(implicit, explicit))
                implicit_sizes.extend(sizes(t["request"]) for t in implicit["trace"])
                explicit_sizes.extend(sizes(t["request"]) for t in explicit["trace"])
            by_feedback[feedback] = {**summary_of(differences),
                                     "by_state": {
                                         "implicit": absolute_sizes(implicit_sizes),
                                         "explicit": absolute_sizes(explicit_sizes)}}
            scenario_deltas.extend(differences)
        original_pairs = verified["scenarios"][folder.name]["matched_information_turn_pairs"]
        if original_pairs != len(scenario_deltas):
            raise ValueError("Transport coverage differs from the evidence audit")
        scenarios[folder.name] = {"by_feedback": by_feedback,
                                  "combined": summary_of(scenario_deltas)}
        global_deltas.extend(scenario_deltas)
    return {"schema": SCHEMA,
            "reference_framing": {"params": REFERENCE_PARAMS,
                                  "developer_instructions_sha256": hashlib.sha256(
                                      INSTRUCTIONS.encode("utf-8")).hexdigest(),
                                  "request_serializer": "api_agent.request_body",
                                  "http_headers_included": False,
                                  "real_model_requests": 0,
                                  "provider_tokens_measured": None},
            "scenario_count": len(scenarios), "scenarios": scenarios,
            "combined": summary_of(global_deltas),
            "limitations": ("Reference serialized HTTP body bytes are not API "
                            "token counts, inference cost or actual HTTP traffic. "
                            "The fixed reference model label and instruction text "
                            "are illustrative. Channel-specific delta values "
                            "depend on the frozen serializer and request schema; "
                            "there was no hosted-model trial.")}


def audit_archive(path):
    """Safely unpack a small, self-contained public calibration archive."""
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as tmp:
        members = archive.infolist()
        if (not members or len(members) > 5000 or
                sum(m.file_size for m in members) > 50_000_000):
            raise ValueError("Unexpected archive size")
        for member in members:
            p = PurePosixPath(member.filename)
            if (p.is_absolute() or ".." in p.parts or "\\" in member.filename or
                    member.is_dir() is False and p.suffix != ".json" or
                    (member.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsafe or unexpected archive entry")
        archive.extractall(tmp)
        result = audit_directory(Path(tmp))
    result["source_archive_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Matched-channel archive ZIP or scenario directory")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("Output file already exists")
    result = (audit_archive(args.source) if args.source.is_file()
              else audit_directory(args.source))
    write_json(args.out, result)
    print(f"Audited {result['combined']['matched_turn_pairs']} matched turns; "
          "zero model requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
