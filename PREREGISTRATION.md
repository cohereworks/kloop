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
should be randomized and recorded; the current pilot runner uses fixed order
and therefore needs modification before a confirmatory run.

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
yet a private-holdout transport. A confirmatory executor must prevent task
seeds/reference answers from reaching the model or a public task artifact.

## Analysis and audit

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
4. Implement an isolated private-holdout execution path and randomized arm
   scheduling. Validate that untrusted model/tool contexts cannot read targets.
5. Commit the public holdout commitment and preregistration **before** any
   confirmatory outcomes; preserve an immutable run/analysis provenance chain.

The statistical contract is implementable today. The experiment is not yet
statistically or operationally ready to claim causality or noninferiority.
