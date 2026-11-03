#!/usr/bin/env python3
"""Create/verify a salted SHA-256 commitment to a private holdout manifest.

The public commitment is not the private manifest. Commit the public JSON to
GitHub BEFORE inference, retain the private JSON outside version control, and
reveal it for independent verification only after the recorded experiment ends.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import secrets
from pathlib import Path


SCHEMA = "kloop-holdout-v1"


def canonical_bytes(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def make_manifest(*, count, repetitions, pilot_sha256):
    if not 1 <= count <= 1000 or not 1 <= repetitions <= 100:
        raise ValueError("count 1..1000 and repetitions 1..100 required")
    return {
        "schema": SCHEMA,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "seed": secrets.randbits(63),
        "nonce": secrets.token_hex(32),
        "task_count": count,
        "repetitions": repetitions,
        "pilot_sha256": pilot_sha256,
    }


def commitment(manifest):
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported holdout manifest schema")
    return {
        "schema": "kloop-holdout-commitment-v1",
        "algorithm": "SHA-256 of canonical JSON (sorted compact keys)",
        "manifest_sha256": hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
        "task_count": manifest["task_count"],
        "repetitions": manifest["repetitions"],
        "pilot_sha256": manifest["pilot_sha256"],
    }


def verify(manifest, public):
    if commitment(manifest) != public:
        raise ValueError("Holdout manifest does not match public commitment")
    return True


def write_new(path, content, *, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(content, stream, indent=2, sort_keys=True)
        stream.write("\n")


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
                raise ValueError("Refusing to overwrite an existing manifest/commitment")
            pilot_file = Path(__file__).resolve().parent / "pilot.py"
            pilot_sha = hashlib.sha256(pilot_file.read_bytes()).hexdigest()
            manifest = make_manifest(count=args.count, repetitions=args.repetitions,
                                     pilot_sha256=pilot_sha)
            write_new(args.private, manifest, private=True)
            write_new(args.commitment, commitment(manifest))
            print(f"Private manifest: {args.private} (never commit)")
            print(f"Public commitment: {args.commitment}")
        else:
            manifest = json.loads(args.private.read_text(encoding="utf-8"))
            public = json.loads(args.commitment.read_text(encoding="utf-8"))
            verify(manifest, public)
            print("Holdout commitment verified")
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
