#!/usr/bin/env python3
"""Reproducible four-arm continuation/feedback experiment (stdlib only)."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import shlex
import subprocess
import sys
import time
from pathlib import Path

from api_agent import ModelResponseError


OPS = ("add", "sub", "mul", "min", "max")
VARIABLES = ("x", "y")
CONDITIONS = (("k", "implicit"), ("k", "explicit"),
              ("rich", "implicit"), ("rich", "explicit"))
STATE_FIELDS = ("objective", "established", "falsified", "unresolved",
                "next_action", "verification")
SCHEMA = 1
MAX_NODES = 31
MAX_STATE_CHARS = 4000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def arm_schedule(task_ids, *, mode="fixed", seed=None):
    """Assign four-arm order per task; balanced mode rotates a shuffled square.

    Every complete block of four tasks uses each arm once in each position.
    This changes execution order, not the paired evidence or scoring contract.
    """
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Task IDs must be unique")
    if mode == "fixed":
        return {task: CONDITIONS for task in task_ids}
    if mode != "balanced" or type(seed) is not int:
        raise ValueError("Balanced scheduling requires an explicit integer seed")
    rng = random.Random(seed)
    base = list(CONDITIONS)
    rng.shuffle(base)
    result = {}
    for start in range(0, len(task_ids), len(CONDITIONS)):
        rotations = list(range(len(CONDITIONS)))
        rng.shuffle(rotations)
        for task, rotation in zip(task_ids[start:start + len(CONDITIONS)], rotations):
            result[task] = tuple(base[rotation:] + base[:rotation])
    return result


def validate_expr(expr, depth=0):
    if depth > 6 or not isinstance(expr, dict):
        raise ValueError("Expression must be a bounded JSON object")
    if set(expr) == {"var"} and expr["var"] in VARIABLES:
        return 1
    if set(expr) == {"const"} and type(expr["const"]) is int and -8 <= expr["const"] <= 8:
        return 1
    if set(expr) == {"op", "args"} and expr["op"] in OPS:
        args = expr["args"]
        if isinstance(args, list) and len(args) == 2:
            count = 1 + sum(validate_expr(arg, depth + 1) for arg in args)
            if count <= MAX_NODES:
                return count
    raise ValueError("Invalid or oversized expression")


def evaluate(expr, x, y):
    if "var" in expr:
        return x if expr["var"] == "x" else y
    if "const" in expr:
        return expr["const"]
    a, b = (evaluate(arg, x, y) for arg in expr["args"])
    return {"add": lambda: a + b, "sub": lambda: a - b,
            "mul": lambda: a * b, "min": lambda: min(a, b),
            "max": lambda: max(a, b)}[expr["op"]]()


def node_paths(expr, path=()):
    yield path, expr
    if "args" in expr:
        for i, arg in enumerate(expr["args"]):
            yield from node_paths(arg, path + (i,))


def node_at(expr, path):
    for i in path:
        expr = expr["args"][i]
    return expr


def leaf(rng):
    kind = rng.choice(("x", "y", "const"))
    return {"const": rng.randint(-3, 3)} if kind == "const" else {"var": kind}


def expression(rng):
    def subtree(depth):
        if depth == 0:
            return leaf(rng)
        return {"op": rng.choice(OPS), "args": [subtree(depth - 1), subtree(depth - 1)]}
    return subtree(3)


def mutate(expr, rng):
    out = copy.deepcopy(expr)
    eligible = [(p, n) for p, n in node_paths(out) if "op" in n or "const" in n]
    path, selected = rng.choice(eligible)
    n = node_at(out, path)
    if "op" in selected:
        n["op"] = rng.choice([op for op in OPS if op != n["op"]])
    else:
        n["const"] = rng.choice([i for i in range(-3, 4) if i != n["const"]])
    return out


def mutate_distinct(expr, rng, count):
    out = copy.deepcopy(expr)
    paths = [p for p, n in node_paths(out) if "op" in n or "const" in n]
    for path in rng.sample(paths, count):
        n = node_at(out, path)
        if "op" in n:
            n["op"] = rng.choice([op for op in OPS if op != n["op"]])
        else:
            n["const"] = rng.choice([i for i in range(-3, 4) if i != n["const"]])
    return out


def make_tasks(seed, count):
    rng = random.Random(seed)
    tasks = []
    grid = [(x, y) for x in range(-5, 6) for y in range(-5, 6)]
    for index in range(count):
        for _ in range(1000):
            target = expression(rng)
            starter = mutate_distinct(target, rng, 4)
            rng.shuffle(grid)
            public_xy, hidden_xy = grid[:12], grid[12:72]
            public = [{"x": x, "y": y, "expected": evaluate(target, x, y)}
                      for x, y in public_xy]
            if sum(evaluate(starter, c["x"], c["y"]) != c["expected"]
                   for c in public) >= 6:
                break
        else:
            raise RuntimeError("Could not create discriminating task")
        tasks.append({
            "id": f"t{index:04d}",
            "spec": "Repair the expression to reproduce the intended integer function of x and y. "
                    "Use only the documented expression JSON grammar.",
            "starter": starter,
            "public": public,
            "_target": target,
            "_hidden": [{"x": x, "y": y,
                         "expected": evaluate(target, x, y)} for x, y in hidden_xy],
        })
    return {"schema": SCHEMA, "seed": seed, "tasks": tasks}


def results(expr, cases):
    return [{**c, "observed": evaluate(expr, c["x"], c["y"]),
             "pass": evaluate(expr, c["x"], c["y"]) == c["expected"]}
            for c in cases]


def rich_feedback(rows):
    failures = [r for r in rows if not r["pass"]]
    if not failures:
        return "All public examples pass; check whether the candidate generalizes."
    r = sorted(failures, key=lambda c: (abs(c["x"]) + abs(c["y"]), c["x"], c["y"]))[0]
    return (f"Review the public mismatch x={r['x']}, y={r['y']}: "
            f"expected {r['expected']}, observed {r['observed']}. "
            "Inspect a subexpression and check all public examples again.")


def request_for(task, condition, turn, candidate, ledger, history):
    feedback, state = condition
    public_rows = results(candidate, task["public"])
    # Target and hidden cases are never copied into the agent's request.
    return {
        "schema": SCHEMA, "condition": {"feedback": feedback, "state": state},
        "turn": turn,
        "task": {k: task[k] for k in ("id", "spec", "starter", "public")},
        "candidate": candidate,
        "public_evaluation": public_rows,
        "human_signal": "K" if feedback == "k" else rich_feedback(public_rows),
        "ledger": ledger if state == "explicit" else None,
        "history": history[-5:] if state == "implicit" else [],
        "limits": {"max_nodes": MAX_NODES, "max_state_chars": MAX_STATE_CHARS},
    }


def validate_response(response, request):
    if not isinstance(response, dict) or "candidate" not in response:
        raise RuntimeError("Agent response requires candidate")
    validate_expr(response["candidate"])
    message = response.get("message", "")
    if not isinstance(message, str) or len(message) > 4000:
        raise RuntimeError("Invalid message")
    if request["condition"]["state"] == "explicit":
        ledger = response.get("ledger")
        if not isinstance(ledger, dict) or not all(k in ledger for k in STATE_FIELDS):
            raise RuntimeError(f"Explicit-state response requires ledger fields {STATE_FIELDS}")
        if len(canonical(ledger)) > MAX_STATE_CHARS:
            raise RuntimeError("Ledger exceeds size limit")
    return response


def invoke_agent(command, request, cwd, timeout):
    start = time.monotonic()
    try:
        proc = subprocess.run(command, input=canonical(request), text=True,
                              capture_output=True, cwd=cwd, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Agent timed out after {timeout}s") from exc
    if proc.returncode:
        raise RuntimeError(f"Agent exit {proc.returncode}: {proc.stderr[:800]}")
    if len(proc.stdout) > 100_000:
        raise RuntimeError("Agent output exceeds 100 KB")
    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Agent returned invalid JSON: {proc.stdout[:500]}") from exc
    return validate_response(response, request), time.monotonic() - start


def run_one(task, condition, command, workdir, max_turns, timeout,
            max_total_tokens=None, adapter=None):
    workdir.mkdir(parents=True, exist_ok=True)
    candidate, ledger, history = copy.deepcopy(task["starter"]), None, []
    records = []
    error = None
    token_counts = []
    capped_usage = []
    budget_exhausted = False
    for turn in range(1, max_turns + 1):
        req = request_for(task, condition, turn, candidate, ledger, history)
        call_usage, error_metrics = None, None
        try:
            if adapter is None:
                response, duration = invoke_agent(command, req, workdir, timeout)
            else:
                start = time.monotonic()
                response = adapter(req)
                error_metrics = (response.get("metrics")
                                 if isinstance(response, dict) else None)
                candidate_count = (error_metrics.get("total_tokens")
                                   if isinstance(error_metrics, dict) else None)
                if type(candidate_count) is int and candidate_count >= 0:
                    call_usage = candidate_count
                response = validate_response(response, req)
                duration = time.monotonic() - start
            metrics = response.get("metrics")
            token_count = (metrics.get("total_tokens")
                           if isinstance(metrics, dict) else None)
            if type(token_count) is int and token_count >= 0:
                token_counts.append(token_count)
                call_usage = token_count
            elif max_total_tokens is not None:
                raise RuntimeError("Token budget requires adapter metrics.total_tokens")
            candidate = response["candidate"]
            if condition[1] == "explicit":
                ledger = response["ledger"]
            public_result = results(candidate, task["public"])
            public_pass = all(r["pass"] for r in public_result)
            history.append({"turn": turn, "candidate": candidate,
                            "message": response.get("message", ""),
                            "public_failures": sum(not r["pass"] for r in public_result)})
            records.append({"request": req, "response": response,
                            "seconds": round(duration, 4), "public_pass": public_pass})
            if max_total_tokens is not None and sum(token_counts) >= max_total_tokens:
                budget_exhausted = True
                break
            if public_pass:
                break
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, ModelResponseError):
                error_metrics = exc.metrics if isinstance(exc.metrics, dict) else None
                count = (error_metrics.get("total_tokens")
                         if isinstance(error_metrics, dict) else None)
                if type(count) is int and count >= 0:
                    call_usage = count
            error = str(exc)
            event = {"request": req, "error": error}
            if max_total_tokens is not None and isinstance(error_metrics, dict):
                event["error_metrics"] = error_metrics
            records.append(event)
            if (max_total_tokens is not None and
                    sum(token_counts) + (call_usage or 0) >= max_total_tokens):
                budget_exhausted = True
            break
        finally:
            if max_total_tokens is not None:
                capped_usage.append(call_usage)
    hidden_rows = results(candidate, task["_hidden"])
    final_public_pass = all(r["pass"] for r in results(candidate, task["public"]))
    known_subtotal = sum(v for v in capped_usage if v is not None)
    fully_metered = bool(capped_usage) and all(v is not None for v in capped_usage)
    within_budget = (True if max_total_tokens is None else
                     False if known_subtotal > max_total_tokens else
                     None if not fully_metered else True)
    result = {
        "task": task["id"], "condition": f"{condition[0]}_{condition[1]}",
        "turns": len(records), "public_pass": final_public_pass,
        "hidden_pass": (error is None and final_public_pass and
                        all(r["pass"] for r in hidden_rows) and within_budget is True),
        "hidden_failures": sum(not r["pass"] for r in hidden_rows),
        "error": error, "trace": records, "budget_exhausted": budget_exhausted,
        "within_budget": within_budget,
        "total_tokens": (known_subtotal if fully_metered else None)
        if max_total_tokens is not None else
        (sum(token_counts) if len(token_counts) ==
         sum("response" in r for r in records) else None),
    }
    if max_total_tokens is not None:
        result["reported_token_lower_bound"] = known_subtotal
    return result


def aggregate(runs):
    out = {}
    for condition in CONDITIONS:
        name = f"{condition[0]}_{condition[1]}"
        selected = [r for r in runs if r["condition"] == name]
        n = len(selected)
        out[name] = {
            "n": n,
            "successes": sum(r["hidden_pass"] for r in selected),
            "success_rate": sum(r["hidden_pass"] for r in selected) / n if n else None,
            "public_passes": sum(r["public_pass"] for r in selected),
            "errors": sum(r["error"] is not None for r in selected),
            "average_turns": sum(r["turns"] for r in selected) / n if n else None,
            "total_tokens": sum(r["total_tokens"] for r in selected)
            if selected and all(r["total_tokens"] is not None for r in selected) else None,
        }
    return out


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Create deterministic benchmark tasks")
    gen.add_argument("--seed", type=int, default=1337)
    gen.add_argument("--count", type=int, default=24)
    gen.add_argument("--out", type=Path, default=Path("tasks.json"))
    run = sub.add_parser("run", help="Run all four conditions")
    run.add_argument("--tasks", type=Path, default=Path("tasks.json"))
    run.add_argument("--out", type=Path, default=Path("runs"))
    run.add_argument("--agent", required=True, help="Agent command (JSON stdin/stdout)")
    run.add_argument("--max-turns", type=int, default=6)
    run.add_argument("--timeout", type=float, default=30)
    run.add_argument("--max-total-tokens", type=int, default=None,
                     help="Measured tokens per task/condition; adapter must return usage")
    run.add_argument("--arm-order", choices=("fixed", "balanced"), default="fixed")
    run.add_argument("--arm-seed", type=int,
                     help="Required for balanced task-block scheduling")
    args = parser.parse_args(argv)
    if args.command == "generate":
        if not 1 <= args.count <= 1000:
            parser.error("count must be 1..1000")
        data = make_tasks(args.seed, args.count)
        write_json(args.out, data)
        print(f"Wrote {len(data['tasks'])} tasks to {args.out}")
        return 0
    if not 1 <= args.max_turns <= 100 or not 0 < args.timeout <= 3600:
        parser.error("invalid resource limits")
    if args.max_total_tokens is not None and args.max_total_tokens < 1:
        parser.error("max-total-tokens must be positive")
    data = json.loads(args.tasks.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA or not isinstance(data.get("tasks"), list):
        parser.error("invalid dataset schema")
    command = shlex.split(args.agent)
    if not command:
        parser.error("empty agent command")
    runs = []
    try:
        schedule = arm_schedule([task["id"] for task in data["tasks"]],
                                mode=args.arm_order, seed=args.arm_seed)
    except ValueError as exc:
        parser.error(str(exc))
    for task in data["tasks"]:
        validate_expr(task["starter"])
        validate_expr(task["_target"])
        for condition in schedule[task["id"]]:
            run_path = args.out / task["id"] / f"{condition[0]}_{condition[1]}"
            if run_path.exists() and any(run_path.iterdir()):
                parser.error(f"Run directory not empty (use a fresh --out): {run_path}")
            result = run_one(task, condition, command, run_path, args.max_turns,
                             args.timeout, args.max_total_tokens)
            runs.append(result)
            write_json(run_path / "trace.json", result)
            print(f"{task['id']} {result['condition']}: hidden_pass={result['hidden_pass']}")
    summary = {
        "schema": SCHEMA, "task_file_sha256": hashlib.sha256(args.tasks.read_bytes()).hexdigest(),
        "agent_command": command, "max_turns": args.max_turns,
        "max_total_tokens": args.max_total_tokens,
        "arm_order": args.arm_order, "arm_seed": args.arm_seed,
        "execution_schedule": {task: [f"{a}_{b}" for a, b in order]
                               for task, order in schedule.items()},
        "conditions": aggregate(runs),
        "warning": "No causal inference from a smoke-test adapter; this records protocol mechanics only.",
    }
    write_json(args.out / "summary.json", summary)
    print(json.dumps(summary["conditions"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
