#!/usr/bin/env python3
"""Exploratory finite-choice model action: bounded logits, canonical pilot scorer.

A chosen edit is a REAL model decision but its structure is host-supplied and
validated. Never interpret syntactic action validity as model reasoning ability.
This is not comparable to the unconstrained SmolLM/Qwen generation pilots.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from api_agent import ModelResponseError
from cpu_openweight_pilot import MODEL as SMOLLM_MODEL
from pilot import (CONDITIONS, OPS, arm_schedule, canonical, make_tasks, node_at,
                   node_paths, run_one, validate_expr, write_json, aggregate)

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
PROMPT_VERSION = "bounded-choice-v1"

INSTRUCTIONS = """Select a single, concrete edit to improve the public examples.
The response must be ONE digit 0, 1, 2, 3 or 4.
The environment supplies five legal choices. No edit is also a legal choice.
Use only PUBLIC evidence. A K signal gives permission to continue, not correctness.
Never assume hidden cases pass. Do not output an expression tree.
"""


def edit_options(candidate):
    """Four deterministic, diverse single-node edits plus explicit no-op.

    The host does NOT rank edits by scores or hidden/public target results.
    Options depend only on the current visible candidate. Each is validated.
    """
    validate_expr(candidate)
    proposals = []
    for path, node in node_paths(candidate):
        if "op" in node:
            for op in OPS:
                if op != node["op"]:
                    proposals.append((list(path), "op", op))
        elif "const" in node:
            for value in (-2, -1, 1, 2):
                if value != node["const"] and -8 <= value <= 8:
                    proposals.append((list(path), "const", value))
    if len(proposals) < 4:
        raise ValueError("Candidate has too few edit proposals")
    indices = [i * (len(proposals) - 1) // 3 for i in range(4)]
    selected = [proposals[i] for i in indices]
    choices = []
    for path, field, value in selected:
        trial = copy.deepcopy(candidate)
        node_at(trial, path)[field] = value
        validate_expr(trial)
        choices.append({"path": path, "field": field, "value": value, "candidate": trial})
    choices.append({"path": [], "field": "noop", "value": None,
                    "candidate": copy.deepcopy(candidate)})
    return choices


def model_prompt(request, options):
    """Include only model-visible information; no target, score, or hidden cases."""
    public_request = {k: v for k, v in request.items()
                      if k not in {"public_evaluation"}}
    option_headers = [{"index": i, "path": item["path"],
                       "field": item["field"], "value": item["value"]}
                      for i, item in enumerate(options)]
    return ("REQUEST_JSON:\n" + canonical(public_request) +
            "\nEDIT_CHOICES:\n" + canonical(option_headers) +
            "\nAnswer with ONE digit [0-4].\n")


def qwen_choice_model(model_id=MODEL, revision=REVISION):
    """Compute a one-step conditional logit choice with explicit attention mask."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision,
                                              trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(model_id, revision=revision,
                                               trust_remote_code=False)
    model.to("cpu").eval()
    option_ids = []
    for digit in "01234":
        encoded = tokenizer.encode(digit, add_special_tokens=False)
        if len(encoded) != 1:
            raise RuntimeError("Choice digit is not single-token; cannot compare logits")
        option_ids.append(encoded[0])
    if len(set(option_ids)) != 5:
        raise RuntimeError("Choice token IDs are not distinct")

    def infer(prompt):
        messages = [{"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": prompt}]
        rendered = tokenizer.apply_chat_template(messages, tokenize=False,
                                                  add_generation_prompt=True)
        encoded = tokenizer(rendered, return_tensors="pt",
                            add_special_tokens=False, return_attention_mask=True)
        with torch.inference_mode():
            logits = model(**encoded).logits[0, -1]
        option_logits = logits[option_ids].float()
        winner = int(torch.argmax(option_logits).item())
        return winner, int(encoded["input_ids"].shape[-1]), [
            round(float(x), 6) for x in option_logits.tolist()]
    return infer


class FiniteChoiceAdapter:
    def __init__(self, infer, *, model_id=MODEL, revision=REVISION):
        self.infer = infer
        self.model_id = model_id
        self.revision = revision
        self.events = []

    def __call__(self, request):
        options = edit_options(request["candidate"])
        prompt = model_prompt(request, options)
        # The model selects a digit based on logits, not an AST or JSON object.
        selected, prompt_tokens, option_logits = self.infer(prompt)
        if (type(selected) is not int or selected not in range(5) or
                type(prompt_tokens) is not int or prompt_tokens < 1 or
                not isinstance(option_logits, list) or len(option_logits) != 5 or
                any(type(x) not in (int, float) for x in option_logits)):
            raise RuntimeError("Invalid model decision or token metering")
        choice = options[selected]
        # Only a forward pass was performed; no token was actually decoded.
        metrics = {"model": self.model_id, "model_revision": self.revision,
                   "prompt_tokens": prompt_tokens, "completion_tokens": 0,
                   "total_tokens": prompt_tokens, "decision_tokens_scored": 1,
                   "usage_provenance": "local_tokenizer_forward_only"}
        self.events.append({
            "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "choice_token": str(selected), "choice_logits": option_logits,
            "selected_edit": {k: choice[k] for k in ("path", "field", "value")},
            "metrics": metrics,
        })
        selected_text = canonical({"path": choice["path"], "field": choice["field"],
                                   "value": choice["value"]})
        message = "Model chose edit index " + str(selected) + ": " + selected_text
        ledger = {"objective": "Fit public examples using valid single-node edits",
                  "established": [message], "falsified": [],
                  "unresolved": ["No hidden targets were disclosed"],
                  "next_action": "Recheck public examples",
                  "verification": "Candidate is grammar-valid; performance unverified"}
        return {"candidate": choice["candidate"], "message": message,
                "ledger": ledger, "metrics": metrics}


def execute(out_dir, *, seed=1337, max_turns=2, cap=12000,
            model_id=MODEL, revision=REVISION, infer=None):
    if not 1 <= max_turns <= 4 or cap < 1:
        raise ValueError("Invalid exploratory resource limits")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Output must be a new/empty directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    task = make_tasks(seed, 1)["tasks"][0]
    schedule = arm_schedule([task["id"]], mode="balanced", seed=20261114)
    manifest = {
        "kind": "bounded_logit_choice_exploratory_not_confirmatory",
        "model": model_id, "revision": revision, "prompt_version": PROMPT_VERSION,
        "seed": seed, "max_turns": max_turns, "cap": cap,
        "single_task_not_positionally_balanced": True,
        "task_sha256": hashlib.sha256(canonical(task).encode()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schedule": [f"{a}_{b}" for a, b in schedule[task["id"]]],
    }
    write_json(out_dir / "manifest.json", manifest)
    adapter = FiniteChoiceAdapter(infer if infer is not None else
                                  qwen_choice_model(model_id, revision),
                                  model_id=model_id, revision=revision)
    runs = []
    try:
        for arm in schedule[task["id"]]:
            name = f"{arm[0]}_{arm[1]}"
            result = run_one(task, arm, None, out_dir / name,
                             max_turns, 90, max_total_tokens=cap, adapter=adapter)
            runs.append(result)
            write_json(out_dir / name / "trace.json", result)
            print(f"{name} turns={result['turns']} error={result['error']} "
                  f"hidden_pass={result['hidden_pass']}", flush=True)
    finally:
        with (out_dir / "model-decisions.jsonl").open("w", encoding="utf-8") as stream:
            for event in adapter.events:
                stream.write(canonical(event) + "\n")
        write_json(out_dir / "summary.json", {
            "manifest": manifest, "runs_completed": len(runs),
            "conditions": aggregate(runs),
            "warning": "Valid AST guaranteed by host menu; model selected only digit."
        })
    return runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("cpu-choice-results"))
    args = parser.parse_args()
    execute(args.out)


if __name__ == "__main__":
    main()
