import hashlib
import tempfile
import unittest
from pathlib import Path

from trusted_sources import source_hashes


class TrustedSourceClosureTests(unittest.TestCase):
    def test_transitive_and_nested_local_imports_are_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "entry.py").write_text(
                "import json\nfrom next_module import value\n", encoding="utf-8")
            (root / "next_module.py").write_text(
                "def value():\n    from last_module import identity\n"
                "    return identity()\n", encoding="utf-8")
            (root / "last_module.py").write_text(
                "from entry import value\n", encoding="utf-8")
            (root / "unrelated.py").write_text("ignored = True\n", encoding="utf-8")
            result = source_hashes(("entry",), root=root)
            self.assertEqual(list(result), ["entry.py", "last_module.py",
                                            "next_module.py"])
            self.assertEqual(result["entry.py"], hashlib.sha256(
                (root / "entry.py").read_bytes()).hexdigest())
            (root / "last_module.py").write_text(
                "from entry import value\n# revised\n", encoding="utf-8")
            revised = source_hashes(("entry",), root=root)
            self.assertNotEqual(result, revised)
            self.assertEqual(result["entry.py"], revised["entry.py"])

    def test_missing_entrypoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "entrypoint missing"):
                source_hashes(("not_here",), root=Path(tmp))

    def test_dynamic_imports_and_execution_are_not_silently_skipped(self):
        for body in ("__import__('external')\n",
                     "import importlib\nimportlib.import_module('other')\n",
                     "exec('x = 1')\n"):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "entry.py").write_text(body, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Dynamic"):
                    source_hashes(("entry",), root=root)

    def test_relative_import_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "entry.py").write_text(
                "from .local import value\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Relative import"):
                source_hashes(("entry",), root=root)

    def test_local_package_import_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "entry.py").write_text("import localpkg\n", encoding="utf-8")
            package = root / "localpkg"
            package.mkdir()
            (package / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Local package"):
                source_hashes(("entry",), root=root)

    def test_unparseable_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "entry.py").write_text("def broken(:\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unparseable trusted source"):
                source_hashes(("entry",), root=root)


if __name__ == "__main__":
    unittest.main()
