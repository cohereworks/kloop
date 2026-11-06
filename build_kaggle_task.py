#!/usr/bin/env python3
"""Build a self-contained Kaggle Benchmarks task from the canonical pilot core."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


HERE = Path(__file__).resolve().parent
EXCLUDED_RUNNER_FUNCTIONS = {"cli", "invoke_agent", "run_one"}


def build(core_path: Path = HERE / "pilot.py",
          template_path: Path = HERE / "kaggle_task_template.py") -> str:
    tree = ast.parse(core_path.read_text(encoding="utf-8"), filename=str(core_path))
    # Kaggle uses only the task/evaluator helpers. Omit local-agent process
    # execution and its api_agent dependency from the standalone notebook.
    stripped = []
    for node in tree.body:
        if (isinstance(node, ast.FunctionDef) and
                node.name in EXCLUDED_RUNNER_FUNCTIONS):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "api_agent":
            if (node.level or len(node.names) != 1 or
                    node.names[0].name != "ModelResponseError" or
                    node.names[0].asname is not None):
                raise ValueError("Unexpected api_agent import in Kaggle core")
            continue
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            if (isinstance(node.test.left, ast.Name) and
                    node.test.left.id == "__name__"):
                continue
        stripped.append(node)
    assembled = ast.fix_missing_locations(ast.Module(body=stripped, type_ignores=[]))
    core = ast.unparse(assembled)
    template = template_path.read_text(encoding="utf-8")
    # Kaggle's percent-format notebook importer recognizes explicit cells.
    output = "# %%\n" + core + "\n\n# %%\n" + template
    output_tree = ast.parse(output, filename="generated_kaggle.py")
    local_names = {p.stem for p in core_path.parent.glob("*.py")}
    for node in ast.walk(output_tree):
        if isinstance(node, ast.Import):
            imported = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise ValueError("Kaggle task cannot contain relative imports")
            imported = {node.module.split(".")[0]} if node.module else set()
        else:
            continue
        if imported & local_names:
            raise ValueError(f"Kaggle task retains local imports: {sorted(imported & local_names)}")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "dist" / "kloop_kaggle_benchmark.py")
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(), encoding="utf-8")
    print(f"Built {args.out}")


if __name__ == "__main__":
    main()
