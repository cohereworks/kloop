#!/usr/bin/env python3
"""Second CPU protocol-adequacy check; intentionally NOT a causal trial.

Preserves the first SmolLM evidence and uses the same canonical evaluator.
Changes model, output budget and prompt framing together, so DO NOT compare
performance against the SmolLM run as though it were a controlled contrast.
"""

from pathlib import Path

from cpu_openweight_pilot import execute, load_generator

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"


def strict_prompt(generator):
    def generate(system, user):
        instructions = (system + "\n\nIMPORTANT OUTPUT CONTRACT: Reply with a SINGLE JSON "
                        "object containing ONLY 'candidate', 'message', and 'ledger'. "
                        "Do not copy REQUEST_JSON. 'candidate' must be a complete expression "
                        "tree. For the explicit-state arm, 'ledger' must be an object containing "
                        "objective, established, falsified, unresolved, next_action, verification. "
                        "No Markdown. No surrounding commentary.")
        return generator(instructions, "REQUEST_JSON follows:\n" + user +
                         "\nEND REQUEST_JSON. Now give only your response object.")
    return generate


def main():
    generate = strict_prompt(load_generator(MODEL, REVISION, max_new_tokens=512))
    execute(Path("cpu-pilot-qwen-results"), model_id=MODEL, revision=REVISION,
            generate=generate, count=1, max_turns=2, cap=12000)


if __name__ == "__main__":
    main()
