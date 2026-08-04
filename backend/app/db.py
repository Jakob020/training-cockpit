"""SQLite key/value store. Mirrors the window.storage semantics the frontend
used in the sandbox: each app 'key' (settings, plan, nutrition, strength, log)
is one JSON blob. This keeps the frontend logic almost unchanged after the move
off the sandbox."""
import json
import os
import sqlite3
import threading

DB_PATH = os.environ.get("DB_PATH", "cockpit.db")
_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
    return conn


def kv_get(key):
    with _lock, _conn() as c:
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None


def kv_set(key, value):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


def kv_delete(key):
    with _lock, _conn() as c:
        c.execute("DELETE FROM kv WHERE key=?", (key,))
