#!/usr/bin/env python3
"""Counterbalance five legal edit labels for one identical public model request.

Measures first-position bias without scoring model improvements or changing
canonical pilot tasks. This is a diagnostic of one constrained token decoder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from cpu_choice_pilot import (MODEL, REVISION, PROMPT_VERSION, edit_options,
                              model_prompt, qwen_choice_model)
from pilot import canonical, make_tasks, request_for, write_json


def permutation_probe(infer, request):
    options = edit_options(request["candidate"])
    results = []
    for shift in range(5):
        rotated = options[shift:] + options[:shift]
        prompt = model_prompt(request, rotated)
        choice, prompt_tokens, logits = infer(prompt)
        if (type(choice) is not int or choice not in range(5) or
                type(prompt_tokens) is not int or prompt_tokens < 1 or
                not isinstance(logits, list) or len(logits) != 5):
            raise RuntimeError("Invalid model choice probe output")
        semantic_index = (choice + shift) % 5
        results.append({
            "rotation": shift,
            "displayed_index": choice,
            "original_option_index": semantic_index,
            "edit": {key: options[semantic_index][key]
                     for key in ("path", "field", "value")},
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 0,
            "option_logits": logits,
        })
    return {
        "rows": results,
        "chosen_index_unique_count": len({r["displayed_index"] for r in results}),
        "chosen_edit_unique_count": len({r["original_option_index"] for r in results}),
        "all_choose_first_label": all(r["displayed_index"] == 0 for r in results),
        "semantic_choice_invariant": len({r["original_option_index"] for r in results}) == 1,
    }


def execute(out_dir, *, infer=None, seed=1337):
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Output directory must be empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    task = make_tasks(seed, 1)["tasks"][0]
    request = request_for(task, ("k", "implicit"), 1, task["starter"], None, [])
    probe = permutation_probe(infer if infer is not None else qwen_choice_model(), request)
    manifest = {
        "kind": "finite_choice_label_rotation_diagnostic_not_confirmatory",
        "model": MODEL, "revision": REVISION, "seed": seed,
        "prompt_version": PROMPT_VERSION,
        "task_sha256": hashlib.sha256(canonical(task).encode()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "hypothesis": "argmax may choose the displayed first index independent of edit",
        "warning": "Five deterministic rotations of one request are not five independent tasks.",
    }
    write_json(out_dir / "manifest.json", manifest)
    write_json(out_dir / "rotation-analysis.json", probe)
    print(json.dumps({k: v for k, v in probe.items() if k != "rows"},
                     sort_keys=True), flush=True)
    for row in probe["rows"]:
        print(f"rotation={row['rotation']} displayed={row['displayed_index']} "
              f"original={row['original_option_index']} "
              f"edit={canonical(row['edit'])}", flush=True)
    return probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("cpu-choice-rotation"))
    args = parser.parse_args()
    execute(args.out)


if __name__ == "__main__":
    main()
