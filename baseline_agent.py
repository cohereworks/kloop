#!/usr/bin/env python3
"""Deterministic hill-climbing protocol smoke-test; NOT an LLM agent."""

import copy
import json
import sys

from pilot import OPS, evaluate, node_at, node_paths


def score(expr, cases):
    observed = [evaluate(expr, c["x"], c["y"]) for c in cases]
    return (sum(o != c["expected"] for o, c in zip(observed, cases)),
            sum(abs(o - c["expected"]) for o, c in zip(observed, cases)))


def neighbors(expr):
    for path, node in node_paths(expr):
        if "op" in node:
            for op in OPS:
                if op != node["op"]:
                    trial = copy.deepcopy(expr)
                    node_at(trial, path)["op"] = op
                    yield trial
        elif "const" in node:
            for value in range(-8, 9):
                if value != node["const"]:
                    trial = copy.deepcopy(expr)
                    node_at(trial, path)["const"] = value
                    yield trial


def main():
    request = json.load(sys.stdin)
    candidate = request["candidate"]
    cases = request["task"]["public"]
    best, best_score = candidate, score(candidate, cases)
    for trial in neighbors(candidate):
        new_score = score(trial, cases)
        if new_score < best_score:
            best, best_score = trial, new_score
    ledger = {
        "objective": "Fit public examples with a bounded expression",
        "established": [f"Current public mismatches: {best_score[0]}"],
        "falsified": [],
        "unresolved": ["Hidden examples are not available"],
        "next_action": "Try another local edit",
        "verification": "Only public examples checked",
    }
    json.dump({"candidate": best, "ledger": ledger,
               "message": f"Greedy local step: {best_score[0]} public mismatches"}, sys.stdout)


if __name__ == "__main__":
    main()
