"""
Switchboard universal GenAI proxy.

Intercepts OpenAI-compatible and Anthropic SDK calls, compresses the last
user message, forwards to the real API, and logs savings to SQLite.

Usage (one-line change):
    # OpenAI SDK / LangChain / any OpenAI-compatible tool
    client = OpenAI(base_url="http://localhost:9847/v1", api_key="YOUR_KEY")

    # Anthropic SDK
    client = anthropic.Anthropic(base_url="http://localhost:9847", api_key="YOUR_KEY")
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

MIN_RATIO   = 1.05   # skip trivial compressions
MIN_CHARS   = 40     # skip very short messages


def _session_id() -> str:
    return str(date.today())


def _compress_last_user_msg(messages: list[dict], model: str) -> tuple[int, int, float, float]:
    """
    Find the last user message, compress it in-place.
    Returns (tokens_in, tokens_saved, ratio, usd_saved).
    """
    from daemon.compress import heuristic_compress
    from daemon.pricing import usd_for_tokens

    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            # multi-part content — find the first text part
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part["text"]
                    if len(text) < MIN_CHARS:
                        return 0, 0, 1.0, 0.0
                    compressed, ratio, _ = heuristic_compress(text)
                    if ratio < MIN_RATIO:
                        return 0, 0, 1.0, 0.0
                    part["text"] = compressed
                    tokens_in    = len(text) // 4
                    tokens_saved = tokens_in - max(len(compressed) // 4, 1)
                    usd_saved    = usd_for_tokens(tokens_saved, model)
                    return tokens_in, tokens_saved, ratio, usd_saved
            return 0, 0, 1.0, 0.0
        elif isinstance(content, str):
            if len(content) < MIN_CHARS:
                return 0, 0, 1.0, 0.0
            compressed, ratio, _ = heuristic_compress(content)
            if ratio < MIN_RATIO:
                return 0, 0, 1.0, 0.0
            msg["content"] = compressed
            tokens_in    = len(content) // 4
            tokens_saved = tokens_in - max(len(compressed) // 4, 1)
            usd_saved    = usd_for_tokens(tokens_saved, model)
            return tokens_in, tokens_saved, ratio, usd_saved

    return 0, 0, 1.0, 0.0


def _log(model: str, tokens_in: int, tokens_saved: int, ratio: float, usd_saved: float) -> None:
    if tokens_saved <= 0:
        return
    try:
        from daemon import storage
        sid = _session_id()
        storage.log_event(
            sid, "proxy",
            tokens_in=tokens_in,
            tokens_saved=tokens_saved,
            ratio=ratio,
            source="proxy-heuristic",
            tier="MEDIUM",
            model_hint=model[:80],
            usd_saved=usd_saved,
            brevity_mode="full",
        )
    except Exception:
        pass


# ── OpenAI-compatible /v1/chat/completions ────────────────────────────────────

def handle_openai_chat(body: dict, api_key: str) -> dict:
    """Non-streaming: compress → forward via litellm → return OpenAI-format dict."""
    import litellm

    messages = body.get("messages", [])
    model    = body.get("model", "claude-opus-4-7")

    tokens_in, tokens_saved, ratio, usd_saved = _compress_last_user_msg(messages, model)

    extra = {k: v for k, v in body.items() if k not in ("model", "messages", "stream")}

    resp = litellm.completion(
        model=model,
        messages=messages,
        api_key=api_key or None,
        **extra,
    )

    _log(model, tokens_in, tokens_saved, ratio, usd_saved)
    return resp.model_dump()


def handle_openai_stream(body: dict, api_key: str, handler: "BaseHTTPRequestHandler") -> None:
    """Streaming: compress → forward as SSE chunks."""
    import litellm

    messages = body.get("messages", [])
    model    = body.get("model", "claude-opus-4-7")

    tokens_in, tokens_saved, ratio, usd_saved = _compress_last_user_msg(messages, model)

    extra = {k: v for k, v in body.items() if k not in ("model", "messages", "stream")}

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Transfer-Encoding", "chunked")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()

    try:
        for chunk in litellm.completion(
            model=model,
            messages=messages,
            api_key=api_key or None,
            stream=True,
            **extra,
        ):
            line = f"data: {chunk.model_dump_json()}\n\n".encode()
            handler.wfile.write(line)
            handler.wfile.flush()
        handler.wfile.write(b"data: [DONE]\n\n")
        handler.wfile.flush()
    except Exception as exc:
        err = f"data: {json.dumps({'error': str(exc)})}\n\n".encode()
        try:
            handler.wfile.write(err)
            handler.wfile.flush()
        except Exception:
            pass

    _log(model, tokens_in, tokens_saved, ratio, usd_saved)


# ── Anthropic /v1/messages ────────────────────────────────────────────────────

def handle_anthropic_messages(body: dict, api_key: str, anthropic_version: str) -> dict:
    """Compress last user message → forward directly to api.anthropic.com."""
    messages = body.get("messages", [])
    model    = body.get("model", "claude-opus-4-7")

    tokens_in, tokens_saved, ratio, usd_saved = _compress_last_user_msg(messages, model)

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type":    "application/json",
            "x-api-key":       api_key,
            "anthropic-version": anthropic_version or "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        result = json.loads(r.read())

    _log(model, tokens_in, tokens_saved, ratio, usd_saved)
    return result
