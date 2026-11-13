#!/usr/bin/env python3
"""Small out-of-band *real-model* CPU smoke test; not a Kaggle or confirmatory trial.

No model is downloaded until the CLI runs. The trusted canonical pilot scores
outputs; this module only provides local tokenized inference and evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from api_agent import INSTRUCTIONS, ModelResponseError
from pilot import CONDITIONS, aggregate, arm_schedule, canonical, make_tasks, run_one, write_json

MODEL = "HuggingFaceTB/SmolLM2-360M-Instruct"
REVISION = "d22ba992b66e2217e204c1192b2fb496619d031c"


def load_generator(model_id=MODEL, revision=REVISION, max_new_tokens=160):
    """One persistent CPU model, fresh prompt context for *every* turn."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision,
                                               trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(model_id, revision=revision,
                                                trust_remote_code=False)
    model.to("cpu").eval()

    def generate(system_text, user_text):
        messages = [{"role": "system", "content": system_text},
                    {"role": "user", "content": user_text}]
        input_ids = tokenizer.apply_chat_template(messages, tokenize=True,
                                                  add_generation_prompt=True,
                                                  return_tensors="pt")
        prompt_tokens = int(input_ids.shape[-1])
        with torch.inference_mode():
            full_ids = model.generate(input_ids, max_new_tokens=max_new_tokens,
                                      do_sample=False, pad_token_id=tokenizer.eos_token_id)
        completion_ids = full_ids[0][prompt_tokens:]
        completion_tokens = int(completion_ids.shape[0])
        raw = tokenizer.decode(completion_ids, skip_special_tokens=True)
        return raw, prompt_tokens, completion_tokens

    return generate


class CpuAdapter:
    """Model-facing local adapter with independent tokenizer-derived metering."""

    def __init__(self, generate, model_id=MODEL, revision=REVISION):
        self.generate = generate
        self.model_id = model_id
        self.revision = revision
        self.events = []

    def __call__(self, request):
        user_text = json.dumps(request, sort_keys=True, ensure_ascii=False)
        raw, n_prompt, n_completion = self.generate(INSTRUCTIONS, user_text)
        if (type(n_prompt) is not int or type(n_completion) is not int or
                min(n_prompt, n_completion) < 0):
            raise RuntimeError("Local tokenizer returned invalid token counts")
        metrics = {"model": self.model_id, "model_revision": self.revision,
                   "prompt_tokens": n_prompt, "completion_tokens": n_completion,
                   "total_tokens": n_prompt + n_completion,
                   "usage_provenance": "local_tokenizer_exact"}
        self.events.append({"request_sha256": hashlib.sha256(user_text.encode()).hexdigest(),
                            "raw_model_text": raw, "metrics": metrics})
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ModelResponseError("Local model output is not JSON", metrics) from exc
        if not isinstance(parsed, dict):
            raise ModelResponseError("Local model output is not a JSON object", metrics)
        # Never trust model-authored metadata; the local tokenizer owns it.
        parsed["metrics"] = metrics
        return parsed


def execute(out_dir, *, seed=1337, count=1, max_turns=2, cap=12000,
            arm_seed=20261112, model_id=MODEL, revision=REVISION,
            generate=None):
    if not 1 <= count <= 4 or not 1 <= max_turns <= 4 or cap < 1:
        raise ValueError("CPU smoke-test limits exceeded")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Output directory must be empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = make_tasks(seed, count)["tasks"]
    schedule = arm_schedule([t["id"] for t in tasks], mode="balanced", seed=arm_seed)
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest = {"kind": "cpu_openweight_exploratory_not_confirmatory",
                "model": model_id, "revision": revision,
                "seed": seed, "count": count, "max_turns": max_turns,
                "token_cap_per_arm": cap, "arm_seed": arm_seed,
                "runner_sha256": source_hash, "task_sha256": hashlib.sha256(canonical(tasks).encode()).hexdigest(),
                "schedule": {k: [f"{a}_{b}" for a, b in v] for k, v in schedule.items()},
                "note": "One task cannot be positionally balanced; no effect inference."}
    write_json(out_dir / "manifest.json", manifest)
    generator = generate if generate is not None else load_generator(model_id, revision)
    adapter = CpuAdapter(generator, model_id, revision)
    runs = []
    try:
        for task in tasks:
            for arm in schedule[task["id"]]:
                arm_name = f"{arm[0]}_{arm[1]}"
                run = run_one(task, arm, None, out_dir / task["id"] / arm_name,
                              max_turns, 90, max_total_tokens=cap, adapter=adapter)
                runs.append(run)
                write_json(out_dir / task["id"] / arm_name / "trace.json", run)
                print(f"{task['id']} {arm_name}: pass={run['hidden_pass']} error={run['error']}", flush=True)
    finally:
        # Persist raw model text even when it is unparseable or a later arm aborts.
        with (out_dir / "raw-responses.jsonl").open("w", encoding="utf-8") as stream:
            for event in adapter.events:
                stream.write(canonical(event) + "\n")
        write_json(out_dir / "summary.json", {"manifest": manifest,
                   "runs_completed": len(runs), "conditions": aggregate(runs),
                   "warning": "Small public synthetic exploratory test; not a causal effect estimate."})
    return runs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("cpu-pilot-results"))
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=2)
    parser.add_argument("--token-cap", type=int, default=12000)
    args = parser.parse_args(argv)
    execute(args.out, seed=args.seed, count=args.count,
            max_turns=args.max_turns, cap=args.token_cap)


if __name__ == "__main__":
    main()
