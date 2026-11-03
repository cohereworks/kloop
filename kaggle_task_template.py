"""This template is appended to the canonical core by build_kaggle_task.py.

Do not upload the template directly; build the self-contained task instead.
"""

import os

import kaggle_benchmarks as kbench


KAGGLE_INSTRUCTIONS = """You repair a bounded integer expression represented as JSON.
Return one valid JSON object with 'candidate' (full expression AST), 'message', and,
for explicit-state conditions, 'ledger' containing objective, established, falsified,
unresolved, next_action, and verification. No Markdown or extra commentary.
The task supplies public input/output examples and candidate evaluations. You cannot
inspect hidden cases. Treat K as permission to continue, not evidence of correctness.
Use only the grammar described in the task. Do not infer success from K.
"""

USAGE_FIELDS = ("input_tokens", "output_tokens", "input_tokens_cost_nanodollars",
                "output_tokens_cost_nanodollars", "total_backend_latency_ms")


def kaggle_run_one(task, condition, llm, kbench_api, max_turns=4):
    candidate = copy.deepcopy(task["starter"])
    history = []
    ledger = None
    error = None
    turns = 0
    trace = []
    token_totals = []
    for turn in range(1, max_turns + 1):
        turns = turn
        request = request_for(task, condition, turn, candidate, ledger, history)
        prompt = KAGGLE_INSTRUCTIONS + "\n\nREQUEST_JSON:\n" + canonical(request)
        try:
            # Critical: Kaggle retains chat history by default. Reset per turn,
            # so only the protocol's explicit history/ledger can carry state.
            with kbench_api.chats.new(f"kloop_{task['id']}_{condition[0]}_{condition[1]}_{turn}") as chat:
                raw = llm.prompt(prompt)
                chat_usage = getattr(chat, "usage", None)
                usage = {field: getattr(chat_usage, field, None) for field in USAGE_FIELDS}
            if (type(usage["input_tokens"]) is int and
                    type(usage["output_tokens"]) is int):
                token_totals.append(usage["input_tokens"] + usage["output_tokens"])
            trace.append({"turn": turn, "request": request, "raw_response": str(raw),
                          "usage": usage})
            response = json.loads(str(raw))
            if not isinstance(response, dict):
                raise ValueError("Response must be a JSON object")
            proposed = response["candidate"]
            validate_expr(proposed)
            if condition[1] == "explicit":
                updated_ledger = response.get("ledger")
                if (not isinstance(updated_ledger, dict) or
                        any(field not in updated_ledger for field in STATE_FIELDS) or
                        len(canonical(updated_ledger)) > MAX_STATE_CHARS):
                    raise ValueError("Invalid explicit-state ledger")
                ledger = updated_ledger
            candidate = proposed
            public_rows = results(candidate, task["public"])
            trace[-1]["public_pass"] = all(x["pass"] for x in public_rows)
            history.append({"turn": turn, "candidate": candidate,
                            "message": response.get("message", ""),
                            "public_failures": sum(not x["pass"] for x in public_rows)})
            if all(x["pass"] for x in public_rows):
                break
        except (ValueError, KeyError, TypeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if trace and trace[-1]["turn"] == turn:
                trace[-1]["error"] = error
            break
    final_public = all(x["pass"] for x in results(candidate, task["public"]))
    final_hidden = all(x["pass"] for x in results(candidate, task["_hidden"]))
    return {"task": task["id"], "condition": f"{condition[0]}_{condition[1]}",
            "turns": turns, "public_pass": final_public,
            "hidden_pass": final_public and final_hidden and error is None,
            "error": error, "trace": trace,
            "total_tokens": sum(token_totals) if len(token_totals) == turns else None}


@kbench.task(name="kloop-pilot")
def kloop_benchmark(llm, seed: int = 1337, count: int = 1,
                    max_turns: int = 4) -> float:
    """Exploratory four-arm continuation experiment with deterministic scoring."""
    if not 1 <= count <= 24 or not 1 <= max_turns <= 10:
        raise ValueError("Exploratory Kaggle limits exceeded")
    tasks = make_tasks(seed, count)["tasks"]
    runs = []
    for task in tasks:
        for condition in CONDITIONS:
            runs.append(kaggle_run_one(task, condition, llm, kbench, max_turns))
    summary = {"schema": SCHEMA, "seed": seed, "task_count": count,
               "max_turns": max_turns, "conditions": aggregate(runs),
               "runs": runs,
               "interpretation": "Exploratory only; per-arm token-cost parity not enforced"}
    output_root = Path(os.environ.get("KLOOP_OUTPUT_DIR", "/kaggle/working"))
    if not output_root.is_dir():
        output_root = Path.cwd()
    write_json(output_root / "kloop-kaggle-results.json", summary)
    print("KLOOP_SUMMARY=" + canonical(summary["conditions"]))
    return sum(item["hidden_pass"] for item in runs) / len(runs)


if __name__ == "__main__":
    # Initial calibration stays deliberately small to avoid accidental spend.
    kloop_benchmark.run(llm=kbench.llm, seed=1337, count=1, max_turns=4)
