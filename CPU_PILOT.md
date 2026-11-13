# CPU open-weight exploratory pilot (separate from Kaggle)

This route is intentionally **not** the original Kaggle Benchmarks execution path. It is a minimal, independently hosted *real-model smoke test* for the canonical four-arm `pilot.py` evaluator while Kaggle credentials/dispatch are unavailable. It is not a replacement for Kaggle and is not a confirmatory causal test.

## Invocation

The feature-branch GitHub Actions workflow `.github/workflows/cpu-openweight-exploratory.yml` uses a GitHub-hosted Ubuntu CPU runner and downloads the Apache-2.0 `HuggingFaceTB/SmolLM2-360M-Instruct` model at pinned revision `d22ba992b66e2217e204c1192b2fb496619d031c`. It pins `transformers==4.46.3` and CPU `torch==2.5.1+cpu` and records the installed package versions.

Run locally with the same dependencies:

```sh
python -m unittest -v test_cpu_openweight_pilot
python cpu_openweight_pilot.py --out cpu-pilot-results --count 1 --max-turns 2 --token-cap 12000
```

The single public synthetic task uses seed 1337 and all four original conditions. Every model turn constructs a fresh chat template from the exact canonical request and the shared `api_agent.INSTRUCTIONS`. No previous provider conversation is carried outside `history`/`ledger`. Generation is deterministic greedy decoding with 160 maximum new tokens. The runner uses a single loaded model for all turns and never sends requests to an external inference endpoint. It counts tokens directly from the tokenizer and saves even malformed raw responses. The canonical evaluator computes public/hidden scores and budget outcomes.

The runner writes `manifest.json`, `summary.json`, `raw-responses.jsonl`, and per-arm `trace.json` to the results directory. The Actions job additionally archives `pip-freeze.txt` and `commit.txt`, even after a failed model download or inference attempt. No secret is needed for this public model.

## Interpretation limits

**One task cannot provide positional balance** across four arms, credible power, or a causal estimate. This run may establish basic model response validity and resource demands, and it may identify immediate protocol incompatibilities. Model-generated JSON can be malformed; the trusted scorer records that failure and retains its measured token cost. The model is tiny, so its performance is not representative of larger systems. The public generator/seed are not a private holdout. Actual model inference must be confirmed from the GitHub Actions job and archived artifact, never inferred from unit tests.

Kaggle remains primary for the intended broader hosted pilot. Its workflow, secret requirement, and private-holdout prerequisites are unchanged.
