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

### Transient-tool recovery diagnostic

The discovery runner can inject exactly one synthetic, retryable failure on a
selected probe attempt, default disabled. This consumes one turn but **no**
observation or successful-probe budget. The next request receives a structured
`last_tool_error` in *both* state modes; `K` remains `K`, and the rich human
channel does not deliver the error. The usual implicit history also records it.
No hidden coefficient is disclosed by the failed probe.

```sh
python discovery_pilot.py --seed 1337 --count 12 \
  --agent "python /absolute/path/to/discovery_baseline_agent.py" \
  --out discovery-control --max-turns 6 --arm-seed 20261103
python discovery_pilot.py --seed 1337 --count 12 \
  --agent "python /absolute/path/to/discovery_baseline_agent.py" \
  --out discovery-faulted --max-turns 6 --arm-seed 20261103 \
  --inject-probe-failure-at 1
python analyze_recovery.py discovery-faulted --control discovery-control \
  --expected-tasks 12 --out discovery-recovery-analysis.json
```

The auditor checks the four-arm pairs, replayed evidence/probe-budget changes,
fault delivery, and the relation between each failure and subsequent
same-coordinate retries. It separately counts *false public success*:
submissions consistent with observed examples but wrong on hidden cases.
It rejects preference traces, where `public_pass` only means committing an
option. Its comparison to no-fault controls is descriptive. It does not prove
that a retry was appropriate for any arbitrary external error, nor that a
language model can recover. The synthetic trace archive and evidence digest
are recorded in [REPORT.md](REPORT.md).

### Independent evidence and ledger-fidelity certificates

`evidence_audit.py` derives algebraic proof obligations from each *visible*
observation, independently of the agent's interpretation. For the public
bilinear hypothesis class, each `(x,y)` observation contributes the linear row
`[x, y, x*y, 1]` over `GF(11)`. Gaussian elimination computes its coefficient
rank `r` and the augmented rank using observed values. When consistent, the
number of compatible hypotheses is exactly `11^(4-r)`; inconsistent evidence
is reported with **zero** compatible hypotheses, never silently reconciled.

For each completed probe, rank gain `1` is new independent information, while
rank gain `0` identifies a redundant probe. Failed probes supply no observation
and are excluded from the successful-probe relevance denominator. Submitting
at rank less than `4` is flagged as underidentified even if the guess happens
to pass. Rank/relevance is evaluated for all four arms.

Explicit-state ledger fidelity is deliberately narrower than "state quality":
the auditor recognizes only `established` references of form `"x,y"`,
`"x,y=value"`, or typed `{ "x": int, "y": int, "value": int }` (value optional).
It certifies references against *already visible* observations and reports
coverage, contradicted values, unsupported references, duplicate claims, and
uncertifiable prose separately. It also checks the ledger's `next_action`
label against the submitted action, which measures self-consistency only.
Free-form `falsified`, `unresolved`, `verification`, and reasoning quality are
**not** semantically certified. Implicit-state ledger metrics are **null (N/A)**,
not zero: there is no explicit ledger intervention to score in those arms.

#### Optional typed coefficient-claim certificate (auditor v2)

For experimental use, an explicit ledger may additionally contain:

```json
"inferences": [
  {"coefficient": "a", "value": 7},
  {"coefficient": "d", "value": 3}
]
```

The exact claim grammar is a JSON array of objects with **only** `coefficient`
(`a`, `b`, `c`, or `d`) and `value` (integer `0..10`, excluding booleans).
For the visible linear equations `Aθ=b` over `GF(11)`, a claim `θᵢ=v` is:

- **Entailed** iff the unit vector `eᵢ` belongs to the row span of `A` and
  appending `[eᵢ,v]` preserves augmented rank.
- **Contradicted** iff `eᵢ` is identifiable but the supplied value conflicts
  with `Aθ=b`.
- **Underdetermined** iff `eᵢ` is not identifiable, regardless of whether
  the supplied value matches the undisclosed target.

Duplicate and malformed claims receive their own classifications. Inconsistent
observations and invalid claim-list shape are explicitly unscorable. An absent
`inferences` property is **unscored, not false**; an explicitly empty array is
scored with zero claims. Identifiable-coefficient coverage is null when no
coefficient can be identified. Per-turn proof detail and aggregate rates are
included in `kloop-discovery-evidence-audit-v2` outputs. Existing v1 audits
remain immutable, and the original model prompts do **not** request this
optional field; comparisons need a separately frozen treatment protocol.

The deterministic `discovery_semantic_control.py` computes only from public
observations and serves as an instrument positive control. To reproduce the
paired calibration, run the same `discovery_pilot.py` commands above with
`--agent "python /absolute/path/to/discovery_semantic_control.py"`, then run
`evidence_audit.py` against both outputs. The complete source traces,
certificates, and summary digests are archived in `reports/` and documented in
[REPORT.md](REPORT.md). No hosted inference occurred.

### State-retention information-flow stress diagnostic (separate schema)

The original `kloop-discovery-v1` request contains **all accumulated** oracle
observations each turn. Once rank is four, those equations are sufficient for
exact coefficient recovery even if prior ledger/history are ignored. This
cannot establish the necessity of persistent state for recovering evidence.
Computational caching may still help a resource-bounded model; that is a
different, as-yet-unmeasured hypothesis.

`discovery_retention.py` introduces the explicitly separate schema
`kloop-discovery-retention-v1`. A model-facing request projection exposes:

- `--view cumulative`: the original complete observations;
- `--view latest`: all initial observations on turn one, then only observations
  newly returned by the oracle since the preceding request; an injected failed
  probe yields an empty observation list until its successful retry;
- `--history-window 0..5`: in implicit arms only, the number of most recent
  action/message/feedback records available; explicit arms receive their
  previous ledger. The evaluator **always** retains the full evidence set.

Two deterministic controls share the same actions: `discovery_retention_control.py`
retains observed coordinate/value pairs in either an explicit ledger or its
most recent assistant `message` (`STATE:` JSON). That latter message is echoed
through implicit history, enabling self-serialization without a typed ledger.
`discovery_retention_blind_control.py` ignores both incoming memory channels.

```sh
python discovery_retention.py --seed 1337 --count 12 --arm-seed 20261103 \
  --agent "python /absolute/path/to/discovery_retention_control.py" \
  --view latest --history-window 1 --out latest-onehistory
python discovery_retention.py --seed 1337 --count 12 --arm-seed 20261103 \
  --agent "python /absolute/path/to/discovery_retention_blind_control.py" \
  --view cumulative --history-window 0 --out cumulative-blind
```

`analyze_retention.py` checks complete four-arm pairing, all model-visible
observation windows, matching prior ledger/history handoffs, probe/observation
correspondence, and canonical trace-tree SHA-256 digests. The six configurations
and their hashes are in [REPORT.md](REPORT.md). The ordinary discovery runner
and its prompts retain their original behavior (`request_projection=None`).

**Causal boundary:** This stress test deliberately changes how much
information each condition can access. Its outcomes cannot be interpreted as
the effect of a structured ledger, of K-only feedback, or of model competence.
It establishes that the harness can make retained state consequential and
that implicit messages can be a functionally equivalent memory channel in
this small task. Future live trials must precommit information budgets,
channel constraints and resource-matched evaluation separately.

#### Capacity-matched semantic state channels (another separate schema)

`discovery_channel_match.py` / `discovery_channel_codec.py` establish an
**information-equivalent** version of the retention diagnostic under
`kloop-discovery-channel-matched-v1`. The public state payload is canonical
JSON `{"facts":[[x,y,value],...]}`, with sorted unique, integer-typed,
previously observed triples. Both arms carry the **identical UTF-8 payload**
under the same `--state-bytes` limit. The host permits only one carrier back:

| Explicit request | Implicit request |
|---|---|
| `ledger: {"carry": CANONICAL_JSON}` | `history: [{"message":"CARRY:" + CANONICAL_JSON}]` |
| `history: []` | `ledger: null` |

Both arms return the same response shape and bytes, containing both equivalent
carriers; only one is accessible on the next request. The host strips all
other previous-state fields, including the prior action and feedback history;
the current environmental observation and `last_tool_error` remain equally
visible. The response validator requires matching carriers and canonical
bounded payloads; the independent replay auditor checks observational support,
window projections and exact state/action/outcome parity within each feedback
condition. Ordinary discovery prompts and runner defaults are unchanged.

```sh
python discovery_channel_match.py --seed 1337 --count 12 \
  --arm-seed 20261103 --state-bytes 48 \
  --agent "python /absolute/path/to/discovery_channel_control.py" \
  --out budget48
python analyze_channel_match.py /path/to/multi-budget-parent \
  --out matched-analysis.json
```

The deterministic control greedily retains a prefix of observed facts in its
fixed canonical format; it does not optimally compress them. This makes the
observed budget threshold a **codec/control-specific result**. Exact semantic
information parity is not byte parity of the *request envelope*, which differs
by the carrier wrapper, nor model token, computation, or latency parity. No
hosted-model inference or causal comparison was performed. Six scenarios and
their complete evidence appear in [REPORT.md](REPORT.md).

```sh
python evidence_audit.py discovery-faulted --expected-tasks 12 \
  --out discovery-evidence-detail.json
python evidence_audit.py discovery-faulted --expected-tasks 12 \
  --aggregate-only --out discovery-evidence-summary.json
```

The auditor rejects malformed/non-discovery traces and uses the independent
trace replay checks from `analyze_recovery.py`. Per-turn certificates include
rank, augmented rank, pivot positions, hypothesis count, and a visible-row
matrix SHA-256. These are **public-hypothesis-class certificates**, not
proofs of observational truth, general-purpose relevance, or causal benefit
from explicit state. Calibration artifacts and hashes are in [REPORT.md](REPORT.md).

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

### Provider cross-request-memory canary

The separate `provider_isolation_audit.py` runs three independent HTTP model
calls per round: a baseline recall probe, exposure to an unimportant random
128-bit canary, and a fresh probe that **does not contain that canary**.

```sh
python provider_isolation_audit.py --rounds 4 \
  --max-total-tokens TOKEN_CAP --out provider-isolation-audit.json
```

Use the same `KLOOP_*` model settings intended for the experiment. The raw
requests, responses, observed model identity, and provider token measurements
are retained as synthetic evidence. An exact recovery is evidence of
cross-request contamination and should stop the trial. A nonmatching recall
is ambiguous. **No recovery does not establish provider/session isolation:**
the provider might selectively retain, conceal, or later expose information.
This audit cannot attest to provider-side logging or hidden retention; it is
a falsification test, not a confidentiality certification.

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
