# Engineering pilot report

## Reproducibility

- Benchmark seed: `1337`
- Tasks: `12` closed-specification expression repairs
- Conditions: `K/implicit`, `K/explicit`, `rich/implicit`, `rich/explicit`
- Turn cap: `6` per task/condition
- Adapter: bundled deterministic `baseline_agent.py`, **not a language model**
- Interpreter: bundled pure JSON-expression evaluator
- Tests: `python -m unittest -v test_pilot test_api_agent` — **9 passing**, including local mock HTTP integration across all four conditions
- Task inputs and hidden reference data: `tasks-v2.json` (public calibration data)
- Summary and complete per-run audit traces: `reports/calibration-traces.zip`, containing `runs-v2/summary.json` and `runs-v2/tNNNN/{condition}/trace.json`

## Smoke-test observations

| Condition | Hidden passes | Public passes | Protocol errors | Mean turns |
|---|---:|---:|---:|---:|
| K / implicit | 2 / 12 | 2 / 12 | 0 | 5.33 |
| K / explicit | 2 / 12 | 2 / 12 | 0 | 5.33 |
| Rich / implicit | 2 / 12 | 2 / 12 | 0 | 5.33 |
| Rich / explicit | 2 / 12 | 2 / 12 | 0 | 5.33 |

The adapter disregards the human signal and does not use the ledger or history when choosing edits, so identical outcomes in all arms are expected. This result verifies that all arms execute and that data can be collected. It **does not** test whether explicit state improves an LLM's autonomy.

An earlier, easier two-mutation task generator was solved in 11/12 tasks by the same deterministic adapter. Before any LLM trials, the generator was strengthened to depth-three expressions with four distinct mutations. Those earlier smoke outcomes are not pooled with these results.

## Remaining experimental prerequisites

1. Supply an authorized live model endpoint and credentials for the bundled Chat Completions adapter; no API credential or local inference runtime was available in the current execution environment.
2. Run adapters in isolation from hidden targets (the pilot has logical request separation but not filesystem confinement).
3. Fix a sample-size and random-seed plan; report paired confidence intervals rather than interpreting 12 tasks as conclusive.
4. Add a genuine resource-matched feedback budget; the rich reviewer currently reformulates available public evidence rather than providing new user information.
5. Add task strata for discoverable uncertainty and privately held preferences; the current task family tests only fully specified goals.
6. Check instruction adherence and state quality independently of final hidden-test success.

## Working conclusion

The proposed four-arm control plane is implemented, executable, traceable, and dependency-free. Its model API wire path is integration-tested against a local mock server. The scientific claim remains **untested** until live inference and a properly controlled evaluation are run.
