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


class ModelResponseError(RuntimeError):
    """A completed provider reply with metering but unusable model content.

    Exposes only provider response metadata, never raw model content. The
    caller can meter the failed call without accepting an invalid action.
    """

    def __init__(self, message, metrics):
        super().__init__(message)
        self.metrics = metrics


class ProviderModelDriftError(ModelResponseError):
    """The provider-reported model changed during one pinned trial."""


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Keep bearer credentials and experiment requests on the pinned origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _direct_opener():
    """Do not inherit ambient HTTP(S) proxies or follow provider redirects."""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _RejectRedirects())


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


def request_body(request, params, instructions=INSTRUCTIONS):
    """Exact UTF-8 JSON HTTP body used by this adapter (before HTTP headers)."""
    payload = {**params, "messages": [
        {"role": "developer", "content": instructions},
        {"role": "user", "content": json.dumps(request, sort_keys=True,
                                               ensure_ascii=False)},
    ]}
    return json.dumps(payload).encode("utf-8")


def provider_usage(envelope):
    """Validate provider *reported* counts; this is not an external audit."""
    usage = envelope.get("usage")
    if usage is None:
        return {"prompt_tokens": None, "completion_tokens": None,
                "total_tokens": None}
    if not isinstance(usage, dict):
        raise ValueError("Provider usage must be an object")
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    values = [usage.get(name) for name in fields]
    if all(value is None for value in values):
        return dict(zip(fields, values))
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("Provider usage requires three nonnegative integer counts")
    if values[0] + values[1] != values[2]:
        raise ValueError("Provider usage total disagrees with component counts")
    return dict(zip(fields, values))


def call_model(request, *, resolved_config=None, instructions=INSTRUCTIONS):
    # Private trials pin the full endpoint/decoder configuration at startup.
    url, key, params, timeout = (configuration() if resolved_config is None
                                 else resolved_config)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    http_request = urllib.request.Request(
        url, data=request_body(request, params, instructions),
        headers=headers, method="POST")
    try:
        with _direct_opener().open(http_request, timeout=timeout) as reply:
            raw = reply.read(1_000_001)
    except urllib.error.HTTPError as exc:
        # Do not print response bodies: providers may include sensitive echoes.
        raise RuntimeError(f"Model endpoint returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Model endpoint unavailable: {type(exc.reason).__name__}") from exc
    if len(raw) > 1_000_000:
        raise RuntimeError("Model endpoint response exceeds 1 MB")
    envelope = json.loads(raw)
    if not isinstance(envelope, dict):
        raise ValueError("Provider response envelope must be an object")
    reported_model = envelope.get("model")
    if not isinstance(reported_model, str) or not reported_model:
        raise ValueError("Provider model identity missing")
    usage = provider_usage(envelope)
    choices = envelope.get("choices")
    choice = (choices[0] if isinstance(choices, list) and choices and
              isinstance(choices[0], dict) else None)
    metrics = {
        "provider_response_id": envelope.get("id"),
        "model": reported_model,
        "finish_reason": choice.get("finish_reason") if choice else None,
        **usage,
        "usage_provenance": "provider_response_envelope_unverified",
        "requested_max_completion_tokens": params["max_completion_tokens"],
        "requested_seed": params.get("seed"),
        "requested_temperature": params.get("temperature"),
    }
    if not choice or not isinstance(choice.get("message"), dict):
        raise ModelResponseError("Provider response has no usable message", metrics)
    content = choice["message"].get("content")
    if not isinstance(content, str):
        raise ModelResponseError("Model message content must be a JSON string", metrics)
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ModelResponseError("Model content is not valid JSON", metrics) from exc
    if not isinstance(result, dict):
        raise ModelResponseError("Model must return a JSON object", metrics)
    result["metrics"] = metrics
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
