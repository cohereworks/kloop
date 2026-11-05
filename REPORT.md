# Engineering pilot report

## Reproducibility

- Benchmark seed: `1337`
- Tasks: `12` closed-specification expression repairs
- Conditions: `K/implicit`, `K/explicit`, `rich/implicit`, `rich/explicit`
- Turn cap: `6` per task/condition
- Adapter: bundled deterministic `baseline_agent.py`, **not a language model**
- Interpreter: bundled pure JSON-expression evaluator
- Initial calibration had **10 passing tests**; the expanded multi-stratum suite now has **72 passing tests**, including mock HTTP, paired analysis, noninterference, four-arm subprocess checks, trusted-runner checks, endpoint-memory canary controls, trace-replay fault-recovery tests, finite-field evidence/ledger-fidelity adversarial tests, and retention-projection tests
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

1. Provision `KAGGLE_API_TOKEN` as a GitHub Actions secret or worker credential, then run the manually gated Kaggle exploratory workflow. The direct Chat Completions adapter remains an alternate route. Neither provider credential was available in the current worker.
2. Run adapters in isolation from hidden targets (the pilot has logical request separation but not filesystem confinement).
3. Fix a sample-size and random-seed plan; report paired confidence intervals rather than interpreting 12 tasks as conclusive.
4. Add a genuine resource-matched feedback budget; the rich reviewer currently reformulates available public evidence rather than providing new user information.
5. Preserve the implemented discovery and preference strata as separate task families; do not pool them into the closed-specification trial or infer model performance from their synthetic controls.
6. Check instruction adherence and state quality independently of final hidden-test success.

## Working conclusion

The four-arm control plane is implemented, executable, and traceable. Its direct model API path is integration-tested against a local mock server, and a Kaggle Benchmarks task is generated and mock-tested without requiring the Kaggle library locally. Neither route has completed live inference. The scientific claim remains **untested** until a properly controlled evaluation is run.

The later private-holdout runner uses a trusted in-process HTTPS adapter,
HMAC-derived task streams from a committed private seed, and seeded balanced
arm scheduling. Mock integration verifies that model-facing messages and
persisted traces contain no hidden cases, targets, or private nonce. The
suite at that stage had 24 tests. This does not constitute live inference or an
external security audit.

## Discoverable-uncertainty calibration

The second stratum's deterministic probe-first baseline was run on 12 seeded
tasks under all four arms (`seed=1337`, `arm_seed=20261103`, 6-turn cap).
All conditions succeeded on **12/12** tasks, with two probe actions and one
submission each. The paired H3/H4/H5 contrast estimates were all zero.
The extracted trace-tree evidence digest is
`dc39b670a90544298c2404d306339a7bbb85368d95118b504b911996940aab3b`;
the complete negative-control traces are archived in
`reports/discovery-calibration-traces.zip` and reproducible using
`discovery_pilot.py`/`discovery_baseline_agent.py`. Token usage is unknown for
this non-model baseline. None of these results are evidence of LLM autonomy.

## Transient-probe recovery calibration (no live model)

The deterministic discovery baseline was run on the same 12 tasks and four
arms with and without one synthetic failure on the first probe attempt:
`seed=1337`, `arm_seed=20261103`, `max_turns=6`.

| Per-arm metric | No-fault control | Single injected failure |
|---|---:|---:|
| Hidden-test completions | 12/12 | 12/12 |
| Successful observations | 2/run | 2/run |
| Total turns | 3/run | 4/run |
| Retry same coordinate next turn | N/A | 12/12 |
| False public successes | 0 | 0 |

All 48 faulted runs successfully retried the failed coordinate on the next
turn; none consumed the probe allowance or exposed a target observation at
the failure point. The mean turn overhead was precisely one. `analyze_recovery.py`
replays observation and budget changes, validates fault delivery, checks
complete four-arm pairs, and counts hidden failures behind apparent public
success. A deliberately premature-submission test verifies that an
observation-consistent but hidden-wrong answer is not counted as recovery.

- Complete control and faulted trace trees:
  `reports/discovery-fault-calibration-traces.zip`
- ZIP SHA-256:
  `8143225641dc299ba936180eab78223872fe1bbf5de7fb0aebeb1feeb71d4ee2`
- Audited analysis: `reports/discovery-fault-calibration-analysis.json`
- Faulted trace-tree evidence SHA-256:
  `cd4dd0a51c7642101785fc1339765d6433b8a7f633a47db02d72db60edee90fd`
- No-fault control trace-tree evidence SHA-256:
  `0ec0980ab0fd5d3c552abd4b0e0ab1be73b9bbf42a51059dcce16e0cefa13ce3`

This is a **protocol negative control** for one retryable failure type. It
cannot establish language-model resilience, nor transfer directly to
non-retryable tool errors, incorrect observations, or independent state
quality. No provider inference was executed.

## Independent evidence/ledger-fidelity calibration (no live model)

`evidence_audit.py` replayed both archived 12-task, four-arm discovery
regimes and derived per-turn certificates *without* consulting hidden targets
or agent explanations. The initial two observations give a coefficient rank of
`2`, leaving `11² = 121` compatible functions. The two baseline probes
each add an independent equation: the hypothesis counts descend `121 → 11 → 1`.

| Per-arm metric | Control | Injected-fault regime |
|---|---:|---:|
| Informative completed probes | 24/24 | 24/24 |
| Redundant completed probes | 0 | 0 |
| Underidentified submissions | 0 | 0 |
| Inconsistent observation sets | 0 | 0 |
| Explicit ledger observation-reference coverage | 100% | 100% |
| Explicit ledger **value** claims verified | **0** | **0** |

The last row is important: the negative-control ledger remembers which
coordinates are observed, not their numeric values. Thus perfect *reference*
coverage is **not** a certificate of high-quality reasoning or a complete
state representation. Ledger metrics for implicit arms are N/A, never zero.
In tests, the independent scorer detects redundant `(2,0)` probes,
underidentified public-passing guesses, contradicted numerical claims,
unobserved/duplicate references, and incompatible evidence. Free-form claims
remain explicitly uncertifiable.

- Aggregate reports: `reports/discovery-evidence-control-summary.json` and
  `reports/discovery-evidence-faulted-summary.json`
- Full per-turn rank/pivot/hypothesis/ledger certificates:
  `reports/discovery-evidence-certificates.zip`
- Certificate ZIP SHA-256:
  `83476267633ffb9346be96ae950d0d151062bfb4425a21ed9baadc9baaac0d91`
- Control/fault source trace-tree SHA-256 values are the same as the
  recovery calibration above; both summaries bind their respective source.

This audit proves exact rank facts in the **toy specified hypothesis class**.
It does not validate an arbitrary observation against a hidden ground truth,
judge free-form assertions, or establish any advantage from explicit state.

## Optional typed-inference positive-control calibration (no live model)

The v2 evidence auditor classifies optional explicit-ledger coefficient claims
against the already visible GF(11) equations. A new deterministic control,
`discovery_semantic_control.py`, extends the original baseline by emitting
exactly those coefficients established by the available observations. It reads
no hidden target. The original baseline and hosted-model prompts are unchanged.

Command parameters for each trace tree: `discovery_pilot.py --seed 1337
--count 12 --max-turns 6 --arm-seed 20261103`, with `--agent "python
/absolute/path/to/discovery_semantic_control.py"`; the faulted tree adds
`--inject-probe-failure-at 1`. Both have 12 tasks in each of the four arms.
`evidence_audit.py --expected-tasks 12` generated the certificate archives and
aggregate-only JSON summaries. `analyze_recovery.py` checked the paired fault
recovery separately. All are exploratory synthetic calibration runs.

| Metric per explicit-state arm | Control | Faulted |
|---|---:|---:|
| Scored ledger turns | 36 | 48 |
| Entailed typed coefficient claims | 108 | 132 |
| Contradicted / underdetermined / malformed / duplicate | 0 | 0 |
| Mean coverage of identifiable coefficients | 100% | 100% |
| Informative completed probes | 24/24 | 24/24 |
| Recovered transient tool failures | N/A | 12/12 |
| Extra turns vs. control | N/A | 1 per task |

Implicit arms have no ledger/inference score (**N/A**, not zero). In the
faulted regime, the repeated evidence after a failed probe yields the same
entailed inferences on the retry turn; it explains the higher count. The
control verifies that the instrument accepts genuinely justified coefficient
claims. The adversarial tests separately verify that correct guesses about
unidentified coefficients earn **no** entailment credit, and that contradictory
claims are rejected. This says nothing about live-model performance, natural-
language state, or a causal effect of explicit state.

- `reports/discovery-semantic-calibration-traces.zip` (SHA-256
  `03981daa347a7c765729715f7c7ba84baa9b61cedb53b0df115baff37fa0ac31`)
- `reports/discovery-semantic-calibration-certificates.zip` (SHA-256
  `62cb8e3c5e2c40748151880c209a6403af952e33beae135f4b99955aa0b545ea`)
- `reports/discovery-semantic-control-summary.json` (source evidence SHA-256
  `f024e8319188a236d48b3fb66616254f9a526aceda4fa6d13ef1e3a151b5afac`)
- `reports/discovery-semantic-faulted-summary.json` (source evidence SHA-256
  `0f2ea692f1161f6a0a57a3a5ba228c8612c42124e5b0d5d0af021b7434608020`)
- `reports/discovery-semantic-recovery-summary.json` (paired replay audit)

The archived ZIPs passed `unzip -tq`; the full local Python test suite passed
**65/65** at the PR #13 checkpoint on 2026-11-05. GitHub CI passed before merge.

## State-retention necessity diagnostic (no live model)

The original discovery runner delivers the **full cumulative observation set**
on every turn. It is therefore possible to recover all coefficients from the
current request alone, with no reference to the previous ledger or history.
This is a limitation of its ability to measure memory *necessity*, not a bug
in the existing benchmark. The following separately labeled diagnostic checks
whether the harness can create and audit a state-dependency boundary.

All six scenarios use 12 identical seeded tasks, four paired arms each, seed
`1337`, arm seed `20261103`, two successful probe observations per task, and
an evaluator that retains the full evidence. The projection only changes the
**model-visible** observation set and available state channel. “Latest” means
two initial observations on turn one, then only observations added since the
previous request. A retryable error does not disclose an observation.

| Model-facing scenario | K-explicit | K-implicit | Rich-explicit | Rich-implicit |
|---|---:|---:|---:|---:|
| Cumulative, state-blind control | 12/12 | 12/12 | 12/12 | 12/12 |
| Cumulative, state-carry control, history 0 | 12/12 | 12/12 | 12/12 | 12/12 |
| Latest, state-blind control | 0/12 | 0/12 | 0/12 | 0/12 |
| Latest, state-carry control, history 1 | 12/12 | 12/12 | 12/12 | 12/12 |
| Latest, state-carry control, history 0 | 12/12 | 0/12 | 12/12 | 0/12 |
| Latest, state-carry control, history 1, fault at probe 1 | 12/12 | 12/12 | 12/12 | 12/12 |

The controls choose the same probe actions and differ only in whether they
read previously returned state. The carrying control serializes observed
coordinate/value records either into the explicit `ledger.established` list
or into its latest `message` (`STATE:` followed by JSON). One retained implicit
message is enough to recursively preserve the observations through this
three-turn task. The state-blind control zero-fills unavailable values; no
task's target is read by the adapter. The fault control retries on the next
turn and completes in four turns. The independent analyzer replays every
observable window and previous-state handoff and verifies paired trace digests.

**Interpretation:** The cumulative protocol cannot make state retention
necessary for information recovery. The history-zero experiment deliberately
withholds information from implicit arms, so its 12/12 versus 0/12 gap is a
successful *positive control for the information channel*, **not** evidence
that explicit state is intrinsically better. Conversely, implicit message
recirculation can emulate state; the intervention needs an information- and
token-budget-matched design before a live causal comparison.

- Full raw request/action/feedback traces for all six scenarios:
  `reports/discovery-retention-calibration-traces.zip` (SHA-256
  `6edc633b5c63b61dc6e18da7e8b12fb856052ce165edd43b4888d2325a536a66`).
- Independent replay and scenario aggregate:
  `reports/discovery-retention-calibration-analysis.json` (SHA-256
  `82c760cff8e9256538003117e76183ee44838024b9edfd507dd81b8dcb87258f`).
- Reproduce with `discovery_retention.py --seed 1337 --count 12
  --arm-seed 20261103`, setting `--view`, `--history-window`, and
  `--inject-probe-failure-at 1` per row, and selecting either
  `discovery_retention_control.py` or `discovery_retention_blind_control.py`
  via `--agent`. Then run `analyze_retention.py ROOT --out analysis.json`.

The archive passes ZIP integrity validation and the local full suite passes
**72/72** tests. This diagnostic does not modify the original model prompts,
published pilot task schema, or earlier calibration artifacts.

## Retrospective paired-analysis smoke check

The subsequent `analyze_trial.py` implementation was also exercised against
the archived `reports/calibration-traces.zip` (`runs-v2`, 12 complete task
pairs). The evidence digest for the extracted trace tree was
`7c9c5e66a2acdf343b2db607bd3b7c963ab4e5e850bba2454401bea4cfa35c39`.
It reproduced the 2/12 completions per arm. All three paired contrast
estimates were exactly zero. The conservative Bonferroni-Hoeffding lower bounds
were `-0.8261` (H3), `-1.6521` (H4), and `-0.8261` (H5); none crossed its
decision threshold. The legacy traces lack token-usage measurements, so the
analyzer correctly reports usage as unknown. This is **still only a deterministic
plumbing check**, not a model result or a preregistered trial.

## Private-preference information-bound calibration

The third stratum holds a favorite among eight alternatives, independently of
all public information, with four proposals and up to five total turns. The
rich reviewer responds to proposals with acceptance/rejection; the `K` reviewer
always returns `K`. The theoretical success rates for an all-`K` policy and a
four-distinct-proposal rich policy are **1/8** and **5/8**, respectively.

The deterministic control ran `seed=1337`, `arm_seed=20261103`, eight tasks
covering every preferred option exactly once, and all four conditions. Both
`K` arms succeeded **1/8**; both rich arms succeeded **5/8**, with zero
protocol errors. The paired-analysis evidence-tree digest was
`783d18672adc5f50b511e333390069a7460db3554829c2722dbc88ab7b722bed`.
The complete subprocess traces and summary are archived in
`reports/preference-calibration-traces.zip` (ZIP SHA-256
`58f4690123bd6b9a7453cfa6f4d9d64d952ac90f2796b59db1f89ce625503c02`).
Reproduction commands and the separate hosted adapter are in [STRATA.md](STRATA.md).

This result establishes only the **negative-control mechanics**. An arbitrary
model that can read the public generator and its known seed can reconstruct
the calibration answers; no live model was tested, and this is not a secured
preference holdout. The private-preference feedback advantage represents
**new target information**, not increased reasoning quality. The existing H3–H5
analyzer can process these traces as a software smoke check, but those
hypotheses must not be interpreted as the same causal estimands here.

## Trusted private-preference holdout (no live model)

`preference_holdout.py` now creates a 256-bit secret and a public SHA-256
manifest commitment binding both the preference generator and the trusted
runner code. `preference_private_trial.py` uses HMAC domain separation for
pseudorandom favorites and per-arm opaque model-facing IDs, with balanced arm
order, task-interleaved dispatch, evaluator-side scoring, and measured token
caps. The live entrypoint pins the direct HTTP model/decoder configuration and
detects provider-reported model identity drift.

Five new tests validate commitment tampering, stale code, secret exclusion
from all model-facing requests and saved traces, distinct arm IDs, interleaved
dispatch, baseline scoring, non-overwriting output directories, and CLI model
identity pinning. The full local suite passes **41/41 tests**. These are
synthetic/mocked checks; no private manifest has been established for a live
model trial, and provider-side hidden state or logging remains unverified.

## Provider-isolation canary audit (mocked only)

`provider_isolation_audit.py` issues a baseline recall probe, exposes a fresh
synthetic 128-bit hex canary to an independent request, and then asks a new
request to recall it without reproducing it in the prompt. The output records
raw request/response events, model identity, reported token usage, exact-match
classification, endpoint origin, and audit-source SHA-256. A provider with
cross-request memory was simulated as a **positive control**, and its exact
canary recovery was detected. A memoryless mock yielded the intentionally
inconclusive `not_detected_in_test` classification. Unexpected unrelated recall,
missing usage, model drift, and cap overrun fail the audit protocol.

The worker checked for `KAGGLE_API_TOKEN`, `KLOOP_MODEL`, `KLOOP_API_KEY`,
`OPENAI_API_KEY`, and `KLOOP_API_URL` on 2026-11-04: none was configured, and
the Kaggle CLI was unavailable. Thus **no real provider endpoint was audited**
and no live inference was performed. The full local suite passes 46/46 tests.
