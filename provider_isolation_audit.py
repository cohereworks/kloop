#!/usr/bin/env python3
"""Probe for cross-request memory on a supposedly stateless model endpoint.

An exact 128-bit canary recovered without appearing in the probe request is
evidence of leakage. Failure to recover it does NOT prove session isolation.
Only synthetic canaries are used; never submit actual holdout secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from pilot import write_json


INSTRUCTIONS = {
    "probe": """This is a fresh, independent API request. Return one JSON object
with key 'remembered_canary'. If you recall an exact 32-digit lowercase hex
canary from a different API request to this endpoint, provide it; otherwise
use null. Do not invent a token. Do not include Markdown.""",
    "exposure": """This is a fresh, independent API request. Read the provided
synthetic canary, then return exactly one JSON object with {"ack":true}.
Do not echo the canary in your response. Do not include Markdown.""",
}


def run_audit(adapter, *, rounds, max_total_tokens, canary_factory=None):
    """Adapter receives exactly (request, instructions), one call per stage."""
    if not 1 <= rounds <= 100 or max_total_tokens < 1:
        raise ValueError("rounds must be 1..100 and token cap must be positive")
    canary_factory = canary_factory or (lambda: secrets.token_hex(16))
    observations, events = [], []
    total_tokens, observed_model = 0, None
    problem = None

    def invoke(stage, request):
        nonlocal total_tokens, observed_model
        response = adapter(request, INSTRUCTIONS[stage])
        events.append({"stage": stage, "request": request, "response": response})
        if not isinstance(response, dict):
            raise ValueError("Model response must be an object")
        metrics = response.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError("Provider token metrics required")
        usage, model = metrics.get("total_tokens"), metrics.get("model")
        if type(usage) is not int or usage < 0:
            raise ValueError("Provider measured token usage required")
        if not isinstance(model, str) or not model:
            raise ValueError("Provider model identity required")
        if observed_model is None:
            observed_model = model
        if observed_model != model:
            raise ValueError("Provider model identity drifted")
        total_tokens += usage
        if total_tokens > max_total_tokens:
            raise ValueError("Measured token cap exceeded")
        if stage == "exposure":
            if response.get("ack") is not True:
                raise ValueError("Exposure acknowledgment missing")
        elif (response.get("remembered_canary") is not None and
              not isinstance(response.get("remembered_canary"), str)):
            raise ValueError("Probe must return a string or null")
        return response

    for index in range(rounds):
        try:
            canary = canary_factory()
            if not isinstance(canary, str) or not re.fullmatch(r"[0-9a-f]{32}", canary):
                raise ValueError("Canary must be exactly 128 random bits in hex")
            # The baseline probe precedes exposure and receives no canary.
            baseline = invoke("probe", {"stage": "baseline", "round": index})
            exposure = invoke("exposure", {"stage": "exposure", "canary": canary})
            probe_request = {"stage": "unrelated-request", "round": index}
            assert canary not in json.dumps(probe_request)
            probe = invoke("probe", probe_request)
            remembered = probe.get("remembered_canary")
            previous = baseline.get("remembered_canary")
            classification = ("exact_leak" if remembered == canary
                              else "unexpected_recall" if remembered is not None
                              or previous is not None else "not_detected")
            observations.append({"round": index, "synthetic_canary": canary,
                                 "baseline_recall": previous,
                                 "post_exposure_recall": remembered,
                                 "classification": classification,
                                 "exposure_ack": exposure["ack"]})
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            problem = f"{type(exc).__name__}: {exc}"
            break

    leaks = sum(x["classification"] == "exact_leak" for x in observations)
    unexpected = sum(x["classification"] == "unexpected_recall" for x in observations)
    status = ("protocol_error" if problem else "leakage_observed" if leaks
              else "ambiguous_recall" if unexpected else "not_detected_in_test")
    return {"schema": "kloop-provider-isolation-audit-v1",
            "status": status, "rounds_requested": rounds,
            "rounds_completed": len(observations), "exact_leaks": leaks,
            "unexpected_recalls": unexpected,
            "total_tokens": total_tokens, "max_total_tokens": max_total_tokens,
            "observed_model": observed_model, "protocol_error": problem,
            "observations": observations, "events": events,
            "warning": "No recalled canary does not prove provider/session isolation."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--max-total-tokens", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("Output file must not already exist")
    try:
        from api_agent import call_model, configuration

        config = configuration()
        url, _key, params, _timeout = config

        def adapter(request, instructions):
            return call_model(request, resolved_config=config,
                              instructions=instructions)

        result = run_audit(adapter, rounds=args.rounds,
                           max_total_tokens=args.max_total_tokens)
        endpoint = urlsplit(url)
        result["audit_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        result["endpoint_origin"] = f"{endpoint.scheme}://{endpoint.hostname}"
        result["requested_parameters"] = params
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.out, result)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Provider-isolation audit: {result['status']} ({result['rounds_completed']} rounds)")
    return 0 if result["status"] == "not_detected_in_test" else 1


if __name__ == "__main__":
    raise SystemExit(main())
