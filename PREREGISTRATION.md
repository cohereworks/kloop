# K-loop confirmatory trial contract (draft; not frozen)

This is the proposed analysis and holdout mechanism for issue #3. **It is not
a completed preregistration.** The actual model, task count, repetitions,
budget, and independently recorded code/manifest commitments remain unset.
No confirmatory run is authorized by this file.

## Experimental unit and hypotheses

Use a **paired task instance** as the unit: the same generated task is presented
once to each of the four arms, all with the same model, decoding parameters,
tools, public evidence, and nominal turn/token limits. If a task is repeated,
its repetition has a unique ID and its four arms remain together. Arm order
is randomized and recorded. `pilot.py` supports seeded balanced rotation per
four-task block; `private_trial.py` uses it by default.

Define binary hidden-test completion indicators:

- `A = K/implicit`, `B = K/explicit`, `C = rich/implicit`, `D = rich/explicit`.
- **H3**: `mean(B - A) > 0` — K-only benefit of explicit state.
- **H4**: `mean((C - A) - (D - B)) > 0` — explicit state reduces the
  rich-feedback advantage.
- **H5**: `mean(B - D) > -0.10` — K/explicit is noninferior to rich/explicit
  with an absolute ten-percentage-point margin.

All three are in one family, with family-wise one-sided alpha `0.05`.
The decision rule is a conservative one-sided **Hoeffding lower confidence
bound**, with Bonferroni per-test alpha `0.05/3`. The per-task contrast ranges
are `[-1,1]` for H3/H5 and `[-2,2]` for H4, yielding the lower bound
`mean - range_width * sqrt(log(3/0.05)/(2*N))`. This avoids spurious zero-width
inferential intervals when observed outcomes are identical. It assumes
independent bounded task units; the confirmatory generator must establish an
appropriate independent sampling design rather than assume sequential output
from a single PRNG seed proves independence.

The standardized analysis implementation is `analyze_trial.py`. It also
reports descriptive paired-task percentile bootstrap 95% two-sided intervals
(20,000 resamples, RNG seed `20261103`), which are **not** the decision rule.
A claim passes its precommitted test only when its adjusted Hoeffding lower
bound exceeds its threshold. The conservative method may demand a large task
count; power and sensitivity must be assessed on an **independent exploratory**
run before freezing this design.

## Holdout commitment

The calibration files in this repository are public and ineligible as private
holdouts. Once sample size is justified and the implementation is frozen:

```sh
python holdout_commitment.py create \
  --private private-holdouts/manifest.json \
  --commitment holdout-commitment.json \
  --count N --repetitions R
python holdout_commitment.py verify \
  --private private-holdouts/manifest.json \
  --commitment holdout-commitment.json
```

`N` and `R` are placeholders requiring an explicit power/cost decision. The
private manifest contains a cryptographically random seed and 256-bit nonce;
the public JSON contains their salted SHA-256 commitment and the generator's
SHA-256. **Commit the public file to GitHub and record the immutable commit SHA
before inference. Never commit the private file.** Reveal it after the run to
verify the commitment and regenerate the task set. This script does not itself
prove the *time* of commitment; GitHub commit history supplies that evidence.

The current Kaggle task deliberately uses a public exploratory seed; it is not
a private-holdout transport. The separate `private_trial.py` executor validates
the manifest/commitment pair, derives per-task pseudorandom streams with HMAC,
holds reference answers in its trusted evaluator, and sends only public
requests through the reviewed `api_agent.call_model()` HTTPS adapter. It does
not start a model-controlled subprocess, and no hidden target file is created.
This is a logical network boundary, **not** an OS sandbox for arbitrary
imported dependencies or a formally proved confidentiality guarantee. The
live CLI pins the endpoint/decoder configuration once and detects drift in
provider-reported model identity across turns.

For the private-preference stratum there is a distinct
`preference_holdout.py`/`preference_private_trial.py` pair. Its public
commitment also binds the private-preference runner source hash; the model sees
arm-specific pseudonymous IDs and no preference secret. The rich-feedback
channel *supplies new target information*, unlike the guidance-only rich
feedback of the closed-specification and discovery strata. Consequently H4/H5
cannot be interpreted as the same state/guidance causal effects on preferences.
This stratum needs its own precommitted estimands and power design. A provider
with cross-call memory is still an uncontrolled potential contamination channel.
The optional `provider_isolation_audit.py` probes this channel with synthetic
128-bit canaries before a live preference trial. Exact recall is a stop signal;
absence of recall does **not** establish isolation. Preserve all raw audit
traces and the model/endpoint settings for independent review.

## Analysis and audit

The separate exploratory discovery diagnostic `analyze_recovery.py` adds
trace-replayed retry and hidden-recovery rates after a single synthetic
retryable probe failure, false-public-success counts, and optional per-arm
turn deltas against a matched no-fault control. These are **not** registered
confirmatory estimands; the injection schedule, error taxonomy, sample size,
decision rule, and cost treatment must be committed before live model testing.
The private-preference stratum is excluded because its `public_pass` means
commitment, not observation consistency.
The separate `evidence_audit.py` adds exploratory rank-gain, hypothesis-count,
underidentified-submission, observation-consistency, and explicit-ledger
reference-fidelity measures. All are deterministic under the discovery
stratum's **known** finite-field hypothesis class; they are not proxies for
unrestricted relevance, semantic state quality, or causal state persistence.
The discovery auditor v2 has now fixed an **optional exploratory** typed
coefficient-claim grammar in [STRATA.md](STRATA.md). It independently checks
entailment against visible finite-field equations, with absent claims unscored
and implicit arms N/A. The original model prompts do not request these claims.
A future controlled live treatment must freeze the new prompt, field format,
scoring inclusion criteria, primary estimand, and budget **before inference**;
the synthetic positive control cannot retroactively preregister that trial.
The later retention stress diagnostic is also exploratory. It manipulates
model-facing evidence visibility and implicit-history capacity, deliberately
changing what information is recoverable. A live study cannot treat that
as a balanced ledger-versus-no-ledger treatment without a new frozen causal
design, matched information access, and independent confirmatory tasks.
The subsequent matched-channel deterministic control demonstrates exact
equality of canonical state contents and outgoing responses under fixed byte
ceilings. This is **not** an empirical comparison of language models or a
replacement preregistration: transport overhead remains unequal, and a future
trial requires common prompts, model/version pinning, token-accounted budgets,
randomized independent holdouts and a frozen estimand before inference.

The analyzer accepts a Kaggle JSON artifact with `runs`, or a local runner
directory of `task/condition/trace.json` files:

```sh
python analyze_trial.py kaggle-results/kloop-kaggle-results.json \
  --holdout-commitment holdout-commitment.json \
  --max-tokens-per-run TOKEN_CAP \
  --out trial-analysis.json
```

- Reject duplicate arms, absent arms, non-boolean outcomes, and entire missing
  task instances (via expected count from the commitment).
- Count model/protocol errors as failures; do not silently discard them.
- Record raw successes separately from successes disqualified for exceeding
  the precommitted per-run measured token cap. Unknown usage with an active cap
  is an error, not a zero or an assumed comparable outcome.
- Preserve all traces, failed runs, environment results, usage, model identity,
  exact prompt adapter and decoder configuration, seeds, run IDs, timestamps,
  and SHA-256 of the input evidence.
- An analysis output is **always marked exploratory** by the tool. A future
  external audit of preregistration, holdout, execution, and budget parity is
  required before interpreting a threshold crossing as confirmatory.

## Decisions still required before locking

1. Execute the small, independent live-model calibration; observe model
   availability, cost, case difficulty, and paired-discordance/contrast variance.
2. Choose `N`, `R`, a minimum detectable effect/power target, and a total
   inference quota based on that independent pilot. Current quota is unknown.
3. Freeze model identity/version, all inference settings, per-run cap, max
   turns, code commit, analysis settings, task strata, and arm-order policy.
4. Audit the in-process private-holdout executor and its dependency/host trust
   boundary. Extend OS isolation if arbitrary external adapters are allowed.
5. Commit the public holdout commitment and preregistration **before** any
   confirmatory outcomes; preserve an immutable run/analysis provenance chain.

The statistical contract is implementable today. The experiment is not yet
statistically or operationally ready to claim causality or noninferiority.
