"""
SQLite-backed state for Switchboard v2.
Replaces daily_stats.json with queryable event log + session tracking.
"""

import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

_db_path: Path | None = None


def init(data_dir: Path) -> None:
    global _db_path
    _db_path = data_dir / "state.db"
    _create_schema()


def _conn() -> sqlite3.Connection:
    assert _db_path, "storage.init() must be called before use"
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _create_schema() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL    NOT NULL,
                session_id   TEXT    NOT NULL,
                event_type   TEXT    NOT NULL,
                tokens_in    INTEGER DEFAULT 0,
                tokens_saved INTEGER DEFAULT 0,
                ratio        REAL    DEFAULT 1.0,
                source       TEXT    DEFAULT 'heuristic',
                tier         TEXT    DEFAULT '',
                model_hint   TEXT    DEFAULT '',
                usd_saved    REAL    DEFAULT 0.0,
                brevity_mode TEXT    DEFAULT 'full'
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
            CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);

            CREATE TABLE IF NOT EXISTS sessions (
                id           TEXT PRIMARY KEY,
                start_ts     REAL NOT NULL,
                end_ts       REAL,
                brevity_mode TEXT DEFAULT 'full'
            );

            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)


# ── Config helpers ────────────────────────────────────────────────────────────

def set_config(key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config(key, value) VALUES(?,?)", (key, value)
        )


def get_config(key: str, default: str = "") -> str:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


# ── Session lifecycle ─────────────────────────────────────────────────────────

def session_start(session_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions(id, start_ts) VALUES(?,?)",
            (session_id, time.time()),
        )
    set_config("current_session_id", session_id)


def session_end(session_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE sessions SET end_ts=? WHERE id=?",
            (time.time(), session_id),
        )


# ── Event logging ─────────────────────────────────────────────────────────────

def log_event(session_id: str, event_type: str, **kwargs) -> None:
    cols = ["ts", "session_id", "event_type"] + list(kwargs.keys())
    vals = [time.time(), session_id, event_type] + list(kwargs.values())
    placeholders = ",".join("?" * len(vals))
    with _conn() as conn:
        conn.execute(
            f"INSERT INTO events ({','.join(cols)}) VALUES ({placeholders})", vals
        )


# ── Stats queries ─────────────────────────────────────────────────────────────

def get_stats() -> dict:
    session_id = get_config("current_session_id", "")
    brevity_mode = get_config("brevity_mode", "full")

    with _conn() as conn:
        def _agg(where: str, params: tuple = ()) -> sqlite3.Row:
            return conn.execute(
                f"""SELECT
                    COALESCE(SUM(tokens_in), 0)    AS tokens_in,
                    COALESCE(SUM(tokens_saved), 0) AS tokens_saved,
                    COALESCE(SUM(usd_saved), 0)    AS usd_saved,
                    COUNT(*)                        AS compressions
                FROM events WHERE event_type='compress' AND {where}""",
                params,
            ).fetchone()

        sess = _agg("session_id=?", (session_id,))
        life = _agg("1=1")

        daily_rows = conn.execute(
            """SELECT
                DATE(ts, 'unixepoch', 'localtime') AS day,
                COALESCE(SUM(tokens_saved), 0)     AS tokens_saved,
                COALESCE(SUM(usd_saved), 0)        AS usd_saved
               FROM events
               WHERE event_type='compress'
                 AND ts >= strftime('%s', 'now', '-7 days')
               GROUP BY day ORDER BY day""",
        ).fetchall()

        tier_rows = conn.execute(
            """SELECT tier, COUNT(*) AS cnt
               FROM events
               WHERE event_type='compress' AND tier != ''
               GROUP BY tier ORDER BY cnt DESC LIMIT 5""",
        ).fetchall()

        streak_rows = conn.execute(
            """SELECT DISTINCT DATE(ts, 'unixepoch', 'localtime') AS day
               FROM events WHERE event_type='compress'
               ORDER BY day DESC""",
        ).fetchall()

    streak = 0
    today = date.today()
    for i, row in enumerate(streak_rows):
        if row["day"] == str(today - timedelta(days=i)):
            streak += 1
        else:
            break

    return {
        "session": {
            "tokens_in":    sess["tokens_in"],
            "tokens_saved": sess["tokens_saved"],
            "usd_saved":    round(sess["usd_saved"], 4),
            "compressions": sess["compressions"],
        },
        "lifetime": {
            "tokens_in":    life["tokens_in"],
            "tokens_saved": life["tokens_saved"],
            "usd_saved":    round(life["usd_saved"], 4),
            "compressions": life["compressions"],
        },
        "daily_7":     [dict(r) for r in daily_rows],
        "streak":      streak,
        "top_tiers":   [dict(r) for r in tier_rows],
        "brevity_mode": brevity_mode,
    }


def daily_rollup(date_str: str) -> dict:
    with _conn() as conn:
        row = conn.execute(
            """SELECT
                COALESCE(SUM(tokens_in), 0)    AS tokens_in,
                COALESCE(SUM(tokens_saved), 0) AS tokens_saved,
                COALESCE(SUM(usd_saved), 0)    AS usd_saved,
                COUNT(*)                        AS compressions
               FROM events
               WHERE event_type='compress'
                 AND DATE(ts, 'unixepoch', 'localtime') = ?""",
            (date_str,),
        ).fetchone()

        by_model = conn.execute(
            """SELECT model_hint, COALESCE(SUM(usd_saved), 0) AS usd_saved
               FROM events
               WHERE event_type='compress'
                 AND DATE(ts, 'unixepoch', 'localtime') = ?
               GROUP BY model_hint""",
            (date_str,),
        ).fetchall()

    return {
        "date":         date_str,
        "tokens_in":    row["tokens_in"],
        "tokens_saved": row["tokens_saved"],
        "usd_saved":    round(row["usd_saved"], 4),
        "compressions": row["compressions"],
        "by_model":     {r["model_hint"]: round(r["usd_saved"], 6) for r in by_model},
    }
