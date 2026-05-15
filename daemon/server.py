"""
Switchboard v2 daemon HTTP server.
Runs on localhost:PORT and serves all adapter calls (Claude Code hook,
future Cursor extension, future ChatGPT extension).

Routes:
  GET  /health    → {"status": "ok", "version": "2.0"}
  POST /compress  → {"text", "ratio"} → {"compressed", "ratio", "source", "filler_count"}
  POST /classify  → {"text", "tokens"} → {tier, score, recommended, usd_delta, hint_label}
  GET  /brevity   → {"mode", "text"}
  POST /brevity   → {"mode"} → {"mode", "text"}
  GET  /stats     → full dashboard dict
  POST /event     → {session_id, event_type, ...} → {"ok": true}
  POST /session   → {"action": "start"|"end", "session_id"} → {"ok": true}
  GET  /rollup    → produce + optionally POST daily digest → payload dict
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT     = int(os.environ.get("SWITCHBOARD_PORT", 9847))
IDLE_SECS = 7200

_last_request: list[float] = [time.monotonic()]
_llmlingua_compressor = None  # lazy-loaded if available


# ── LLMLingua loader (optional heavy dep) ─────────────────────────────────────

def _load_llmlingua():
    global _llmlingua_compressor
    if _llmlingua_compressor is not None:
        return _llmlingua_compressor
    try:
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from llmlingua import PromptCompressor
        _llmlingua_compressor = PromptCompressor(
            model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
            use_llmlingua2=True,
            device_map="cpu",
        )
    except Exception:
        pass
    return _llmlingua_compressor


# ── Request handler ────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass  # suppress access log noise

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _add_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization, x-api-key, anthropic-version")

    def _respond(self, status: int, body: dict | list) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._add_cors()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self._add_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        _last_request[0] = time.monotonic()
        if self.path in ("/health", "/v1/models"):
            if self.path == "/v1/models":
                # OpenAI SDK validation call — return a minimal models list
                self._respond(200, {"object": "list", "data": [
                    {"id": "claude-opus-4-7",   "object": "model"},
                    {"id": "claude-sonnet-4-6", "object": "model"},
                    {"id": "claude-haiku-4-5",  "object": "model"},
                ]})
                return
            self._respond(200, {"status": "ok", "version": "2.0"})

        elif self.path == "/brevity":
            from daemon import brevity, storage
            mode = storage.get_config("brevity_mode", brevity.DEFAULT_MODE)
            self._respond(200, {"mode": mode, "text": brevity.get_text(mode)})

        elif self.path == "/stats":
            from daemon import storage
            self._respond(200, storage.get_stats())

        elif self.path == "/rollup":
            from daemon import rollup
            self._respond(200, rollup.produce_and_send())

        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        _last_request[0] = time.monotonic()
        body = self._read_json()

        if self.path == "/compress":
            self._handle_compress(body)

        elif self.path == "/classify":
            self._handle_classify(body)

        elif self.path == "/brevity":
            self._handle_brevity_set(body)

        elif self.path == "/event":
            self._handle_event(body)

        elif self.path == "/session":
            self._handle_session(body)

        elif self.path == "/v1/chat/completions":
            self._handle_proxy_openai(body)

        elif self.path == "/v1/messages":
            self._handle_proxy_anthropic(body)

        else:
            self._respond(404, {"error": "not found"})

    # ── Route handlers ─────────────────────────────────────────────────────────

    def _handle_compress(self, body: dict) -> None:
        text  = body.get("text", "")
        ratio = float(body.get("ratio", 0.5))

        compressor = _load_llmlingua()
        if compressor:
            try:
                r = compressor.compress_prompt(text, rate=ratio, force_tokens=["\n"])
                compressed = r["compressed_prompt"]
                orig    = r.get("origin_tokens",     len(text)       // 4)
                compr   = r.get("compressed_tokens", len(compressed) // 4)
                actual  = round(orig / max(compr, 1), 2)
                self._respond(200, {
                    "compressed": compressed, "ratio": actual,
                    "source": "llmlingua", "filler_count": 0,
                })
                return
            except Exception:
                pass

        from daemon.compress import heuristic_compress
        compressed, actual, filler_count = heuristic_compress(text, ratio)
        self._respond(200, {
            "compressed": compressed, "ratio": actual,
            "source": "heuristic", "filler_count": filler_count,
        })

    def _handle_classify(self, body: dict) -> None:
        from daemon import classify
        text   = body.get("text", "")
        tokens = int(body.get("tokens", max(len(text) // 4, 1)))
        result = classify.classify(text, tokens)
        self._respond(200, result)

    def _handle_brevity_set(self, body: dict) -> None:
        from daemon import brevity, storage
        mode = brevity.validate(body.get("mode", brevity.DEFAULT_MODE))
        storage.set_config("brevity_mode", mode)
        self._respond(200, {"mode": mode, "text": brevity.get_text(mode)})

    def _handle_event(self, body: dict) -> None:
        from daemon import storage
        session_id = body.pop("session_id", "unknown")
        event_type = body.pop("event_type", "compress")
        try:
            storage.log_event(session_id, event_type, **body)
            self._respond(200, {"ok": True})
        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def _handle_session(self, body: dict) -> None:
        from daemon import storage
        action     = body.get("action", "start")
        session_id = body.get("session_id", "unknown")
        if action == "start":
            storage.session_start(session_id)
        else:
            storage.session_end(session_id)
        self._respond(200, {"ok": True, "session_id": session_id})

    def _handle_proxy_openai(self, body: dict) -> None:
        from daemon import proxy
        api_key = (
            (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or ""
        )
        stream = body.get("stream", False)
        if stream:
            proxy.handle_openai_stream(body, api_key, self)
        else:
            try:
                result = proxy.handle_openai_chat(body, api_key)
                self._respond(200, result)
            except Exception as exc:
                self._respond(502, {"error": str(exc)})

    def _handle_proxy_anthropic(self, body: dict) -> None:
        from daemon import proxy
        api_key = (
            self.headers.get("x-api-key", "").strip()
            or os.environ.get("ANTHROPIC_API_KEY")
            or ""
        )
        anthropic_version = self.headers.get("anthropic-version", "2023-06-01")
        try:
            result = proxy.handle_anthropic_messages(body, api_key, anthropic_version)
            self._respond(200, result)
        except Exception as exc:
            self._respond(502, {"error": str(exc)})


# ── Idle watcher ──────────────────────────────────────────────────────────────

def _idle_watcher(pid_file: Path) -> None:
    while True:
        time.sleep(60)
        if time.monotonic() - _last_request[0] > IDLE_SECS:
            pid_file.unlink(missing_ok=True)
            os._exit(0)


# ── Entry ─────────────────────────────────────────────────────────────────────

def serve(data_dir: Path) -> None:
    """Initialize storage and start the HTTP server (blocking)."""
    from daemon import storage, pricing

    data_dir.mkdir(parents=True, exist_ok=True)
    storage.init(data_dir)
    pricing.try_refresh()

    pid_file = data_dir / "daemon.pid"
    pid_file.write_text(str(os.getpid()))

    threading.Thread(target=_idle_watcher, args=(pid_file,), daemon=True).start()

    # Warm LLMLingua in background so first compress call is fast
    threading.Thread(target=_load_llmlingua, daemon=True).start()

    server = HTTPServer(("localhost", PORT), Handler)
    server.serve_forever()
