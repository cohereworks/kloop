# K-loop task strata

The experimental factor is the human feedback channel (`K` versus rich
review), crossed with working-state representation (implicit versus explicit).
The environment is a separate evidence channel. Conflating those channels
would make the one-bit feedback question meaningless.

| Stratum | Goal knowledge at start | New evidence source | Hidden component | Status |
|---|---|---|---|---|
| Closed specification | Public examples constrain target expression | Candidate evaluation against supplied examples | Exhaustive hidden cases | Implemented in `pilot.py` |
| Discoverable uncertainty | Two observations underdetermine function | Agent-selected `probe(x,y)` | Coefficients and unqueried outputs | Implemented in `discovery_pilot.py` |
| Private user preference | Environmental observations cannot determine preference | Acceptance/rejection from preference holder | Preference itself | Implemented in `preference_pilot.py` |

## Discoverable-uncertainty pilot

Unknown target:

`f(x,y) = (a*x + b*y + c*x*y + d) mod 11`, coefficients in `0..10`.

The task initially reveals `f(0,0)` and `f(1,0)`. These determine `d` and
`a`, but all 121 combinations of `(b,c)` remain consistent. The agent may
use up to three `probe` actions, each consuming one turn and returning a new
environmental observation. Or it may `submit` all four coefficients. A
successful submission matches the target on every point in `[-3,3]^2`.
The rich-feedback channel only comments on the *known evidence geometry*;
it never supplies target outputs or private preferences.

The two independent manipulations persist:

- `K/implicit`, `K/explicit`, `rich/implicit`, `rich/explicit`.
- Implicit arms see bounded action/history summaries; explicit arms see a
  bounded structured ledger, but not prior history.
- All four arms start with the same observations and identical probe limits.
- Balanced execution order uses a recorded deterministic schedule.

### Reproduce the negative control

```sh
python discovery_pilot.py --seed 1337 --count 12 \
  --agent "python /absolute/path/to/discovery_baseline_agent.py" \
  --out discovery-runs --max-turns 6 --arm-seed 20261103
python analyze_trial.py discovery-runs --expected-tasks 12
```

The deterministic control always probes `(0,1)` and `(1,1)` before solving.
Its success only proves the probing/evidence/action/scoring path. It cannot
support any inference about language-model reasoning or autonomy.

For authorized hosted inference with an OpenAI-compatible endpoint, substitute
`discovery_api_agent.py` as `--agent` and provide the same existing `KLOOP_*`
configuration as the expression-repair adapter. Set a measured
`--max-total-tokens` cap. No live model has been run through this stratum.

## Private-preference pilot

Eight publicly identical alternatives are indexed `0..7`; the evaluator holds
one uniformly randomized favorite that is independent of the public request.
The agent can make **up to four proposals** and then commit an option, within
a five-turn cap. In the rich arms, the holder responds `Accepted` or `Rejected`
after a proposal. In the `K` arms, every proposal elicits `K`, including
proposals that happen to name the favorite. Nothing in the environment can
disclose the preference. Both state modes have identical action budgets.

Under a uniformly random target, and with no side channel, the entire all-`K`
transcript is independent of the preference. Any decision policy therefore has
success probability exactly **1/8** (in expectation over random preferences).
With four distinct yes/no proposals, a rich-feedback policy can succeed on
the first four options, then guess one of the four remaining options: **5/8**.
This is an information-theoretic contrast, not a comparison of model skill.

### Reproduce the negative control

```sh
python preference_pilot.py --seed 1337 --count 8 \
  --agent "python /absolute/path/to/preference_baseline_agent.py" \
  --out preference-runs --max-turns 5 --arm-seed 20261103
python analyze_trial.py preference-runs --expected-tasks 8
```

The deterministic baseline proposes `0,1,2,3`, commits immediately on rich
acceptance, and otherwise commits `4`. It yields 1/8 in both `K` conditions
and 5/8 in both rich conditions over each complete block of eight preferences.
The trace archive is `reports/preference-calibration-traces.zip`. The `public_pass`
field here means the agent committed an option, **not** that the hidden
preference was satisfied; `hidden_pass` alone measures success.

To try a hosted model, use the **trusted private-preference route** below,
with the same `KLOOP_*` endpoint configuration as the other adapters and a
measured `--max-total-tokens` cap. **The public calibration generator and its
seed are reconstructable.** Never use `preference_pilot.py --seed` as a
confidential holdout for a code-aware model.

### Trusted private-preference holdout

```sh
python preference_holdout.py create \
  --private preference-holdouts/manifest.json \
  --commitment preference-holdout-commitment.json \
  --count N --repetitions R
python preference_holdout.py verify \
  --private preference-holdouts/manifest.json \
  --commitment preference-holdout-commitment.json

# Commit the public commitment to GitHub BEFORE inference; never the private file.
python preference_private_trial.py \
  --private preference-holdouts/manifest.json \
  --commitment preference-holdout-commitment.json \
  --out preference-private-runs --arm-seed 20261103 \
  --max-turns 5 --max-total-tokens TOKEN_CAP
python analyze_trial.py preference-private-runs --expected-tasks N_TIMES_R
```

Replace `N`, `R`, `TOKEN_CAP`, and `N_TIMES_R` with the independently chosen
task count, repetitions, measured cap, and their product. The uncommitted
manifest holds a 256-bit random secret. HMAC derives each favorite and an
unrelated opaque model-facing ID for every task/arm. The public commitment
binds the manifest, `preference_pilot.py`, and `preference_private_trial.py`.
The trusted process keeps all favorites evaluator-side; each model call goes
directly through the shared HTTP adapter using `preference_api_agent`'s
instructions. Arms are interleaved across tasks rather than run back-to-back;
the exact dispatch order is recorded. No arbitrary agent subprocess runs next
to the private targets.

This closes the obvious public-seed leak and removes shared task IDs from
model-facing requests, while interleaving reduces trivial timing correlation.
It is **not** a formal secrecy proof: the host, imported Python code, HTTP
provider, and its logging or hidden cross-request memory remain trusted.
Reusing one provider account can still introduce cross-arm contamination.
Treat any live run as exploratory until model/session isolation, true
independent sampling, preregistration, and budgets are verified externally.

## Limits and future comparisons

- The discovery stratum is still a toy, exactly specified hypothesis class.
  A solver that already knows the basis can choose an optimal probe sequence;
  this is an intended negative control, not a model of arbitrary diagnosis.
- The rich reviewer changes *guidance*, not target information. It does not
  answer questions the user has not been asked.
- Do not pool strata without a precommitted stratified design and analysis.
- The private-preference stratum deliberately contains information available
  only from the holder. Its all-`K` identification limit is an experimental
  boundary, not evidence of bad reasoning or deficient state management.
- The same private favorite is held across paired arms. Its answer is never
  supplied to a request, but a provider that shares hidden state between
  separate calls could still contaminate arms. An independent provider/session
  isolation check is required before interpreting paired outcomes.
