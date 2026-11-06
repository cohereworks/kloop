#!/usr/bin/env python3
"""Fingerprint the transitive, statically imported local source closure.

This binds project Python files, not the interpreter, stdlib, installed wheels,
environment variables, network endpoint, or runtime-loaded source bytes.
Dynamic imports/code execution are rejected inside the trusted closure rather
than silently omitted from a purportedly complete local source inventory.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


def source_hashes(entrypoints, *, root=None):
    """Return sorted filename -> SHA-256 for recursively imported local files."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    names = {p.stem for p in root.glob("*.py") if p.is_file()}
    local_packages = {p.name for p in root.iterdir()
                      if p.is_dir() and any(p.rglob("*.py"))}
    pending = set(entrypoints)
    if not pending or any(name not in names for name in pending):
        raise ValueError("Trusted source entrypoint missing from local project")
    seen = {}
    while pending:
        name = min(pending)
        pending.remove(name)
        if name in seen:
            continue
        path = root / (name + ".py")
        if path.is_symlink():
            raise ValueError(f"Trusted source must not be a symlink: {path.name}")
        raw = path.read_bytes()
        try:
            parsed = ast.parse(raw, filename=str(path))
        except SyntaxError as exc:
            raise ValueError(f"Unparseable trusted source: {path.name}") from exc
        imported = set()
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    raise ValueError(f"Relative import needs explicit review: {path.name}")
                if node.module:
                    imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                target = node.func
                if (isinstance(target, ast.Name) and target.id in
                        {"__import__", "eval", "exec", "compile"}):
                    raise ValueError(f"Dynamic code/import requires review: {path.name}")
                if (isinstance(target, ast.Attribute) and
                        target.attr == "import_module" and
                        isinstance(target.value, ast.Name) and
                        target.value.id == "importlib"):
                    raise ValueError(f"Dynamic import requires review: {path.name}")
        if imported & local_packages:
            raise ValueError(f"Local package imports need explicit review: {path.name}")
        pending.update((imported & names) - set(seen))
        seen[name] = hashlib.sha256(raw).hexdigest()
    return {name + ".py": seen[name] for name in sorted(seen)}
