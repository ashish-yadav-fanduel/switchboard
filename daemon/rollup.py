"""
Daily signed rollup for opt-in org telemetry.
Produces an HMAC-signed payload of aggregate counts (no prompt text).
POSTs to SWITCHBOARD_ROLLUP_URL when SWITCHBOARD_ROLLUP_OPTIN=1.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from datetime import date

from daemon import storage


def _engineer_id() -> str:
    """SHA-256 of email + org salt. No PII leaves the machine in plaintext."""
    email = os.environ.get("SWITCHBOARD_ENGINEER_EMAIL", os.environ.get("USER", "unknown"))
    salt  = os.environ.get("SWITCHBOARD_ORG_SALT", "switchboard-fanduel-v2")
    return hashlib.sha256(f"{email}:{salt}".encode()).hexdigest()[:16]


def _sign(payload: dict, secret: str) -> str:
    body = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def produce_and_send(date_str: str | None = None) -> dict:
    """
    Build today's rollup dict, sign it, and POST to SWITCHBOARD_ROLLUP_URL
    if opt-in is enabled. Always returns the (unsigned) payload dict.
    """
    if date_str is None:
        date_str = str(date.today())

    data = storage.daily_rollup(date_str)
    payload = {
        "version":     "2",
        "engineer_id": _engineer_id(),
        **data,
    }

    optin   = os.environ.get("SWITCHBOARD_ROLLUP_OPTIN", "0").strip() == "1"
    url     = os.environ.get("SWITCHBOARD_ROLLUP_URL", "").strip()
    secret  = os.environ.get("SWITCHBOARD_ROLLUP_SECRET", "switchboard-default-secret")

    if optin and url:
        signed_payload = {**payload, "sig": _sign(payload, secret)}
        body = json.dumps(signed_payload).encode()
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "X-Switchboard-Version": "2"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload["_sent"] = resp.status == 200
        except Exception as exc:
            payload["_send_error"] = str(exc)

    return payload


def maybe_send_today(last_sent_key: str = "rollup_last_sent") -> bool:
    """Send today's rollup at most once per day. Returns True if sent."""
    today = str(date.today())
    if storage.get_config(last_sent_key, "") == today:
        return False
    result = produce_and_send(today)
    if not result.get("_send_error"):
        storage.set_config(last_sent_key, today)
        return True
    return False
