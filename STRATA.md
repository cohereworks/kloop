# K-loop task strata

The experimental factor is the human feedback channel (`K` versus rich
review), crossed with working-state representation (implicit versus explicit).
The environment is a separate evidence channel. Conflating those channels
would make the one-bit feedback question meaningless.

| Stratum | Goal knowledge at start | New evidence source | Hidden component | Status |
|---|---|---|---|---|
| Closed specification | Public examples constrain target expression | Candidate evaluation against supplied examples | Exhaustive hidden cases | Implemented in `pilot.py` |
| Discoverable uncertainty | Two observations underdetermine function | Agent-selected `probe(x,y)` | Coefficients and unqueried outputs | Implemented in `discovery_pilot.py` |
| Private user preference | Environmental observations cannot determine preference | Directional feedback from preference holder | Preference itself | **Not implemented** |

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

## Limits and future comparisons

- The discovery stratum is still a toy, exactly specified hypothesis class.
  A solver that already knows the basis can choose an optimal probe sequence;
  this is an intended negative control, not a model of arbitrary diagnosis.
- The rich reviewer changes *guidance*, not target information. It does not
  answer questions the user has not been asked.
- Do not pool strata without a precommitted stratified design and analysis.
- A future private-preference stratum must deliberately separate recoverable
  environmental evidence from information only the preference holder can
  reveal. Under all-`K` feedback it may be information-theoretically impossible
  to identify the preferred outcome; that failure must not be mislabeled as
  poor reasoning.
