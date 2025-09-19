import sqlite3
import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
from .notify import notifier

DB_PATH = os.getenv("SR_SQLITE_PATH", os.getenv("SAFERUN_DB", "data/saferun.db"))

def reload_db_path(path: str = None):
    global DB_PATH
    if path:
        DB_PATH = path
    else:
        DB_PATH = os.getenv("SR_SQLITE_PATH", os.getenv("SAFERUN_DB", "data/saferun.db"))
    return DB_PATH

def _conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _column_exists(con, table: str, column: str) -> bool:
    cur = con.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())


def _table_exists(con, table: str) -> bool:
    cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None

def init_db():
    con = _conn(); cur = con.cursor()
    # --- base tables (create if not exists)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS changes(
        change_id TEXT PRIMARY KEY,
        -- keep page_id for backward-compat (deprecated)
        page_id TEXT,
        target_id TEXT,             -- NEW unified id
        provider TEXT,
        title TEXT,
        status TEXT,                -- pending|applied|reverted|expired
        risk_score REAL,
        expires_at TEXT,
        created_at TEXT,
        last_edited_time TEXT,
        policy_json TEXT,
        summary_json TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        change_id TEXT,
        event TEXT,                 -- dry_run|applied|reverted|expired|...
        meta_json TEXT,
        ts TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tokens(
        token TEXT PRIMARY KEY,
        kind TEXT,                  -- approve|revert|...
        ref TEXT,                   -- change_id or revert_token
        expires_at TEXT,
        used INTEGER DEFAULT 0
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    
    # API Keys table for production
    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_keys(
        api_key TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        usage_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        is_active INTEGER DEFAULT 1
    );
    """)

    # --- migrations
    # add target_id if missing
    if not _column_exists(con, "changes", "target_id"):
        try:
            cur.execute("ALTER TABLE changes ADD COLUMN target_id TEXT;")
        except Exception:
            # older SQLite may error if column already exists concurrently; ignore
            pass
        # backfill from legacy page_id if exists
        if _column_exists(con, "changes", "page_id"):
            cur.execute("UPDATE changes SET target_id = COALESCE(target_id, page_id);")

    # add change_id if missing (older schema used target_id as key)
    if not _column_exists(con, "changes", "change_id"):
        try:
            cur.execute("ALTER TABLE changes ADD COLUMN change_id TEXT;")
        except Exception:
            pass
        # backfill change_id from page_id or target_id or rowid
        if _column_exists(con, "changes", "page_id"):
            cur.execute("UPDATE changes SET change_id = COALESCE(page_id, target_id, CAST(rowid AS TEXT));")
        else:
            cur.execute("UPDATE changes SET change_id = COALESCE(target_id, CAST(rowid AS TEXT));")

    # Ensure all expected columns exist (add missing ones for older schemas)
    expected_columns = {
        "provider": "TEXT",
        "title": "TEXT",
        "status": "TEXT",
        "risk_score": "REAL",
        "expires_at": "TEXT",
        "created_at": "TEXT",
        "last_edited_time": "TEXT",
        "policy_json": "TEXT",
        "summary_json": "TEXT",
        "token": "TEXT",
        "revert_token": "TEXT",
        "requires_approval": "INTEGER",
    }

    for col, col_type in expected_columns.items():
        if not _column_exists(con, "changes", col):
            try:
                cur.execute(f"ALTER TABLE changes ADD COLUMN {col} {col_type};")
            except Exception:
                pass

    # Ensure change_id is unique so ON CONFLICT(change_id) works even for migrated schemas
    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_changes_change_id ON changes(change_id);")
    except Exception:
        pass

    con.commit(); con.close()

# --- Generic DB Helpers ---
def fetchall(query: str, params: tuple = ()): 
    con=_conn(); cur=con.cursor()
    cur.execute(query, params)
    rows = cur.fetchall(); con.close(); return [dict(r) for r in rows]

def fetchone(query: str, params: tuple = ()): 
    con=_conn(); cur=con.cursor()
    cur.execute(query, params)
    row = cur.fetchone(); con.close(); return dict(row) if row else None

def exec(query: str, params: tuple = ()): 
    con=_conn(); cur=con.cursor()
    cur.execute(query, params)
    con.commit(); con.close()

# --- Datetime Helpers ---
def parse_dt(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

# --- Functions that remain in SQLite backend ---

def get_setting(key: str, default: str = None) -> str | None:
    row = fetchone("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default

def insert_audit(change_id: str, event: str, meta: dict):
    exec("INSERT INTO audit(change_id,event,meta_json,ts) VALUES(?,?,?,?)",
         (change_id, event, json.dumps(meta or {}), iso_z(now_utc())))

# --- Functions to be moved to SqliteStorage ---
# These are kept here for now to avoid breaking the app, 
# but will be called via the storage interface.

def upsert_change(change: dict):
    """
    Expected keys: change_id, target_id, provider, title, status,
                   risk_score, expires_at, created_at, last_edited_time,
                   policy_json, summary_json
    Back-compat: also writes page_id = target_id if the column exists.
    """
    con = _conn()
    has_page_id = _column_exists(con, "changes", "page_id")

    if has_page_id:
        con.execute("""
        INSERT INTO changes(
            change_id, target_id, page_id, provider, title, status,
            risk_score, expires_at, created_at, last_edited_time,
            policy_json, summary_json, token, revert_token, requires_approval
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(change_id) DO UPDATE SET
            target_id=excluded.target_id,
            page_id=excluded.page_id,
            provider=excluded.provider,
            title=excluded.title,
            status=excluded.status,
            risk_score=excluded.risk_score,
            expires_at=excluded.expires_at,
            created_at=excluded.created_at,
            last_edited_time=excluded.last_edited_time,
            policy_json=excluded.policy_json,
            summary_json=excluded.summary_json,
            token=excluded.token,
            revert_token=excluded.revert_token,
            requires_approval=excluded.requires_approval
        """, (
            change["change_id"],
            change.get("target_id"),
            change.get("page_id", change.get("target_id")),  # mirror for legacy
            change.get("provider"),
            change.get("title"),
            change.get("status"),
            change.get("risk_score"),
            change.get("expires_at"),
            change.get("created_at"),
            change.get("last_edited_time"),
            json.dumps(change.get("policy_json") or change.get("policy") or {}),
            json.dumps(change.get("summary_json") or change.get("summary") or {}),
            change.get("token"),
            change.get("revert_token"),
            int(bool(change.get("requires_approval")))
        ))
    else:
        con.execute("""
        INSERT INTO changes(
            change_id, target_id, provider, title, status,
            risk_score, expires_at, created_at, last_edited_time,
            policy_json, summary_json, token, revert_token, requires_approval
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(change_id) DO UPDATE SET
            target_id=excluded.target_id,
            provider=excluded.provider,
            title=excluded.title,
            status=excluded.status,
            risk_score=excluded.risk_score,
            expires_at=excluded.expires_at,
            created_at=excluded.created_at,
            last_edited_time=excluded.last_edited_time,
            policy_json=excluded.policy_json,
            summary_json=excluded.summary_json,
            token=excluded.token,
            revert_token=excluded.revert_token,
            requires_approval=excluded.requires_approval
        """, (
            change["change_id"],
            change.get("target_id"),
            change.get("provider"),
            change.get("title"),
            change.get("status"),
            change.get("risk_score"),
            change.get("expires_at"),
            change.get("created_at"),
            change.get("last_edited_time"),
            json.dumps(change.get("policy_json") or change.get("policy") or {}),
            json.dumps(change.get("summary_json") or change.get("summary") or {}),
            change.get("token"),
            change.get("revert_token"),
            int(bool(change.get("requires_approval")))
        ))
    con.commit()

def get_change(change_id: str):
    return fetchone("SELECT * FROM changes WHERE change_id=?", (change_id,))

def get_by_revert_token(token: str):
    return fetchone("SELECT * FROM changes WHERE revert_token=?", (token,))

def set_change_status(change_id: str, status: str):
    exec("UPDATE changes SET status=? WHERE change_id=?", (status, change_id))

def set_revert_token(change_id: str, token: str):
    exec("UPDATE changes SET revert_token=? WHERE change_id=?", (token, change_id))

def insert_token(token: str, kind: str, ref: str, expires_at: str):
    exec("INSERT OR REPLACE INTO tokens(token,kind,ref,expires_at,used) VALUES(?,?,?,?,?)",
         (token, kind, ref, expires_at, 0))

def use_token(token: str):
    exec("UPDATE tokens SET used=1 WHERE token=?", (token,))

def get_token(token: str):
    return fetchone("SELECT * FROM tokens WHERE token=?", (token,))

def gc_expired():
    now = now_utc().replace(microsecond=0)
    to_expire = []
    rows = fetchall("SELECT change_id, expires_at FROM changes WHERE status='pending'")
    for r in rows:
        exp = parse_dt(r["expires_at"])
        if exp < now:
            to_expire.append(r["change_id"])

    if to_expire:
        for cid in to_expire:
            set_change_status(cid, "expired")
            insert_audit(cid, "expired", {})
            row = get_change(cid)
            if not row: continue
            try:
                asyncio.get_running_loop()
                schedule = asyncio.create_task
            except RuntimeError:
                def schedule(coro): asyncio.run(coro)
            schedule(notifier.publish("expired", row))

    to_delete = []
    trows = fetchall("SELECT token, expires_at, used FROM tokens")
    for r in trows:
        if r["used"] == 1 or parse_dt(r["expires_at"]) < now:
            to_delete.append(r["token"])
    if to_delete:
        for t in to_delete:
            exec("DELETE FROM tokens WHERE token=?", (t,))

# --- API Key Management Functions ---
import hashlib
import secrets

def generate_api_key() -> str:
    """Generate a secure API key."""
    return f"sr_{secrets.token_urlsafe(32)}"

def create_api_key(email: str) -> str:
    """Create a new API key for an email."""
    api_key = generate_api_key()
    exec(
        "INSERT INTO api_keys(api_key, email, created_at) VALUES (?, ?, ?)",
        (api_key, email, iso_z(now_utc()))
    )
    return api_key

def validate_api_key(api_key: str) -> dict | None:
    """Validate an API key and increment usage count."""
    row = fetchone(
        "SELECT * FROM api_keys WHERE api_key = ? AND is_active = 1",
        (api_key,)
    )
    if row:
        exec(
            "UPDATE api_keys SET usage_count = usage_count + 1 WHERE api_key = ?",
            (api_key,)
        )
    return row

def get_api_key_by_email(email: str) -> dict | None:
    """Get API key info by email."""
    return fetchone(
        "SELECT * FROM api_keys WHERE email = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
        (email,)
    )
