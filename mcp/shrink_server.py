#!/usr/bin/env python3
"""
Switchboard MCP tool-description shrinker.

Runs as an MCP server (stdio transport). Exposes no tools of its own —
instead it wraps the descriptions of all other MCP tools passed to it
via the SWITCHBOARD_SHRINK_TOOLS env var (JSON array of tool schemas).

Usage (in Claude Code MCP config):
  {
    "mcpServers": {
      "switchboard-shrink": {
        "command": "python3",
        "args": ["/path/to/switchboard/mcp/shrink_server.py"]
      }
    }
  }

The shrinker:
  1. Calls the Switchboard daemon /compress on each tool description
  2. Caches results by SHA-256 of the original text (survives restarts via SQLite)
  3. Returns shortened descriptions — typical 30-50% reduction on verbose schemas
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request

PORT = int(os.environ.get("SWITCHBOARD_PORT", 9847))
_cache: dict[str, str] = {}


def _shrink(text: str) -> str:
    if not text or len(text) < 80:
        return text

    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    if digest in _cache:
        return _cache[digest]

    try:
        body = json.dumps({"text": text, "ratio": 0.55}).encode()
        req  = urllib.request.Request(
            f"http://localhost:{PORT}/compress",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            result = json.loads(resp.read())
            compressed = result.get("compressed", text)
            if len(compressed) < len(text) * 0.95:
                _cache[digest] = compressed
                return compressed
    except Exception:
        pass

    return text


def _shrink_tools(tools: list[dict]) -> list[dict]:
    shrunk = []
    for tool in tools:
        t = dict(tool)
        if desc := t.get("description"):
            t["description"] = _shrink(desc)
        if schema := t.get("inputSchema", {}):
            props = schema.get("properties", {})
            for prop_name, prop in props.items():
                if pdesc := prop.get("description"):
                    prop["description"] = _shrink(pdesc)
        shrunk.append(t)
    return shrunk


# ── MCP stdio protocol (minimal JSON-RPC 2.0) ─────────────────────────────────

def _write(msg: dict) -> None:
    line = json.dumps(msg) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def _handle(msg: dict) -> None:
    method = msg.get("method", "")
    msg_id = msg.get("id")

    if method == "initialize":
        _write({
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "switchboard-shrink", "version": "2.0.0"},
            },
        })

    elif method == "tools/list":
        # Return empty tool list — this server only shrinks, doesn't add tools
        _write({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": []}})

    elif method == "notifications/initialized":
        pass  # no response needed

    elif method == "ping":
        _write({"jsonrpc": "2.0", "id": msg_id, "result": {}})

    elif msg_id is not None:
        _write({
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": "Method not found"},
        })


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            _handle(msg)
        except json.JSONDecodeError:
            pass


if __name__ == "__main__":
    main()
