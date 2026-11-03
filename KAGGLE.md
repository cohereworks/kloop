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
python build_kaggle_task.py
python -m py_compile dist/kloop_kaggle_benchmark.py
```

The generated file is self-contained. It is built from the canonical `pilot.py` logic and the `kaggle_task_template.py` wrapper, then tested for semantic parity with the local task generator. The initial task executes just one deterministic task across four arms, with at most four model turns per arm.

To schedule an exploratory run after inspecting the quota and selecting a supported model:

```sh
kaggle benchmarks tasks push kloop-pilot -f dist/kloop_kaggle_benchmark.py --wait 1800
kaggle benchmarks tasks run kloop-pilot -m YOUR_MODEL_SLUG --wait 3600
kaggle benchmarks tasks status kloop-pilot
kaggle benchmarks tasks download kloop-pilot -m YOUR_MODEL_SLUG -o kaggle-results
```

Alternatively, configure a GitHub Actions repository secret named `KAGGLE_API_TOKEN` and dispatch the **Kaggle exploratory benchmark** workflow. Its default `execute=false` performs a readiness check only. Set `execute=true` with an explicit model slug to authorize Kaggle task creation and inference. The workflow is **never** triggered on ordinary pushes or pull requests.

Do not schedule the model run until its model, quota, and exploratory budget are acceptable. The task is initially limited to at most sixteen model calls (one task × four conditions × four turns), but it does **not** enforce equal per-arm token budgets. Treat its results as exploratory only.

## Evaluation invariants

- Each task/condition/turn is a new `kbench.chats.new()` context: Kaggle retains conversation history within a chat by default, which would otherwise confound our explicit-state factor.
- Only projected public examples and current candidate/state enter the model prompt; reference targets and hidden cases remain evaluator-side.
- `K` means continue, not correctness or preference endorsement.
- Per-turn Kaggle input/output token counts, costs, and latency are recorded when the Model Proxy reports them. Retain Kaggle's run identities and downloaded source/results. A confirmatory result requires budget normalization, a fresh private holdout, and preregistration.
- The existing direct API adapter remains available as a comparison path, not the assumed default.
- The Kaggle wrapper generates the task set within the trusted evaluator and sends only the `request_for()` projection to each `llm.prompt()`. The generated source is auditable in `dist/` before upload.

## Current readiness

Documentation, single-file task generation, state isolation, usage extraction, and four-arm message routing were locally tested with a mock model. `KAGGLE_API_TOKEN` and the `kaggle` CLI were not available in the current worker; no authenticated Kaggle call has been made, and API compatibility and run artifacts have not been verified against a live Kaggle task.
