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

## Next, in order

1. **Establish a real inference endpoint**. Use the same named model, fixed settings, max turns, and token cap across all four arms. The current worker has no configured provider API credential or local model CLI.
2. **Fix the confirmatory evaluation protocol**. Set sample size, seed commitment, run repetitions, and confidence interval method before evaluating a model; do not reuse the public calibration set as a hidden holdout.
3. **Harden adapter isolation**. A trusted HTTP adapter sends only public task fields, but arbitrary local adapters are not sandboxed by the runner. Run untrusted adapters in a real container or other constrained process environment.
4. **Expand task strata**. Add discoverable uncertainty and private-preference tasks as distinct strata; the current DSL represents only closed-specification work.
5. **Measure capability and drift**. Add recovery after injected errors, false-success rates, state-quality measures, cost, and independent evidence/relevance certificates.
6. **Test generality** on a non-toy maintenance benchmark and compare to findings from the separate multi-agent role-isolation harness.

## Interpretive boundaries

- The deterministic solver's equal scores across arms are an expected negative control, not evidence for equivalence.
- Structured-state intervention includes a schema and behavior constraints; it does not isolate memory persistence as a causal mechanism.
- A single fixed `K` is permission to continue, not user feedback on quality. The human channel may convey no directional information across an all-`K` transcript.
- The visible task data can be identical across arms while the generated prompt lengths and effective token usage differ. Use token accounting and report both outcome and cost.
- The calibration dataset contains reference targets and cannot serve as an undisclosed benchmark once published.
