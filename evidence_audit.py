#!/usr/bin/env python3
"""Independent linear-evidence and conservative ledger-fidelity certificates.

Discovery only. The evaluator scores claims against observations supplied at
the time of the response; it never reads the hidden target or model rationale.
Natural-language claims are reported as uncertifiable, not presumed false.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from analyze_recovery import audit_run
from analyze_trial import ARMS, load_runs, pair_runs
from discovery_pilot import MODULUS, SCHEMA
from pilot import canonical


COORDINATE = re.compile(r"^(-?\d+),(-?\d+)(?:=(-?\d+))?$")


def matrix_rank(rows, modulus=MODULUS):
    """Reduced row-echelon rank and pivot columns over the prime field GF(11)."""
    if not rows:
        return 0, []
    ncols = len(rows[0])
    if any(len(row) != ncols or any(type(value) is not int for value in row)
           for row in rows):
        raise ValueError("Invalid finite-field matrix")
    m = [[v % modulus for v in row] for row in rows]
    pivots = []
    for col in range(ncols):
        index = next((i for i in range(len(pivots), len(m))
                      if m[i][col]), None)
        if index is None:
            continue
        cursor = len(pivots)
        m[cursor], m[index] = m[index], m[cursor]
        inverse = pow(m[cursor][col], -1, modulus)
        m[cursor] = [(v * inverse) % modulus for v in m[cursor]]
        for row in range(len(m)):
            if row != cursor and m[row][col]:
                coefficient = m[row][col]
                m[row] = [(a - coefficient * b) % modulus
                          for a, b in zip(m[row], m[cursor])]
        pivots.append(col)
        if len(pivots) == len(m):
            break
    return len(pivots), pivots


def evidence_certificate(observations):
    """Rank and cardinality of the solution space implied by visible evidence."""
    if not isinstance(observations, list):
        raise ValueError("Expected observation list")
    rows = []
    for observation in observations:
        if (not isinstance(observation, dict) or
                any(type(observation.get(field)) is not int
                    for field in ("x", "y", "value")) or
                not 0 <= observation["value"] < MODULUS):
            raise ValueError("Invalid observation")
        x, y = observation["x"], observation["y"]
        rows.append([x % MODULUS, y % MODULUS, (x * y) % MODULUS,
                     1, observation["value"]])
    rank, pivots = matrix_rank([row[:4] for row in rows])
    augmented_rank, _ = matrix_rank(rows)
    consistent = augmented_rank == rank
    return {"observations": len(rows), "coefficient_rank": rank,
            "basis_pivot_columns": pivots,
            "augmented_rank": augmented_rank,
            "consistent": consistent,
            "degrees_of_freedom": 4 - rank if consistent else None,
            "compatible_hypotheses": MODULUS ** (4 - rank) if consistent else 0,
            "visible_row_matrix_sha256": hashlib.sha256(canonical(rows).encode()).hexdigest()}


def parse_established_claim(claim):
    """Recognize coordinate or coordinate/value references; no NLP inference."""
    if isinstance(claim, str):
        match = COORDINATE.fullmatch(claim.strip())
        if match:
            x, y, value = match.groups()
            return (int(x), int(y)), (int(value) if value is not None else None)
    elif (isinstance(claim, dict) and set(claim) in
          ({"x", "y"}, {"x", "y", "value"}) and
          all(type(value) is int for value in claim.values())):
        return (claim["x"], claim["y"]), claim.get("value")
    return None


def ledger_certificate(ledger, observations, action):
    """Certify only established coordinate references and chosen next action."""
    known = {(row["x"], row["y"]): row["value"] for row in observations}
    claims = ledger.get("established") if isinstance(ledger, dict) else None
    if not isinstance(claims, list):
        return {"shape_valid": False, "claim_count": None,
                "verified_references": 0, "verified_values": 0,
                "duplicate_references": 0,
                "unsupported_references": 0, "contradicted_values": 0,
                "uncertifiable_claims": None, "observation_reference_coverage": 0.0,
                "claim_certification_rate": None,
                "next_action_alignment": (ledger.get("next_action") == action.get("type")
                                          if isinstance(ledger, dict) else False)}
    covered = set()
    verified, values, unsupported, contradicted, uncertifiable, duplicates = 0, 0, 0, 0, 0, 0
    for claim in claims:
        parsed = parse_established_claim(claim)
        if parsed is None:
            uncertifiable += 1
            continue
        point, value = parsed
        if point not in known:
            unsupported += 1
        elif value is not None and value != known[point]:
            contradicted += 1
        else:
            if point in covered:
                duplicates += 1
            else:
                verified += 1
                covered.add(point)
            if value is not None:
                values += 1
    return {"shape_valid": True, "claim_count": len(claims),
            "verified_references": verified, "verified_values": values,
            "duplicate_references": duplicates,
            "unsupported_references": unsupported,
            "contradicted_values": contradicted,
            "uncertifiable_claims": uncertifiable,
            "observation_reference_coverage": (len(covered) / len(known)
                                               if known else None),
            "claim_certification_rate": (verified / len(claims) if claims else None),
            "next_action_alignment": ledger.get("next_action") == action.get("type")}


def certify_run(run):
    """Return reproducible per-turn proof obligations and descriptive metrics."""
    audit_run(run)  # Reject malformed transitions and non-discovery strata.
    arm = run["condition"]
    explicit = arm.endswith("_explicit")
    turns = []
    relevant, redundant, successful = 0, 0, 0
    unsupported_submissions, inconsistent_turns = 0, 0
    for index, event in enumerate(run["trace"]):
        request = event["request"]
        before = evidence_certificate(request["observations"])
        response = event.get("response")
        if response is None:
            inconsistent_turns += int(not before["consistent"])
            turns.append({"turn": index + 1, "before": before,
                          "action_type": "protocol_error", "after": before,
                          "rank_gain": None, "ledger": None})
            continue
        action = response["action"]
        feedback = event["environment_feedback"]
        after = (evidence_certificate(request["observations"] +
                                      [feedback["observation"]])
                 if "observation" in feedback else before)
        inconsistent_turns += int(not before["consistent"] or not after["consistent"])
        gain = after["coefficient_rank"] - before["coefficient_rank"]
        if gain not in (0, 1):
            raise ValueError("A probe cannot increase linear rank by more than one")
        if action["type"] == "probe" and "observation" in feedback:
            successful += 1
            relevant += int(gain == 1)
            redundant += int(gain == 0)
        if action["type"] == "submit" and before["coefficient_rank"] < 4:
            unsupported_submissions += 1
        turns.append({"turn": index + 1, "before": before, "after": after,
                      "action_type": action["type"],
                      "rank_gain": (gain if action["type"] == "probe" else None),
                      "faulted_probe": "tool_error" in feedback,
                      "ledger": (ledger_certificate(response.get("ledger"),
                                                    request["observations"], action)
                                 if explicit else None)})
    return {"task": run["task"], "condition": arm,
            "hidden_pass": run["hidden_pass"],
            "successful_probes": successful, "relevant_probes": relevant,
            "redundant_probes": redundant,
            "probe_relevance_rate": relevant / successful if successful else None,
            "underidentified_submissions": unsupported_submissions,
            "inconsistent_evidence_turns": inconsistent_turns,
            "turn_certificates": turns}


def analyze(runs):
    paired = pair_runs(runs)
    certificates = [certify_run(group[arm])
                    for _, group in paired for arm in ARMS]
    by_arm = {}
    for arm in ARMS:
        selected = [cert for cert in certificates if cert["condition"] == arm]
        success = sum(cert["successful_probes"] for cert in selected)
        relevant = sum(cert["relevant_probes"] for cert in selected)
        ledger_turns = [turn["ledger"] for cert in selected
                        for turn in cert["turn_certificates"]
                        if turn["ledger"] is not None]
        by_arm[arm] = {
            "n": len(selected), "successful_probes": success,
            "relevant_probes": relevant,
            "redundant_probes": sum(cert["redundant_probes"] for cert in selected),
            "probe_relevance_rate": relevant / success if success else None,
            "underidentified_submissions": sum(cert["underidentified_submissions"]
                                                for cert in selected),
            "inconsistent_evidence_turns": sum(cert["inconsistent_evidence_turns"]
                                               for cert in selected),
            "ledger_fidelity": ({
                "scored_turns": len(ledger_turns),
                "invalid_established_shapes": sum(not c["shape_valid"]
                                                  for c in ledger_turns),
                "verified_references": sum(c["verified_references"]
                                           for c in ledger_turns),
                "verified_values": sum(c["verified_values"] for c in ledger_turns),
                "duplicate_references": sum(c["duplicate_references"]
                                            for c in ledger_turns),
                "unsupported_references": sum(c["unsupported_references"]
                                              for c in ledger_turns),
                "contradicted_values": sum(c["contradicted_values"]
                                           for c in ledger_turns),
                "uncertifiable_claims": sum(c["uncertifiable_claims"] or 0
                                            for c in ledger_turns),
                "mean_observation_reference_coverage":
                    sum(c["observation_reference_coverage"] or 0
                        for c in ledger_turns) / len(ledger_turns),
                "next_action_alignment_rate": sum(c["next_action_alignment"]
                                                  for c in ledger_turns) / len(ledger_turns),
            } if ledger_turns else None),
        }
    return {"schema": "kloop-discovery-evidence-audit-v1",
            "stratum": SCHEMA, "n_paired_tasks": len(paired),
            "by_arm": by_arm, "certificates": certificates,
            "limitations": ("Linear rank proves distinguishability only inside the fixed "
                            "public hypothesis class GF(11). Ledger checks certify only "
                            "recognized coordinate/value references and action labels, "
                            "not free-form reasoning, unresolved/falsified assertions, "
                            "causal state utility, or observational truth. Null ledger "
                            "scores in implicit arms mean not applicable, not failure.")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--expected-tasks", type=int)
    parser.add_argument("--aggregate-only", action="store_true",
                        help="Omit large per-turn certificates from the JSON summary")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        runs, digest = load_runs(args.input)
        report = analyze(runs)
        if args.expected_tasks is not None and report["n_paired_tasks"] != args.expected_tasks:
            raise ValueError("Unexpected paired task count")
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    report["evidence_sha256"] = digest
    if args.aggregate_only:
        del report["certificates"]
        report["certificate_detail"] = "omitted; rerun without --aggregate-only"
    output = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
