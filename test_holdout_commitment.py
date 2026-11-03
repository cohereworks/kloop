import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from holdout_commitment import commitment, main, make_manifest, verify


class HoldoutCommitmentTests(unittest.TestCase):
    def test_salted_manifest_and_private_public_separation(self):
        with patch("holdout_commitment.secrets.randbits", return_value=42), \
                patch("holdout_commitment.secrets.token_hex", return_value="b" * 64):
            first = make_manifest(count=12, repetitions=2, pilot_sha256="a" * 64)
        with patch("holdout_commitment.secrets.randbits", return_value=43), \
                patch("holdout_commitment.secrets.token_hex", return_value="c" * 64):
            second = make_manifest(count=12, repetitions=2, pilot_sha256="a" * 64)
        self.assertNotEqual(first["seed"], second["seed"])
        self.assertNotEqual(first["nonce"], second["nonce"])
        public = commitment(first)
        self.assertEqual(len(public["manifest_sha256"]), 64)
        self.assertNotIn("seed", public)
        self.assertNotIn("nonce", public)
        self.assertTrue(verify(first, public))
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify({**first, "seed": first["seed"] + 1}, public)

    def test_cli_round_trip_no_overwrite_and_private_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private.json"
            public = root / "public.json"
            argv = ["create", "--private", str(private), "--commitment", str(public),
                    "--count", "16", "--repetitions", "1"]
            self.assertEqual(main(argv), 0)
            self.assertEqual(main(["verify", "--private", str(private),
                                   "--commitment", str(public)]), 0)
            self.assertEqual(stat.S_IMODE(os.stat(private).st_mode), 0o600)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(argv)
            manifest = json.loads(private.read_text())
            self.assertEqual(manifest["task_count"], 16)
            self.assertNotIn(str(manifest["seed"]), public.read_text())


if __name__ == "__main__":
    unittest.main()
