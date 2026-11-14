# Finite-choice CPU model action pilot

This protocol-adequacy experiment follows the two archived unconstrained model-output failures described in [CPU_PILOT.md](CPU_PILOT.md). It does **not** retroactively change either result.

The problem is now decomposed into:

1. **Model decision:** choose one of four candidate single-node edits, plus a no-op, using a real Qwen2.5-0.5B-Instruct forward pass.
2. **Host serialization/validation:** construct the AST deterministically from the selected legal edit and pass it to the *original* `pilot.run_one` scorer.

This eliminates large free-form AST output as a prerequisite for evaluating *choice behavior*. It does not demonstrate that the model can emit valid JSON, author a sound ledger, or optimize the task. The explicit ledger is generated from the model's actual chosen edit by a host adapter; it is **not** a free-form model-authored reasoning record. As in the original protocol, the public task supplies enough information that one cannot interpret retention effects causally.

## Evidence contract

- Model: `Qwen/Qwen2.5-0.5B-Instruct` at revision `7ae557604adf67be50417f59c2c2f167def9a775`
- Model sees current candidate, public examples, feedback signal, and the appropriate visible carrier, plus the four legal edit headers and no-op
- Host never includes `_target`, `_hidden`, hidden evaluation, or the scores for the offered edits
- Model uses a fresh chat template on every turn, with an explicit attention mask
- A single forward pass produces logits for five digit tokens (`0`...`4`); `argmax` selects a digit. **No completion token is generated.** The measured `prompt_tokens` count covers the forward input, `completion_tokens` is correctly **zero**, and `decision_tokens_scored=1` records the single-token classification operation
- The host creates a grammar-valid single-node expression edit and a deterministic carrier describing the choice
- Canonical `pilot.run_one` checks public/hidden success, turn count, and a bounded per-arm token sum
- `model-decisions.jsonl` saves every exact prompt, chosen index, all five logits, selected edit and tokenizer metering; `trace.json` persists each canonical evaluator step, and `manifest.json` records source/task/model identities
- A successful CI job **does not imply** any task success or causal effect

This is a diagnostic with one public seeded task, four arms, at most two turns per arm, deterministic candidate menus, greedy argmax choice and a maximum of 12,000 input tokens per arm. It does not create an independent holdout or match model resource budgets across hypothetical state representations. It is a *new action interface*, so compare it with the earlier failed free-form-output pilots only to establish that the validity bottleneck can be bypassed through constrained decisions, not as a performance effect.

## Run

```sh
python -m unittest -v test_cpu_choice_pilot
python cpu_choice_pilot.py --out cpu-choice-results
```

The feature branch has a **one-shot PR-triggered** GitHub Actions workflow for the initial real-model test. Before merging, the workflow must be changed to **manual dispatch only** to avoid recurring inference charges from routine PR synchronization. The Kaggle route remains untouched and remains the primary intended hosted evaluation.
