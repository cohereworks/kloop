# kloop

Can an agent sustain a coherent, cumulative line of inquiry when the only feedback it receives is a one-bit continuation signal?

This repository contains the first executable pilot. More precisely, `K` is a continuation signal in the **human feedback channel**; the agent can still obtain environmental evidence from tools and tests.

A standard-library Python harness for the four-condition continuation-feedback experiment. It is intentionally small, deterministic, inspectable, and dependency-free.

## Run the smoke test

From this directory (Python 3.10+):

```sh
python -m unittest discover -p 'test_*.py' -v
python pilot.py generate --seed 1337 --count 24 --out tasks.json
python pilot.py run --tasks tasks.json --out runs --agent "python /absolute/path/to/baseline_agent.py" --max-turns 6
```

The smoke-test adapter is a deterministic greedy search algorithm. Its result says nothing about LLM autonomy.

## Connect a real model

**Primary intended route: Kaggle Benchmarks.** The original repository explicitly named `KAGGLE_API_TOKEN`; this is an integration requirement, not merely historical context. Kaggle's CLI can authenticate non-interactively with that variable, submit benchmark tasks, run them against selected models through its Model Proxy, and download the results. See [KAGGLE.md](KAGGLE.md) for the execution flow and current limits.

Build a self-contained Kaggle task with `python build_kaggle_task.py`; the generated file is not checked into source control. The manually dispatched [Kaggle exploratory workflow](.github/workflows/kaggle-exploratory.yml) can verify credentials and quota, then optionally submit the task and run an explicitly selected model.

**Alternate route: direct model endpoint.** The bundled `api_agent.py` speaks an OpenAI-compatible Chat Completions JSON protocol. Set `KLOOP_MODEL` and either `KLOOP_API_KEY` or `OPENAI_API_KEY` through your normal secret-management mechanism; neither the credential nor its value belongs in the benchmark files. The default HTTPS endpoint is `https://api.openai.com/v1/chat/completions`. Set `KLOOP_API_URL` for a compatible provider or local loopback server.

```sh
python pilot.py run --tasks tasks.json --out model-runs \
  --agent "python /absolute/path/to/api_agent.py" \
  --max-turns 6 --max-total-tokens 12000 --timeout 90
```

Optional adapter settings: `KLOOP_MAX_COMPLETION_TOKENS` (default 1600), `KLOOP_TEMPERATURE`, `KLOOP_SEED`, `KLOOP_HTTP_TIMEOUT` (default 60 seconds), and `KLOOP_JSON_MODE` (`1` by default; set `0` for endpoints that lack JSON-object mode). Not every provider supports every optional parameter; there is no silent parameter fallback. The adapter records response ID, model, finish reason, requested parameters, and provider-reported token usage with each turn. It deliberately omits credentials from logs.

The runner's `--max-total-tokens` enforces a measured per-task/condition cap when usage is reported. A final API call can overshoot the cap; such an outcome is not scored as a success. For a real trial, use the same chosen model and adapter settings in all four arms, and keep API and test data accessible only to the trusted runner and adapter. A separate mock HTTP integration test exercises the entire request/response path without billable inference.

The local runner also accepts `--arm-order balanced --arm-seed INTEGER` to
randomize arm execution in complete four-task blocks. Every arm occupies each
position once per block; the selected schedule is saved in the summary.
Default `fixed` order retains historical calibration compatibility.

## Plug in a model or agent

Use `--agent "python /absolute/path/to/your_adapter.py"`. The command is invoked **once per turn** with JSON on stdin and must write exactly one JSON object to stdout. For relative commands, note that the harness runs each turn from a distinct run directory; use absolute paths for external adapters.

Input excerpt:

```json
{
  "schema": 1,
  "condition": {"feedback": "k", "state": "explicit"},
  "turn": 1,
  "task": {"id": "t0000", "spec": "...", "starter": {}, "public": []},
  "candidate": {},
  "public_evaluation": [],
  "human_signal": "K",
  "ledger": null,
  "history": [],
  "limits": {"max_nodes": 31, "max_state_chars": 4000}
}
```

Output:

```json
{
  "candidate": {"op": "add", "args": [{"var": "x"}, {"var": "y"}]},
  "message": "Adjusted the expression based on public examples",
  "ledger": {
    "objective": "Match the function",
    "established": [],
    "falsified": [],
    "unresolved": [],
    "next_action": "Test remaining cases",
    "verification": "Public examples only"
  }
}
```

`ledger` is required only for explicit-state arms. In implicit-state arms, the previous five action summaries are passed as `history`. In explicit-state arms, the current ledger is returned instead. The provided API adapter makes a fresh inference call per request, but the runner does not OS-sandbox arbitrary adapter programs; do not execute untrusted adapters next to hidden task files.

The expression grammar is: `{ "var": "x"|"y" }`, `{ "const": integer -8..8 }`, or `{ "op": "add"|"sub"|"mul"|"min"|"max", "args": [expression, expression] }` (maximum 31 nodes).

The harness writes one trace per task/condition and a scored `runs/summary.json`. See [PROTOCOL.md](PROTOCOL.md) for hypotheses, validity limits, and reporting requirements.

## Analyze paired trials and commit a private holdout

`analyze_trial.py` computes the three preregistered-candidate paired contrasts
(H3/H4/H5), deterministic bootstrap intervals, and per-arm usage from either
Kaggle result JSON or the local `runs/` directory. It rejects incomplete pairs
and can enforce a precommitted measured-token cap:

```sh
python analyze_trial.py runs --resamples 20000 --bootstrap-seed 20261103
```

`holdout_commitment.py` creates a random private seed/nonce manifest and a
public SHA-256 commitment to commit *before* model inference. Neither the
existing calibration data nor the public Kaggle exploratory task is a private
holdout. See [PREREGISTRATION.md](PREREGISTRATION.md) for the complete protocol,
required operator decisions, and the explicit limits on inferential claims.

`private_trial.py` is the trusted, in-process holdout executor for the direct
HTTPS adapter. It validates the public commitment and generator hash, derives
fresh task streams without writing hidden targets, uses balanced arm order,
and stores public-only traces. It never launches an arbitrary model-controlled
subprocess next to the holdout. It pins the endpoint/decoder configuration at
startup and treats changes in provider-reported model identity as protocol
errors. Once model credentials and a preregistered
budget exist, invocation is:

```sh
python private_trial.py \
  --private private-holdouts/manifest.json \
  --commitment holdout-commitment.json \
  --out private-runs --arm-seed INTEGER \
  --max-turns 6 --max-total-tokens TOKEN_CAP
```

This is a reviewed protocol boundary, **not** OS sandboxing of arbitrary
Python dependencies or evidence that model inference was performed.

## Calibration artifacts

`tasks-v2.json` is a **public calibration set**, including the reference expressions and hidden-case values. It is not an acceptable private holdout for confirmatory model evaluation. `REPORT.md` summarizes the deterministic smoke-test results; `reports/calibration-traces.zip` contains the full request/response records. Use a fresh, separately stored holdout seed for real-model trials.

## Project state

The current status, priority order, residual risks, and next experiment are recorded in [PLAN.md](PLAN.md).

## Discoverable uncertainty stratum

The second pilot permits agents to spend turns querying an environmental
oracle before submitting a solution. Unlike the original closed-specification
task, initial evidence is deliberately underdetermined. Its four-arm control
plane, deterministic baseline, and hosted-model adapter are documented in
[STRATA.md](STRATA.md). The discovery trials are separate from the original
calibration and must not be pooled with it without a stratified analysis plan.
The optional `--inject-probe-failure-at` exercises a retryable environmental
tool error without consuming evidence or probe budget; `analyze_recovery.py`
audits same-coordinate retry, hidden recovery, excess turns versus an unfailed
paired control, and public/hidden mismatches. These are descriptive diagnostics
and the bundled deterministic baseline is not a model robustness test.
`evidence_audit.py` independently certifies linear information gain from probes
over `GF(11)` and conservatively checks explicit ledgers for observation
references and incorrect values. Its optional typed `ledger.inferences` field
adds proof-based coefficient-claim classification: entailed, contradicted, or
underdetermined using only visible equations. A separate
`discovery_semantic_control.py` deterministic positive control and archived
paired normal/faulted traces exercise this measurement. Missing claims are
unscored, and no model prompt is retroactively modified. Unverifiable
natural-language assertions are reported as such; implicit arms have no
comparable ledger score. See
[STRATA.md](STRATA.md) and [REPORT.md](REPORT.md) for the proof semantics and
archived certificates.

### State-retention necessity diagnostic

The original discovery task repeats **all observations on every request**.
Consequently, preserving a ledger or message history is not necessary to
recover its coefficients, although it may help compute or organize them.
`discovery_retention.py` is a separate, explicitly non-confirmatory diagnostic
that exposes only new observations and varies access to previous messages.
State-blind and state-carrying deterministic controls demonstrate both the
information-loss boundary and that one recursively updated *implicit* message
can preserve the same public facts as an explicit ledger. Archived traces and
an independent disclosure/handoff replay audit are in [REPORT.md](REPORT.md).
Do not pool these asymmetric information conditions with the original four-arm
trial or interpret them as a measured benefit of structured state.

## Private preferences stratum

`preference_pilot.py` implements a third, deliberately distinct four-arm
experiment. A favorite among eight alternatives is held exclusively by the
preference evaluator. There is no environmental evidence that identifies it.
Agents can propose up to four candidates and must then commit; only rich
acceptance/rejection feedback reveals the holder's choice. Consequently,
all-`K` policies have a **1/8** expected success limit, even with perfect
reasoning, whereas four informed proposals plus a final guess attain **5/8**.
The deterministic negative control, API adapter, reproducibility commands,
and limits of the public calibration are documented in [STRATA.md](STRATA.md).
The third stratum is **not** included in the current Kaggle exploratory task.
For confidential model evaluations, use `preference_holdout.py` to commit an
unrevealed 256-bit key before inference and `preference_private_trial.py` to
score all paired arms through the trusted HTTP model channel. Each arm gets an
opaque task ID, not a shared identifier. See [STRATA.md](STRATA.md) for the
workflow, trust limitations, and reproducibility instructions.
`provider_isolation_audit.py` offers a synthetic canary test for cross-request
memory on the selected model endpoint. An exact canary recovery is evidence of
leakage; a clean result is explicitly inconclusive and does not certify the
provider's internal state isolation.

## Kaggle environment

```text
KAGGLE_API_TOKEN
```

This is the credential to provision for non-interactive Kaggle use. The deterministic local smoke test does not require it. It was absent from the worker that built this pilot, so no Kaggle run has been claimed. Do not commit its value.
