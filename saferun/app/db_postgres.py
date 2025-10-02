"""PostgreSQL database adapter for SafeRun."""
import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any

DATABASE_URL = os.getenv("DATABASE_URL")

def reload_db_path(path: str = None):
    """No-op for Postgres - DATABASE_URL is managed via env vars."""
    return DATABASE_URL

def get_connection():
    """Get PostgreSQL connection."""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Initialize PostgreSQL database schema."""
    conn = get_connection()
    cur = conn.cursor()

    # Create changes table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS changes(
        change_id TEXT PRIMARY KEY,
        page_id TEXT,
        target_id TEXT,
        provider TEXT,
        title TEXT,
        status TEXT,
        risk_score REAL,
        expires_at TIMESTAMP,
        created_at TIMESTAMP,
        last_edited_time TIMESTAMP,
        policy_json TEXT,
        summary_json TEXT,
        token TEXT,
        revert_token TEXT,
        requires_approval INTEGER DEFAULT 0
    );
    """)

    # Create audit table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit(
        id SERIAL PRIMARY KEY,
        change_id TEXT,
        event TEXT,
        meta_json TEXT,
        ts TIMESTAMP
    );
    """)

    # Create tokens table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tokens(
        token TEXT PRIMARY KEY,
        kind TEXT,
        ref TEXT,
        expires_at TIMESTAMP,
        used INTEGER DEFAULT 0
    );
    """)

    # Create settings table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)

    # Create API keys table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_keys(
        api_key TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        usage_count INTEGER DEFAULT 0,
        created_at TIMESTAMP NOT NULL,
        is_active INTEGER DEFAULT 1
    );
    """)

    conn.commit()
    conn.close()

def fetchall(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Execute query and return all rows as dicts."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def fetchone(query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    """Execute query and return one row as dict."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def exec(query: str, params: tuple = ()):
    """Execute query without returning results."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    conn.close()

# Datetime helpers
def parse_dt(s: str) -> datetime:
    """Parse ISO datetime string."""
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(s, datetime):
        # Ensure timezone aware
        if s.tzinfo is None:
            return s.replace(tzinfo=timezone.utc)
        return s
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    # Ensure timezone aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)

def iso_z(dt: datetime) -> str:
    """Convert datetime to ISO string with Z suffix."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

# Settings
def get_setting(key: str, default: str = None) -> Optional[str]:
    """Get setting value."""
    row = fetchone("SELECT value FROM settings WHERE key=%s", (key,))
    return row["value"] if row else default

# Audit
def insert_audit(change_id: str, event: str, meta: dict):
    """Insert audit log entry."""
    exec("INSERT INTO audit(change_id, event, meta_json, ts) VALUES(%s, %s, %s, %s)",
         (change_id, event, json.dumps(meta or {}), now_utc()))

# Changes
def upsert_change(change: dict):
    """Insert or update change record."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO changes(
        change_id, target_id, page_id, provider, title, status,
        risk_score, expires_at, created_at, last_edited_time,
        policy_json, summary_json, token, revert_token, requires_approval
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT(change_id) DO UPDATE SET
        target_id=EXCLUDED.target_id,
        page_id=EXCLUDED.page_id,
        provider=EXCLUDED.provider,
        title=EXCLUDED.title,
        status=EXCLUDED.status,
        risk_score=EXCLUDED.risk_score,
        expires_at=EXCLUDED.expires_at,
        created_at=EXCLUDED.created_at,
        last_edited_time=EXCLUDED.last_edited_time,
        policy_json=EXCLUDED.policy_json,
        summary_json=EXCLUDED.summary_json,
        token=EXCLUDED.token,
        revert_token=EXCLUDED.revert_token,
        requires_approval=EXCLUDED.requires_approval
    """, (
        change["change_id"],
        change.get("target_id"),
        change.get("page_id", change.get("target_id")),
        change.get("provider"),
        change.get("title"),
        change.get("status"),
        change.get("risk_score"),
        parse_dt(change.get("expires_at")) if change.get("expires_at") else None,
        parse_dt(change.get("created_at")) if change.get("created_at") else now_utc(),
        parse_dt(change.get("last_edited_time")) if change.get("last_edited_time") else None,
        json.dumps(change.get("policy_json") or change.get("policy") or {}),
        json.dumps(change.get("summary_json") or change.get("summary") or {}),
        change.get("token"),
        change.get("revert_token"),
        int(bool(change.get("requires_approval")))
    ))

    conn.commit()
    conn.close()

def get_change(change_id: str) -> Optional[Dict[str, Any]]:
    """Get change by ID."""
    return fetchone("SELECT * FROM changes WHERE change_id=%s", (change_id,))

def get_by_revert_token(token: str) -> Optional[Dict[str, Any]]:
    """Get change by revert token."""
    return fetchone("SELECT * FROM changes WHERE revert_token=%s", (token,))

def set_change_status(change_id: str, status: str):
    """Update change status."""
    exec("UPDATE changes SET status=%s WHERE change_id=%s", (status, change_id))

def set_revert_token(change_id: str, token: str):
    """Set revert token for change."""
    exec("UPDATE changes SET revert_token=%s WHERE change_id=%s", (token, change_id))

# Tokens
def insert_token(token: str, kind: str, ref: str, expires_at: str):
    """Insert token."""
    exec("INSERT INTO tokens(token, kind, ref, expires_at, used) VALUES(%s, %s, %s, %s, %s) ON CONFLICT(token) DO UPDATE SET kind=EXCLUDED.kind, ref=EXCLUDED.ref, expires_at=EXCLUDED.expires_at",
         (token, kind, ref, parse_dt(expires_at), 0))

def use_token(token: str):
    """Mark token as used."""
    exec("UPDATE tokens SET used=1 WHERE token=%s", (token,))

def get_token(token: str) -> Optional[Dict[str, Any]]:
    """Get token by value."""
    return fetchone("SELECT * FROM tokens WHERE token=%s", (token,))

# Garbage collection
def gc_expired():
    """Expire old changes and delete used tokens."""
    from .notify import notifier
    import asyncio

    now = now_utc()

    # Expire old changes
    rows = fetchall("SELECT change_id, expires_at FROM changes WHERE status='pending'")
    for r in rows:
        exp = parse_dt(r["expires_at"]) if r["expires_at"] else datetime.max.replace(tzinfo=timezone.utc)
        if exp < now:
            set_change_status(r["change_id"], "expired")
            insert_audit(r["change_id"], "expired", {})
            row = get_change(r["change_id"])
            if row:
                try:
                    asyncio.get_running_loop()
                    schedule = asyncio.create_task
                except RuntimeError:
                    def schedule(coro): asyncio.run(coro)
                schedule(notifier.publish("expired", row))

    # Delete used/expired tokens
    trows = fetchall("SELECT token, expires_at, used FROM tokens")
    for r in trows:
        exp = parse_dt(r["expires_at"]) if r["expires_at"] else datetime.max.replace(tzinfo=timezone.utc)
        if r["used"] == 1 or exp < now:
            exec("DELETE FROM tokens WHERE token=%s", (r["token"],))

# API Key Management
import secrets

def generate_api_key() -> str:
    """Generate a secure API key."""
    return f"sr_{secrets.token_urlsafe(32)}"

def create_api_key(email: str) -> str:
    """Create a new API key for an email."""
    api_key = generate_api_key()
    exec(
        "INSERT INTO api_keys(api_key, email, created_at) VALUES (%s, %s, %s)",
        (api_key, email, now_utc())
    )
    return api_key

def validate_api_key(api_key: str) -> Optional[Dict[str, Any]]:
    """Validate an API key and increment usage count."""
    row = fetchone(
        "SELECT * FROM api_keys WHERE api_key = %s AND is_active = 1",
        (api_key,)
    )
    if not row:
        return None

    exec(
        "UPDATE api_keys SET usage_count = usage_count + 1 WHERE api_key = %s",
        (api_key,)
    )

    updated = fetchone(
        "SELECT * FROM api_keys WHERE api_key = %s AND is_active = 1",
        (api_key,)
    )
    return updated

def get_api_key_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get API key info by email."""
    return fetchone(
        "SELECT * FROM api_keys WHERE email = %s AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
        (email,)
    )
