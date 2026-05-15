"""Tests for daemon/storage.py — SQLite event log, session tracking, stats queries."""

import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from daemon import storage


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    storage.init(tmp_path)
    yield
    # reset global so next fixture gets a clean state
    storage._db_path = None


def test_session_lifecycle():
    storage.session_start("sess-1")
    assert storage.get_config("current_session_id") == "sess-1"
    storage.session_end("sess-1")
    # second start should not overwrite existing row (INSERT OR IGNORE)
    storage.session_start("sess-1")
    assert storage.get_config("current_session_id") == "sess-1"


def test_config_roundtrip():
    storage.set_config("brevity_mode", "ultra")
    assert storage.get_config("brevity_mode") == "ultra"
    storage.set_config("brevity_mode", "lite")
    assert storage.get_config("brevity_mode") == "lite"


def test_config_default():
    assert storage.get_config("nonexistent_key", "fallback") == "fallback"
    assert storage.get_config("nonexistent_key") == ""


def test_log_and_query_events():
    storage.session_start("s1")
    storage.log_event("s1", "compress",
                      tokens_in=400, tokens_saved=150, ratio=2.0,
                      source="heuristic", tier="SIMPLE",
                      model_hint="haiku", usd_saved=0.002, brevity_mode="full")
    storage.log_event("s1", "compress",
                      tokens_in=600, tokens_saved=200, ratio=1.8,
                      source="heuristic", tier="MEDIUM",
                      model_hint="", usd_saved=0.003, brevity_mode="full")

    stats = storage.get_stats()
    assert stats["session"]["tokens_saved"] == 350
    assert stats["session"]["compressions"] == 2
    assert stats["lifetime"]["tokens_in"] == 1000
    assert round(stats["session"]["usd_saved"], 4) == 0.005


def test_stats_streak_single_day():
    storage.session_start("s1")
    storage.log_event("s1", "compress",
                      tokens_in=100, tokens_saved=40, ratio=1.5,
                      source="heuristic", tier="SIMPLE",
                      model_hint="", usd_saved=0.001, brevity_mode="full")
    stats = storage.get_stats()
    assert stats["streak"] == 1


def test_stats_top_tiers():
    storage.session_start("s1")
    for _ in range(3):
        storage.log_event("s1", "compress",
                          tokens_in=100, tokens_saved=30, ratio=1.4,
                          source="heuristic", tier="SIMPLE",
                          model_hint="", usd_saved=0.001, brevity_mode="full")
    storage.log_event("s1", "compress",
                      tokens_in=200, tokens_saved=60, ratio=1.5,
                      source="heuristic", tier="REASONING",
                      model_hint="", usd_saved=0.002, brevity_mode="full")

    stats = storage.get_stats()
    tiers = {t["tier"]: t["cnt"] for t in stats["top_tiers"]}
    assert tiers["SIMPLE"] == 3
    assert tiers["REASONING"] == 1


def test_daily_rollup():
    from datetime import date
    today = str(date.today())
    storage.session_start("s1")
    storage.log_event("s1", "compress",
                      tokens_in=500, tokens_saved=200, ratio=2.0,
                      source="heuristic", tier="MEDIUM",
                      model_hint="sonnet", usd_saved=0.005, brevity_mode="full")

    rollup = storage.daily_rollup(today)
    assert rollup["date"] == today
    assert rollup["tokens_in"] == 500
    assert rollup["tokens_saved"] == 200
    assert rollup["compressions"] == 1
    assert rollup["usd_saved"] == 0.005
    assert "sonnet" in rollup["by_model"]


def test_rollup_empty_day():
    rollup = storage.daily_rollup("1970-01-01")
    assert rollup["tokens_saved"] == 0
    assert rollup["compressions"] == 0
    assert rollup["by_model"] == {}


def test_session_isolation():
    storage.session_start("s1")
    storage.log_event("s1", "compress",
                      tokens_in=100, tokens_saved=40, ratio=1.5,
                      source="heuristic", tier="SIMPLE",
                      model_hint="", usd_saved=0.001, brevity_mode="full")
    # start a new session
    storage.session_start("s2")
    storage.log_event("s2", "compress",
                      tokens_in=200, tokens_saved=80, ratio=1.8,
                      source="heuristic", tier="MEDIUM",
                      model_hint="", usd_saved=0.002, brevity_mode="full")

    # current_session_id = s2
    stats = storage.get_stats()
    assert stats["session"]["tokens_saved"] == 80
    assert stats["lifetime"]["tokens_saved"] == 120
