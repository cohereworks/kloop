#!/usr/bin/env python3
"""Build a self-contained Kaggle Benchmarks task from the canonical pilot core."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


HERE = Path(__file__).resolve().parent


def build(core_path: Path = HERE / "pilot.py",
          template_path: Path = HERE / "kaggle_task_template.py") -> str:
    tree = ast.parse(core_path.read_text(encoding="utf-8"), filename=str(core_path))
    # The command-line entry point is not part of a Kaggle notebook task.
    stripped = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "cli":
            continue
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            if (isinstance(node.test.left, ast.Name) and
                    node.test.left.id == "__name__"):
                continue
        stripped.append(node)
    core = ast.unparse(ast.fix_missing_locations(ast.Module(body=stripped, type_ignores=[])))
    template = template_path.read_text(encoding="utf-8")
    return core + "\n\n" + template


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "dist" / "kloop_kaggle_benchmark.py")
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(), encoding="utf-8")
    print(f"Built {args.out}")


if __name__ == "__main__":
    main()
