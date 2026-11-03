# Kaggle execution route

The repository's original README declared `KAGGLE_API_TOKEN`. This is the intended authentication mechanism for hosted evaluation, not an abandoned note.

## Supported path

Kaggle's official CLI supports non-interactive authentication through `KAGGLE_API_TOKEN`. The **Benchmarks** command group can upload a Python task, run it against a chosen model via Kaggle's Model Proxy, query status, download results, and inspect quota. The `kaggle-benchmarks` library supports multi-turn model interactions and explicit isolated chat contexts.

Authoritative references:

- [CLI authentication](https://github.com/Kaggle/kaggle-cli/blob/main/skills/references/auth.md)
- [Benchmarks CLI](https://github.com/Kaggle/kaggle-cli/blob/main/docs/benchmarks.md)
- [Benchmarks library quick start](https://github.com/Kaggle/kaggle-benchmarks/blob/main/quick_start.md)
- [Benchmarks library user guide](https://github.com/Kaggle/kaggle-benchmarks/blob/main/user_guide.md)

## Operator workflow

On a machine with Python 3.11+, the Kaggle CLI, and an authorized `KAGGLE_API_TOKEN` injected through secret management:

```sh
python -m pip install kaggle
kaggle benchmarks quota
kaggle benchmarks tasks models
```

The task source and `push` / `run` commands will be pinned here after the benchmark wrapper has been locally tested. Do not invoke the task creation/run operations until model choice, quota, and experiment budget are explicit; pushing a benchmark can execute model calls.

## Evaluation invariants

- Each task/condition/turn is a new `kbench.chats.new()` context: Kaggle retains conversation history within a chat by default, which would otherwise confound our explicit-state factor.
- Only projected public examples and current candidate/state enter the model prompt; reference targets and hidden cases remain evaluator-side.
- `K` means continue, not correctness or preference endorsement.
- Kaggle's reported usage/cost and run identities must be retained. A confirmatory result requires budget normalization, a fresh private holdout, and preregistration.
- The existing direct API adapter remains available as a comparison path, not the assumed default.

## Current readiness

Documentation and protocol verified from Kaggle's official sources. `KAGGLE_API_TOKEN` and the `kaggle` CLI were not available in the current worker; no authenticated Kaggle call has been made.
