#!/usr/bin/env python3
"""OpenAI-compatible Chat Completions adapter (no third-party dependencies)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


INSTRUCTIONS = """You repair a small integer expression represented as JSON.
Return exactly one JSON object, not Markdown. Include:
- candidate: a complete expression AST using only var, const, op, args as described by the task.
- message: a brief account of what you changed and why.
- ledger: when the condition's state is explicit, an object with objective, established,
  falsified, unresolved, next_action, verification. Keep it compact and factual.
Your input includes public examples and evaluations. You cannot inspect hidden cases.
Treat K as permission to continue, not endorsement or correctness feedback.
Do not claim public results prove hidden correctness. Repair the candidate incrementally.
"""


def integer_env(name, default):
    raw = os.environ.get(name)
    value = int(raw) if raw is not None else default
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def configuration():
    model = os.environ.get("KLOOP_MODEL")
    if not model:
        raise ValueError("KLOOP_MODEL must name the model; no implicit selection")
    url = os.environ.get("KLOOP_API_URL", "https://api.openai.com/v1/chat/completions")
    parsed = urllib.parse.urlsplit(url)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if not (parsed.scheme == "https" or (parsed.scheme == "http" and loopback)):
        raise ValueError("API URL must use HTTPS (HTTP permitted only for loopback tests)")
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Invalid API URL")
    key = os.environ.get("KLOOP_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key and not loopback:
        raise ValueError("KLOOP_API_KEY or OPENAI_API_KEY is required")
    params = {"model": model, "max_completion_tokens": integer_env("KLOOP_MAX_COMPLETION_TOKENS", 1600)}
    temperature = os.environ.get("KLOOP_TEMPERATURE")
    if temperature is not None:
        params["temperature"] = float(temperature)
    seed = os.environ.get("KLOOP_SEED")
    if seed is not None:
        params["seed"] = int(seed)
    json_mode = os.environ.get("KLOOP_JSON_MODE", "1") == "1"
    if json_mode:
        params["response_format"] = {"type": "json_object"}
    return url, key, params, integer_env("KLOOP_HTTP_TIMEOUT", 60)


def call_model(request, *, resolved_config=None):
    # Private trials pin the full endpoint/decoder configuration at startup.
    url, key, params, timeout = (configuration() if resolved_config is None
                                 else resolved_config)
    payload = {**params, "messages": [
        {"role": "developer", "content": INSTRUCTIONS},
        {"role": "user", "content": json.dumps(request, sort_keys=True, ensure_ascii=False)},
    ]}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    http_request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as reply:
            raw = reply.read(1_000_001)
    except urllib.error.HTTPError as exc:
        # Do not print response bodies: providers may include sensitive echoes.
        raise RuntimeError(f"Model endpoint returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Model endpoint unavailable: {type(exc.reason).__name__}") from exc
    if len(raw) > 1_000_000:
        raise RuntimeError("Model endpoint response exceeds 1 MB")
    envelope = json.loads(raw)
    choice = envelope["choices"][0]
    content = choice["message"]["content"]
    if not isinstance(content, str):
        raise RuntimeError("Model message content must be a JSON string")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise RuntimeError("Model must return a JSON object")
    usage = envelope.get("usage") or {}
    result["metrics"] = {
        "provider_response_id": envelope.get("id"),
        "model": envelope.get("model", params["model"]),
        "finish_reason": choice.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "requested_max_completion_tokens": params["max_completion_tokens"],
        "requested_seed": params.get("seed"),
        "requested_temperature": params.get("temperature"),
    }
    return result


def main():
    try:
        request = json.load(sys.stdin)
        json.dump(call_model(request), sys.stdout)
        sys.stdout.write("\n")
    except (ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
        print(f"api_agent: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
