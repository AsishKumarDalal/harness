"""sessions.py — the notebook (SQLite).

Every message is written here the moment it happens, so a crash never loses
the conversation. Compaction archives old rows (active=0) instead of deleting
them, so pruned output stays searchable (/search).

Subagents each get their own connection (thread-local) and their own session
row with parent_session_id set — that's Hermes' "lineage".
"""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import config

DB_PATH = config.HARNESS_HOME / "state.db"      # lives OUTSIDE the project

_local = threading.local()      # one connection per thread (children run in threads)
_current = None                 # the parent session currently being served


def db():
    """Open the notebook once per thread and make sure the tables exist."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")     # threads read while writing
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, title TEXT, model TEXT, system_prompt TEXT,
            cwd TEXT, started_at REAL, ended_at REAL, end_reason TEXT,
            parent_session_id TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, role TEXT, content TEXT,
            tool_calls TEXT, tool_call_id TEXT, tool_name TEXT,
            active INTEGER DEFAULT 1, timestamp REAL)""")
        conn.commit()
        _local.conn = conn
    return conn


def set_current(session_id):
    """Remember which session the live loop is serving (children inherit it)."""
    global _current
    _current = session_id


def current_id():
    return _current


def _j(obj):
    """tool_calls list -> stable JSON string (for storing and comparing)."""
    return json.dumps(obj, sort_keys=True) if obj else ""


def _insert(conn, session_id, role, content, tool_calls="", tool_call_id="", tool_name=""):
    conn.execute(
        "INSERT INTO messages (session_id,role,content,tool_calls,tool_call_id,"
        "tool_name,active,timestamp) VALUES (?,?,?,?,?,?,1,?)",
        (session_id, role, content or "", tool_calls, tool_call_id, tool_name, time.time()))


# ---------------- sessions ----------------

def new_session(title=None, system_prompt="", model="", cwd="", parent_session_id=None):
    sid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    db().execute(
        "INSERT INTO sessions (id,title,model,system_prompt,cwd,parent_session_id,started_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (sid, title or None, model, system_prompt, cwd, parent_session_id, time.time()))
    db().commit()
    return sid


def find_session(key):
    """Find by full id, id prefix, or (part of the) title."""
    conn = db()
    for sql, arg in (
        ("SELECT * FROM sessions WHERE id=?", key),
        ("SELECT * FROM sessions WHERE id LIKE ?", key + "%"),
        ("SELECT * FROM sessions WHERE title LIKE ? ORDER BY started_at DESC LIMIT 1", f"%{key}%"),
    ):
        row = conn.execute(sql, (arg,)).fetchone()
        if row:
            return dict(row)
    return None


def list_sessions(limit=20):
    rows = db().execute("""SELECT s.*,
        (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS n
        FROM sessions s ORDER BY s.started_at DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def set_title(session_id, title):
    db().execute("UPDATE sessions SET title=? WHERE id=?", (title[:60], session_id))
    db().commit()


def auto_title(session_id, title):
    db().execute("UPDATE sessions SET title=? WHERE id=? AND (title IS NULL OR title='')",
                 (title[:60], session_id))
    db().commit()


def end_session(session_id, reason="exit"):
    db().execute("UPDATE sessions SET ended_at=?, end_reason=? WHERE id=?",
                 (time.time(), reason, session_id))
    db().commit()


def reopen_session(session_id):
    db().execute("UPDATE sessions SET ended_at=NULL, end_reason=NULL WHERE id=?", (session_id,))
    db().commit()


def delete_session(session_id):
    conn = db()
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()


def prune_sessions(days=30, keep=None):
    """Delete only finished sessions older than N days; never the live one."""
    cutoff = time.time() - days * 86400
    old = db().execute("SELECT id FROM sessions WHERE ended_at IS NOT NULL AND ended_at<?",
                       (cutoff,)).fetchall()
    n = 0
    for r in old:
        if r["id"] != keep:
            delete_session(r["id"])
            n += 1
    return n


# ---------------- messages ----------------

def add_message(session_id, role, content, tool_calls=None, tool_call_id="", tool_name=""):
    """Write exactly one message, the moment it is created (crash-safe)."""
    if not session_id:
        return
    _insert(db(), session_id, role, content, _j(tool_calls), tool_call_id, tool_name)
    db().commit()


def _key(role, content, tool_call_id, tool_calls_json):
    """What makes a message 'the same' message (matches history <-> store)."""
    return (role or "", content or "", tool_call_id or "", tool_calls_json or "")


def sync(session_id, history):
    """Make the store's active rows match the live history.

    Called after compaction. Rows that vanished get archived (active=0,
    still searchable). Brand-new rows get inserted.
    """
    if not session_id:
        return
    conn = db()
    rows = conn.execute("SELECT * FROM messages WHERE session_id=? AND active=1",
                        (session_id,)).fetchall()
    have = {}                                  # key -> list of store row ids
    for r in rows:
        k = _key(r["role"], r["content"], r["tool_call_id"], r["tool_calls"])
        have.setdefault(k, []).append(r["id"])

    live = set(_key(m.get("role"), m.get("content"), m.get("tool_call_id"), _j(m.get("tool_calls")))
               for m in history)
    for r in rows:
        k = _key(r["role"], r["content"], r["tool_call_id"], r["tool_calls"])
        if k not in live:
            conn.execute("UPDATE messages SET active=0 WHERE id=?", (r["id"],))

    for m in history:
        k = _key(m.get("role"), m.get("content"), m.get("tool_call_id"), _j(m.get("tool_calls")))
        if have.get(k):
            have[k].pop()                      # already stored, consume it
        else:
            _insert(conn, session_id, m.get("role", "user"), m.get("content"),
                    _j(m.get("tool_calls")), m.get("tool_call_id") or "")
    conn.commit()


def load_messages(session_id):
    """Rebuild the live history from active rows."""
    rows = db().execute("SELECT * FROM messages WHERE session_id=? AND active=1 "
                        "ORDER BY id", (session_id,)).fetchall()
    history = []
    for r in rows:
        msg = {"role": r["role"], "content": r["content"] or ""}
        if r["tool_calls"]:
            msg["tool_calls"] = json.loads(r["tool_calls"])
        if r["tool_call_id"]:
            msg["tool_call_id"] = r["tool_call_id"]
        history.append(msg)
    return history


# ---------------- search + export ----------------

def search(query, limit=5):
    """Search ALL messages ever stored (live + archived — includes subagents)."""
    q = (query or "").strip()
    if not q:
        return []
    rows = db().execute(
        "SELECT session_id, role, content, tool_name, timestamp FROM messages "
        "WHERE content LIKE ? OR tool_name LIKE ? ORDER BY id DESC LIMIT ?",
        (f"%{q}%", f"%{q}%", limit)).fetchall()
    return [dict(r) for r in rows]


def export_session(session_id, path=None):
    """Dump every row of a session (live + archived) to one JSONL file."""
    conn = db()
    s = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not s:
        return None
    rows = conn.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id",
                        (session_id,)).fetchall()
    out = Path(path) if path else config.HARNESS_HOME / "exports" / f"{session_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps({"session": dict(s)}) + "\n")
        for r in rows:
            f.write(json.dumps(dict(r)) + "\n")
    return str(out)