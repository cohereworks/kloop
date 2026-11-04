# K-loop pilot: protocol v0.1

Status: **engineering pilot, not an empirical result**. The protocol below was fixed before any real-model trials. The bundled `baseline_agent.py` is a deterministic smoke-test adapter; its output must never be presented as LLM evidence.

## Question

Can structured working state reduce the performance gap between `K`-only human continuation and rich human-style feedback, with the task specification, tools, environmental evidence, model, and compute budget held fixed?

## Experimental factors

| Arm | Human feedback | State intervention |
|---|---|---|
| A | K-only | Implicit transcript |
| B | K-only | Explicit ledger |
| C | Rich textual review | Implicit transcript |
| D | Rich textual review | Explicit ledger |

The task/environment channel is **not** one-bit: all arms receive identical public examples and candidate evaluations. The rich textual reviewer summarizes an already visible public failure; it introduces no new data. Accordingly, the intervention measures guidance/reformatting, not access to private information.

The explicit-state intervention includes behavioral constraints and a different representation. It does not isolate memory persistence alone. Both modes are capped, but equal byte limits do not guarantee equal token budgets. A rigorous later trial should record token counts and normalize inference budgets externally.

## Task environment

- Pure bounded JSON expression DSL: integer variables `x` and `y`, bounded constants, and `add`, `sub`, `mul`, `min`, `max`.
- Seeded depth-three target expression; starter expression has four mutations at distinct nodes (tasks without at least six public mismatches are rejected).
- 12 public and 60 hidden input-output cases, sampled reproducibly.
- Candidate programs are interpreted without executing generated code.
- Each run starts from the same starter expression and receives at most six turns by default.
- Hidden cases and target AST are excluded from agent messages; hidden tests evaluate final candidates only.
- Public passing is the stopping criterion. Success requires both public passing and passing all hidden cases.
- Reruns must use a fresh output directory; the runner rejects existing nonempty per-arm directories rather than mixing traces.
- Real-model adapters must report token usage when a measured per-arm token cap is enabled. A run exceeding its cap is not counted as successful.

This is a **protocol plumbing benchmark**, not representative software maintenance. Its small grammar and local mutation structure make it susceptible to search strategies unrelated to general agent reasoning.

A separate [discoverable-uncertainty stratum](STRATA.md) now tests whether
agents can elect to obtain additional environmental evidence through probes.
It is separately scored; results must not be pooled into the original pilot's
preregistered-candidate contrasts without an explicit stratified design.

The [private-preference stratum](STRATA.md) tests a different regime: the
user's private goal cannot be inferred from public observations. Rich feedback
in this stratum *does* disclose preference information, so its all-`K` versus
rich contrast is not a clean measure of guidance or state quality. It must be
analyzed separately, and public synthetic tasks are not private holdouts.
The distinct `preference_private_trial.py` route seals a 256-bit evaluator
secret in a precommitted private manifest, binds both task and runner code
hashes, and exposes unique opaque identifiers to each arm. It uses only the
reviewed in-process HTTP adapter, not a local agent subprocess. Session or
provider-level cross-call memory is **not** proven absent.
`provider_isolation_audit.py` is a black-box attempt to falsify isolation by
testing for exact recall of random canaries in otherwise independent requests.
Negative outcomes cannot prove noninterference; a provider may retain data
without exposing it to this probe.

## Hypotheses to test with a real model

- H3: `P(K, explicit) > P(K, implicit)`.
- H4: `(P(rich, implicit) - P(K, implicit)) > (P(rich, explicit) - P(K, explicit))`.
- H5: On fully specified tasks, `P(K, explicit) >= P(rich, explicit) - 0.10` (provisional noninferiority margin).

The pilot has no power analysis. No significance or equivalence claim should be made from a handful of examples. Later trials should preregister sample size, seed list, trial repetitions, expected effect, confidence interval method, cost budget, and real-model version before execution.

## Primary outcome and audit

Primary: fraction of paired tasks for which the final candidate passes every hidden test, with public passing as a separate reported outcome.

Secondary: average turns, protocol errors, public/hidden discrepancy, inference cost (where an adapter exposes it), and trace-level recovery after failed tests.

All requests, responses, reported errors, provider-reported usage (if available), and public outcomes are recorded in per-run `trace.json`; `summary.json` includes dataset SHA-256. Externally visible inputs and scored outputs are separate. This pilot does **not** sandbox the external agent command or prove that an adapter refrains from reading the dataset through other paths; production evaluation should run agents in an isolated environment without filesystem access to hidden targets. The bundled API adapter sends only the projected public task/request fields to the remote model.

## Confirmatory analysis addendum (not yet preregistered)

The mechanics for complete-pair validation, H3/H4/H5 contrasts, adjusted
one-sided conservative Hoeffding lower bounds, descriptive paired bootstrap
intervals, usage-cap disqualification, and salted
holdout commitments are documented in [PREREGISTRATION.md](PREREGISTRATION.md)
and implemented by `analyze_trial.py` and `holdout_commitment.py`.

This addendum does **not** retroactively preregister the published calibration
trials, nor does it authorize labeling a future Kaggle exploratory run
confirmatory. It still requires a frozen sample size/power calculation,
model/version/budget controls, and an independently audited trust boundary
before any confirmatory outcomes are observed. The subsequent `private_trial.py`
provides deterministic HMAC-derived private task streams, a reviewed HTTP-only
model channel, and balanced arm scheduling. That route has been mock-tested,
but not audited or run against a live model.

## Interpretation rules

1. A smoke-test run demonstrates operational correctness only, never a model-capability result.
2. `K` means permission to continue, not praise, correctness, or preference endorsement.
3. Verification of generated expressions is conditional on the benchmark evaluator and tests.
4. Do not extrapolate a closed-DSL result to open-ended work or hidden user preferences.
5. Preserve null results and protocol failures, including runs with no improvements.
