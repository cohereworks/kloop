#!/usr/bin/env python3
"""Generate and verify sealed commitments for private-preference trials.

The private manifest must never be committed or exposed to a model endpoint.
The public commitment binds the manifest and both task/scorer implementations.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import secrets
from pathlib import Path

from holdout_commitment import canonical_bytes, write_new


SCHEMA = "kloop-preference-holdout-v1"
PUBLIC_SCHEMA = "kloop-preference-holdout-commitment-v1"
FILES = ("preference_pilot.py", "preference_private_trial.py")


def code_hashes():
    root = Path(__file__).resolve().parent
    return {f.replace(".py", "_sha256"): hashlib.sha256((root / f).read_bytes()).hexdigest()
            for f in FILES}


def make_manifest(*, count, repetitions):
    if not 1 <= count <= 1000 or not 1 <= repetitions <= 100:
        raise ValueError("count 1..1000 and repetitions 1..100 required")
    return {"schema": SCHEMA,
            "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "secret_key": secrets.token_hex(32),
            "task_count": count, "repetitions": repetitions,
            **code_hashes()}


def commitment(manifest):
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported preference-holdout schema")
    return {"schema": PUBLIC_SCHEMA,
            "algorithm": "SHA-256 of canonical JSON (sorted compact keys)",
            "manifest_sha256": hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
            "task_count": manifest["task_count"],
            "repetitions": manifest["repetitions"],
            **{key: manifest[key] for key in code_hashes()}}


def verify(manifest, public):
    if commitment(manifest) != public:
        raise ValueError("Preference-holdout manifest does not match public commitment")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--private", type=Path, required=True)
    create.add_argument("--commitment", type=Path, required=True)
    create.add_argument("--count", type=int, required=True)
    create.add_argument("--repetitions", type=int, default=1)
    check = sub.add_parser("verify")
    check.add_argument("--private", type=Path, required=True)
    check.add_argument("--commitment", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            if args.private.resolve() == args.commitment.resolve():
                raise ValueError("Private and public paths must differ")
            if args.private.exists() or args.commitment.exists():
                raise ValueError("Refusing to overwrite an existing commitment")
            private = make_manifest(count=args.count, repetitions=args.repetitions)
            write_new(args.private, private, private=True)
            write_new(args.commitment, commitment(private))
            print(f"Private preference manifest: {args.private} (never commit)")
            print(f"Public preference commitment: {args.commitment}")
        else:
            private = json.loads(args.private.read_text(encoding="utf-8"))
            public = json.loads(args.commitment.read_text(encoding="utf-8"))
            verify(private, public)
            print("Preference-holdout commitment verified")
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
