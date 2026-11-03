# K-loop work plan

Status: **mechanics verified; real-model hypothesis untested**.

## Completed

- [x] Define continuation versus endorsement and the four experimental arms.
- [x] Implement deterministic closed-world expression-repair task generator and scorer.
- [x] Persist per-turn raw requests, parsed responses, evaluation, and token-usage metadata.
- [x] Add OpenAI-compatible Chat Completions adapter with a JSON-only interface.
- [x] Enforce measured token caps; treat over-budget results as non-successes.
- [x] Test all conditions, mock HTTP inference, missing model configuration, non-HTTPS restrictions, and budget overshoot.
- [x] Record calibration results and archive complete deterministic smoke traces.
- [x] Restore the original `KAGGLE_API_TOKEN` integration requirement.
- [x] Build and mock-test a self-contained Kaggle Benchmarks task with isolated chat contexts.
- [x] Add a reusable paired four-arm H3/H4/H5 analysis, complete-pair and
      token-cap validation, conservative finite-sample decision bounds, and
      reproducible descriptive bootstrap intervals.
- [x] Add salted private-holdout manifest commitments with tamper verification.
- [x] Add seeded, positionally balanced arm scheduling and a trusted HTTP
      private-holdout runner that never gives model-facing requests targets.
- [x] Implement a separate discoverable-uncertainty stratum with finite
      probing, environmental observations, four arms, deterministic negative
      control, and compatible hosted-model adapter.

## Next, in order

1. **Exercise the intended Kaggle route**. The original README specified `KAGGLE_API_TOKEN`. A first-party Benchmarks task and manually gated GitHub Actions workflow are implemented, but require an authorized repository secret or worker token. Check available model slugs and quota; run the small exploratory task before planning confirmatory inference. The current worker has no Kaggle token or CLI.
2. **Freeze the confirmatory evaluation** after an independent live pilot. The
   [preregistration contract](PREREGISTRATION.md) and analysis/holdout tools now
   exist; sample size/power, repeats, model settings, inference budget, and
   private-holdout execution remain uncommitted. Do not reuse calibration data.
3. **Audit and harden adapter isolation**. The new in-process private runner
   uses the reviewed direct HTTP adapter and keeps hidden cases evaluator-side.
   Arbitrary local subprocess adapters remain unsandboxed by the legacy runner;
   do not use them for private confirmatory data without OS confinement.
4. **Expand task strata**. The modular-function discovery stratum is implemented
   as a separate toy pilot ([STRATA.md](STRATA.md)); next implement a genuinely
   private-preference task and explicitly characterize the all-`K` information
   limit rather than attributing impossible inference to poor reasoning.
5. **Measure capability and drift**. Add recovery after injected errors, false-success rates, state-quality measures, cost, and independent evidence/relevance certificates.
6. **Test generality** on a non-toy maintenance benchmark and compare to findings from the separate multi-agent role-isolation harness.

## Interpretive boundaries

- The deterministic solver's equal scores across arms are an expected negative control, not evidence for equivalence.
- Structured-state intervention includes a schema and behavior constraints; it does not isolate memory persistence as a causal mechanism.
- A single fixed `K` is permission to continue, not user feedback on quality. The human channel may convey no directional information across an all-`K` transcript.
- The visible task data can be identical across arms while the generated prompt lengths and effective token usage differ. Use token accounting and report both outcome and cost.
- The calibration dataset contains reference targets and cannot serve as an undisclosed benchmark once published.
- Kaggle Benchmarks may retain model conversation state by default. Start a new chat per agent turn so only explicit `history` or `ledger` fields carry state across turns.
- The present Kaggle benchmark embeds a public exploratory seed. Use the
  separate private HTTP runner with balanced arm order for confidential trials;
  a private Kaggle transport remains unimplemented.
