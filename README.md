# kloop

Can an agent sustain a coherent, cumulative line of inquiry when the only feedback it receives is a one-bit continuation signal?

This repository contains the first executable pilot. More precisely, `K` is a continuation signal in the **human feedback channel**; the agent can still obtain environmental evidence from tools and tests.

A standard-library Python harness for the four-condition continuation-feedback experiment. It is intentionally small, deterministic, inspectable, and dependency-free.

## Run the smoke test

From this directory (Python 3.10+):

```sh
python -m unittest -v test_pilot test_api_agent
python pilot.py generate --seed 1337 --count 24 --out tasks.json
python pilot.py run --tasks tasks.json --out runs --agent "python /absolute/path/to/baseline_agent.py" --max-turns 6
```

The smoke-test adapter is a deterministic greedy search algorithm. Its result says nothing about LLM autonomy.

## Connect a real model

The bundled `api_agent.py` speaks an OpenAI-compatible Chat Completions JSON protocol. Set `KLOOP_MODEL` and either `KLOOP_API_KEY` or `OPENAI_API_KEY` through your normal secret-management mechanism; neither the credential nor its value belongs in the benchmark files. The default HTTPS endpoint is `https://api.openai.com/v1/chat/completions`. Set `KLOOP_API_URL` for a compatible provider or local loopback server.

```sh
python pilot.py run --tasks tasks.json --out model-runs \
  --agent "python /absolute/path/to/api_agent.py" \
  --max-turns 6 --max-total-tokens 12000 --timeout 90
```

Optional adapter settings: `KLOOP_MAX_COMPLETION_TOKENS` (default 1600), `KLOOP_TEMPERATURE`, `KLOOP_SEED`, `KLOOP_HTTP_TIMEOUT` (default 60 seconds), and `KLOOP_JSON_MODE` (`1` by default; set `0` for endpoints that lack JSON-object mode). Not every provider supports every optional parameter; there is no silent parameter fallback. The adapter records response ID, model, finish reason, requested parameters, and provider-reported token usage with each turn. It deliberately omits credentials from logs.

The runner's `--max-total-tokens` enforces a measured per-task/condition cap when usage is reported. A final API call can overshoot the cap; such an outcome is not scored as a success. For a real trial, use the same chosen model and adapter settings in all four arms, and keep API and test data accessible only to the trusted runner and adapter. A separate mock HTTP integration test exercises the entire request/response path without billable inference.

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

## Calibration artifacts

`tasks-v2.json` is a **public calibration set**, including the reference expressions and hidden-case values. It is not an acceptable private holdout for confirmatory model evaluation. `REPORT.md` summarizes the deterministic smoke-test results; `reports/calibration-traces.zip` contains the full request/response records. Use a fresh, separately stored holdout seed for real-model trials.

## Project state

The current status, priority order, residual risks, and next experiment are recorded in [PLAN.md](PLAN.md).

## Environment notes

The original repository included `KAGGLE_API_TOKEN` as a prospective environment variable. It is not required by this Python pilot; no credential is included in the repository.
