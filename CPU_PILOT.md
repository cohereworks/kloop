# CPU open-weight exploratory pilots (separate from Kaggle)

These are **real-model smoke tests of the canonical four-arm pilot**, deliberately outside the original Kaggle Benchmarks route. They were run on GitHub-hosted Ubuntu CPU hardware without a provider credential. The evaluator, scorer and task generator remain the canonical `pilot.py`; these are not causal or confirmatory comparisons.

## Executed runs

| Run | Pinned open model | Max new tokens | Valid JSON actions | Hidden successes | Evidence |
|---|---|---:|---:|---:|---|
| First | SmolLM2-360M-Instruct (`d22ba992b66e2217e204c1192b2fb496619d031c`) | 160 | 0/4 | 0/4 | [run 43352478701](https://github.com/cohereworks/kloop/actions/runs/43352478701) |
| Second | Qwen2.5-0.5B-Instruct (`7ae557604adf67be50417f59c2c2f167def9a775`) | 512 | 0/4 | 0/4 | [run 43353276367](https://github.com/cohereworks/kloop/actions/runs/43353276367) |

Both used seed 1337, one public synthetic expression-repair task and four arms. Each received one model call because its output failed parsing, so no iterative state update was actually executed.

The first model echoed the JSON input and exhausted its 160-token completion ceiling. The second model terminated naturally after 289–306 tokens, but every JSON-like output contained a malformed delimiter in the candidate expression at character offset 974; this is **not simply truncation**. The 512-token ceiling was not reached. Both used greedy decoding.

Source-controlled exact metering and failure classifications:
- [First run](reports/cpu-openweight-smollm-first-run.json), artifact SHA-256 `978682b08a75276264d388f14e544795022f6ac772c38c9f163c437768c64d41`.
- [Second run](reports/cpu-openweight-qwen-second-run.json), artifact SHA-256 `da6195eda257f55c697d2f700c97fa42aa54e90bed0f8f160a24ba3fa3b14b25`.

The Actions artifacts contain the **raw generated responses**, token counts derived from each model's tokenizer, complete scorer traces, the source commit, and installed package versions. The artifacts expire in February 2027; the summary records above are permanent. Never infer hidden-test success from a green workflow: the workflow treats malformed model output as a measured experimental failure, not a CI infrastructure failure.

## Execution and reproduction

The workflow in `.github/workflows/cpu-openweight-exploratory.yml` currently runs the **second** Qwen protocol-adequacy check. The first SmolLM test remains reproducible via:

```sh
python -m unittest -v test_cpu_openweight_pilot
python cpu_openweight_pilot.py --out cpu-pilot-results --count 1 --max-turns 2 --token-cap 12000
```

The second run is:

```sh
python cpu_openweight_qwen_pilot.py
```

Dependencies were pinned to `transformers==4.46.3` and `torch==2.5.1+cpu`; the complete resolved versions are in the action artifacts. Both runners use the same trusted evaluator but differ in model, output-token ceiling, and prompt framing. **Do not interpret cross-run differences as a controlled model or state-channel effect.**

## Scientific conclusion

There is now unambiguous evidence that the harness can execute and meter real open-weight language models. There is **no valid model action** in either run, so the project's state-persistence research hypothesis remains untested. The next real trial needs a model shown capable of the structured action protocol, not another deterministic control. The Kaggle route remains the intended primary hosted execution route and still requires an authorized `KAGGLE_API_TOKEN` / workflow dispatch.
