"""PostgreSQL database adapter for SafeRun."""
import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any
from . import crypto

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
        metadata TEXT,
        token TEXT,
        revert_token TEXT,
        requires_approval INTEGER DEFAULT 0,
        api_key TEXT,
        branch_head_sha TEXT,
        revert_window INTEGER,
        revert_expires_at TIMESTAMP
    );
    
    CREATE INDEX IF NOT EXISTS idx_changes_api_key ON changes(api_key);
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

    # Create user notification settings table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_notification_settings(
        api_key TEXT PRIMARY KEY,
        slack_webhook_url TEXT,
        slack_bot_token TEXT,
        slack_channel TEXT DEFAULT '#saferun-alerts',
        slack_enabled INTEGER DEFAULT 0,
        email TEXT,
        email_enabled INTEGER DEFAULT 1,
        webhook_url TEXT,
        webhook_secret TEXT,
        webhook_enabled INTEGER DEFAULT 0,
        notification_channels TEXT DEFAULT '["email"]',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY (api_key) REFERENCES api_keys(api_key) ON DELETE CASCADE
    );
    """)

    # Create GitHub installations table (for GitHub App)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS github_installations(
        id SERIAL PRIMARY KEY,
        installation_id INTEGER UNIQUE NOT NULL,
        api_key TEXT,
        account_login TEXT,
        installed_at TIMESTAMP NOT NULL,
        repositories_json TEXT DEFAULT '[]',
        FOREIGN KEY (api_key) REFERENCES api_keys(api_key) ON DELETE SET NULL
    );
    """)

    # Create approval tokens table (Phase 1.4 fix: Approval flow auth)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS approval_tokens(
        token TEXT PRIMARY KEY,
        change_id TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        used BOOLEAN DEFAULT FALSE,
        used_at TIMESTAMP,
        FOREIGN KEY (change_id) REFERENCES changes(change_id) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_approval_tokens_change_id
    ON approval_tokens(change_id);
    """)

    # Migration: Add metadata column if not exists (for existing deployments)
    cur.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='changes' AND column_name='metadata'
        ) THEN
            ALTER TABLE changes ADD COLUMN metadata TEXT;
        END IF;
    END $$;
    """)

    # Migration: Add github_installation_id to api_keys (for GitHub App linking)
    cur.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='api_keys' AND column_name='github_installation_id'
        ) THEN
            ALTER TABLE api_keys ADD COLUMN github_installation_id INTEGER;
        END IF;
    END $$;
    """)

    # Migration: Add slack_message_ts column to changes table (for message updates)
    cur.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='changes' AND column_name='slack_message_ts'
        ) THEN
            ALTER TABLE changes ADD COLUMN slack_message_ts TEXT;
        END IF;
    END $$;
    """)

    # Migration: Add revert_window columns to changes table
    cur.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='changes' AND column_name='revert_window'
        ) THEN
            ALTER TABLE changes ADD COLUMN revert_window INTEGER;
        END IF;
        
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='changes' AND column_name='revert_expires_at'
        ) THEN
            ALTER TABLE changes ADD COLUMN revert_expires_at TIMESTAMP;
        END IF;
    END $$;
    """)

    # Create Slack OAuth state table (for CSRF protection)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS oauth_states(
        state TEXT PRIMARY KEY,
        api_key TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMP NOT NULL,
        used BOOLEAN DEFAULT FALSE,
        is_slack_connected BOOLEAN DEFAULT FALSE,
        is_github_installed BOOLEAN DEFAULT FALSE,
        github_installation_id INTEGER,
        FOREIGN KEY (api_key) REFERENCES api_keys(api_key) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_oauth_states_expires ON oauth_states(expires_at);
    CREATE INDEX IF NOT EXISTS idx_oauth_states_unified_status 
        ON oauth_states(state, is_slack_connected, is_github_installed);
    """)
    
    # Migration for existing tables: add unified setup columns
    cur.execute("""
    DO $$ 
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'oauth_states' AND column_name = 'is_slack_connected'
        ) THEN
            ALTER TABLE oauth_states ADD COLUMN is_slack_connected BOOLEAN DEFAULT FALSE;
        END IF;
        
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'oauth_states' AND column_name = 'is_github_installed'
        ) THEN
            ALTER TABLE oauth_states ADD COLUMN is_github_installed BOOLEAN DEFAULT FALSE;
        END IF;
        
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'oauth_states' AND column_name = 'github_installation_id'
        ) THEN
            ALTER TABLE oauth_states ADD COLUMN github_installation_id INTEGER;
        END IF;
    END $$;
    """)

    # Create Slack installations table (OAuth tokens)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS slack_installations(
        id SERIAL PRIMARY KEY,
        api_key TEXT UNIQUE NOT NULL,
        team_id TEXT NOT NULL,
        team_name TEXT,
        bot_token TEXT NOT NULL,
        bot_user_id TEXT,
        channel_id TEXT,
        installed_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        FOREIGN KEY (api_key) REFERENCES api_keys(api_key) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_slack_installations_team ON slack_installations(team_id);
    """)
    
    # Add UNIQUE constraint on team_id (one workspace per account, prevent hijacking)
    # Using DO NOTHING to handle case where constraint already exists
    try:
        cur.execute("""
        ALTER TABLE slack_installations 
        ADD CONSTRAINT slack_installations_team_id_unique UNIQUE (team_id);
        """)
    except Exception:
        pass  # Constraint may already exist

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

# Token encryption migration
def migrate_tokens_to_encrypted():
    """
    Migrate existing plaintext tokens to encrypted format.
    Safe to run multiple times (idempotent).
    Returns number of tokens migrated.
    """
    conn = get_connection()
    cur = conn.cursor()
    
    # Migrate changes.token
    cur.execute("SELECT change_id, token FROM changes WHERE token IS NOT NULL AND token != ''")
    rows = cur.fetchall()
    
    migrated_count = 0
    for row in rows:
        change_id = row[0]
        token = row[1]
        
        # Skip if already encrypted
        if crypto.is_encrypted(token):
            continue
        
        # Encrypt and update
        try:
            encrypted = crypto.encrypt_token(token)
            cur.execute("UPDATE changes SET token = %s WHERE change_id = %s", (encrypted, change_id))
            migrated_count += 1
        except Exception as e:
            print(f"Warning: Failed to encrypt token for change {change_id}: {e}")
    
    # Migrate changes.revert_token
    cur.execute("SELECT change_id, revert_token FROM changes WHERE revert_token IS NOT NULL AND revert_token != ''")
    rows = cur.fetchall()
    
    for row in rows:
        change_id = row[0]
        token = row[1]
        
        # Skip if already encrypted
        if crypto.is_encrypted(token):
            continue
        
        # Encrypt and update
        try:
            encrypted = crypto.encrypt_token(token)
            cur.execute("UPDATE changes SET revert_token = %s WHERE change_id = %s", (encrypted, change_id))
            migrated_count += 1
        except Exception as e:
            print(f"Warning: Failed to encrypt revert_token for change {change_id}: {e}")
    
    conn.commit()
    cur.close()
    
    return migrated_count

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
    # Encrypt sensitive tokens before storing
    if change.get("token"):
        change["token"] = crypto.encrypt_token(change["token"])
    
    if change.get("revert_token"):
        change["revert_token"] = crypto.encrypt_token(change["revert_token"])
    
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO changes(
        change_id, target_id, page_id, provider, title, status,
        risk_score, expires_at, created_at, last_edited_time,
        policy_json, summary_json, metadata, token, revert_token, requires_approval,
        api_key, branch_head_sha, revert_window, revert_expires_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        metadata=EXCLUDED.metadata,
        token=EXCLUDED.token,
        revert_token=EXCLUDED.revert_token,
        requires_approval=EXCLUDED.requires_approval,
        api_key=EXCLUDED.api_key,
        branch_head_sha=EXCLUDED.branch_head_sha,
        revert_window=EXCLUDED.revert_window,
        revert_expires_at=EXCLUDED.revert_expires_at
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
        # Fix double JSON encoding: only dump if not already a string
        json.dumps(change.get("summary_json") or change.get("summary") or {}) if not isinstance(change.get("summary_json"), str) else change.get("summary_json"),
        # Always serialize metadata to JSON string (even if empty dict)
        change.get("metadata") if isinstance(change.get("metadata"), str) else json.dumps(change.get("metadata") or {}),
        change.get("token"),
        change.get("revert_token"),
        int(bool(change.get("requires_approval"))),
        change.get("api_key"),
        change.get("branch_head_sha"),
        change.get("revert_window"),
        parse_dt(change.get("revert_expires_at")) if change.get("revert_expires_at") else None
    ))

    conn.commit()
    conn.close()

def get_change(change_id: str) -> Optional[Dict[str, Any]]:
    """Get change by ID."""
    rec = fetchone("SELECT * FROM changes WHERE change_id=%s", (change_id,))
    
    # Decrypt tokens after retrieving (only if encrypted)
    if rec and rec.get("token") and crypto.is_encrypted(rec["token"]):
        rec["token"] = crypto.decrypt_token(rec["token"])
    
    if rec and rec.get("revert_token") and crypto.is_encrypted(rec["revert_token"]):
        rec["revert_token"] = crypto.decrypt_token(rec["revert_token"])
    
    return rec

def get_by_revert_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Get change by revert token.
    Note: Encrypted tokens require scanning all records (migration will improve this)
    """
    # Try direct lookup first (for backward compat with plaintext)
    rec = fetchone("SELECT * FROM changes WHERE revert_token=%s", (token,))
    
    if rec:
        # Decrypt if encrypted
        if rec.get("revert_token") and crypto.is_encrypted(rec["revert_token"]):
            rec["revert_token"] = crypto.decrypt_token(rec["revert_token"])
        if rec.get("token") and crypto.is_encrypted(rec["token"]):
            rec["token"] = crypto.decrypt_token(rec["token"])
        return rec
    
    # If not found, token might be plaintext query against encrypted DB
    # Scan all records (inefficient, but only during migration period)
    all_recs = fetchall("SELECT * FROM changes WHERE revert_token IS NOT NULL")
    for rec in all_recs:
        encrypted_token = rec.get("revert_token")
        if encrypted_token and crypto.is_encrypted(encrypted_token):
            decrypted = crypto.decrypt_token(encrypted_token)
            if decrypted == token:
                rec["revert_token"] = decrypted
                if rec.get("token") and crypto.is_encrypted(rec["token"]):
                    rec["token"] = crypto.decrypt_token(rec["token"])
                return rec
    
    return None

def set_change_status(change_id: str, status: str):
    """Update change status."""
    exec("UPDATE changes SET status=%s WHERE change_id=%s", (status, change_id))

def set_revert_token(change_id: str, token: str):
    """Set revert token for change."""
    # Encrypt before storing
    encrypted_token = crypto.encrypt_token(token)
    exec("UPDATE changes SET revert_token=%s WHERE change_id=%s", (encrypted_token, change_id))

def update_summary_json(change_id: str, summary_json: dict):
    """Update summary_json for change."""
    import json
    summary_json_str = json.dumps(summary_json) if isinstance(summary_json, dict) else summary_json
    exec("UPDATE changes SET summary_json=%s WHERE change_id=%s", (summary_json_str, change_id))

def set_slack_message_ts(change_id: str, message_ts: str):
    """Set Slack message timestamp for change (to enable message updates)."""
    exec("UPDATE changes SET slack_message_ts=%s WHERE change_id=%s", (message_ts, change_id))

def get_slack_message_ts(change_id: str) -> Optional[str]:
    """Get Slack message timestamp for change."""
    row = fetchone("SELECT slack_message_ts FROM changes WHERE change_id=%s", (change_id,))
    return row.get("slack_message_ts") if row else None


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


def get_api_key(api_key: str) -> Optional[Dict[str, Any]]:
    """Get API key info by key value."""
    return fetchone(
        "SELECT * FROM api_keys WHERE api_key = %s AND is_active = 1",
        (api_key,)
    )


def get_api_key_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get API key info by email."""
    return fetchone(
        "SELECT * FROM api_keys WHERE email = %s AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
        (email,)
    )

# Notification Settings Management
def get_notification_settings(api_key: str) -> Optional[Dict[str, Any]]:
    """Get notification settings with decryption for sensitive data."""
    row = fetchone(
        "SELECT * FROM user_notification_settings WHERE api_key = %s",
        (api_key,)
    )
    
    if not row:
        return None
    
    # Decrypt sensitive fields (with fallback for legacy plain text)
    def safe_decrypt(value: str) -> Optional[str]:
        """Decrypt token, or return as-is if not encrypted (legacy plain text)."""
        if not value:
            return None
        
        # If it's plain text (URLs or tokens with known prefixes), return as-is
        if value.startswith(('https://', 'http://', 'xoxb-', 'xoxp-', 'xoxe-', 'xoxa-')):
            return value
        
        # Only decrypt if it looks encrypted
        if crypto.is_encrypted(value):
            decrypted = crypto.decrypt_token(value)
            return decrypted if decrypted else value
        
        # Not encrypted - return as-is (legacy plain text)
        return value
    
    if row.get("slack_webhook_url"):
        row["slack_webhook_url"] = safe_decrypt(row["slack_webhook_url"])
    
    if row.get("slack_bot_token"):
        row["slack_bot_token"] = safe_decrypt(row["slack_bot_token"])
    
    if row.get("webhook_secret"):
        row["webhook_secret"] = safe_decrypt(row["webhook_secret"])
    
    return row


def get_protected_branches(api_key: str) -> str:
    """Get protected branches pattern for user. Returns comma-separated patterns."""
    row = fetchone(
        "SELECT protected_branches FROM user_notification_settings WHERE api_key = %s",
        (api_key,)
    )
    if row and row.get("protected_branches"):
        return row["protected_branches"]
    return "main,master"  # Default


def update_protected_branches(api_key: str, branches: str, old_value: str = None):
    """Update protected branches and log to audit."""
    exec(
        "UPDATE user_notification_settings SET protected_branches = %s WHERE api_key = %s",
        (branches, api_key)
    )
    # Audit log for Banking Grade compliance
    insert_audit(
        change_id=f"settings_{api_key[:8]}",
        event="protected_branches_update",
        meta={"old_value": old_value, "new_value": branches, "api_key": api_key[:8]}
    )


def upsert_notification_settings(api_key: str, settings: Dict[str, Any]):
    """Insert or update notification settings with encryption for sensitive data."""
    conn = get_connection()
    cur = conn.cursor()

    # Encrypt sensitive fields before storing
    slack_webhook = settings.get("slack_webhook_url")
    slack_bot_token = settings.get("slack_bot_token")
    webhook_secret = settings.get("webhook_secret")
    
    encrypted_slack_webhook = crypto.encrypt_token(slack_webhook) if slack_webhook else None
    encrypted_bot_token = crypto.encrypt_token(slack_bot_token) if slack_bot_token else None
    encrypted_webhook_secret = crypto.encrypt_token(webhook_secret) if webhook_secret else None

    cur.execute("""
    INSERT INTO user_notification_settings(
        api_key, slack_webhook_url, slack_bot_token, slack_channel, slack_enabled,
        email, email_enabled, webhook_url, webhook_secret, webhook_enabled,
        notification_channels, updated_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT(api_key) DO UPDATE SET
        slack_webhook_url=EXCLUDED.slack_webhook_url,
        slack_bot_token=EXCLUDED.slack_bot_token,
        slack_channel=EXCLUDED.slack_channel,
        slack_enabled=EXCLUDED.slack_enabled,
        email=EXCLUDED.email,
        email_enabled=EXCLUDED.email_enabled,
        webhook_url=EXCLUDED.webhook_url,
        webhook_secret=EXCLUDED.webhook_secret,
        webhook_enabled=EXCLUDED.webhook_enabled,
        notification_channels=EXCLUDED.notification_channels,
        updated_at=EXCLUDED.updated_at
    """, (
        api_key,
        encrypted_slack_webhook,   # ← ENCRYPTED
        encrypted_bot_token,        # ← ENCRYPTED
        settings.get("slack_channel", "#saferun-alerts"),
        int(bool(settings.get("slack_enabled", False))),
        settings.get("email"),
        int(bool(settings.get("email_enabled", True))),
        settings.get("webhook_url"),
        encrypted_webhook_secret,   # ← ENCRYPTED
        int(bool(settings.get("webhook_enabled", False))),
        json.dumps(settings.get("notification_channels", ["email"])),
        now_utc()
    ))

    conn.commit()
    conn.close()

def delete_notification_settings(api_key: str):
    """Delete notification settings for an API key."""
    exec("DELETE FROM user_notification_settings WHERE api_key = %s", (api_key,))


def migrate_notification_secrets() -> int:
    """
    Migrate existing plain text secrets to encrypted format.
    
    This is idempotent - can be run multiple times safely.
    Returns: Number of records migrated
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Get all settings with potential plain text secrets
    cur.execute("""
        SELECT api_key, slack_webhook_url, slack_bot_token, webhook_secret
        FROM user_notification_settings
        WHERE slack_webhook_url IS NOT NULL 
           OR slack_bot_token IS NOT NULL
           OR webhook_secret IS NOT NULL
    """)
    
    rows = cur.fetchall()
    migrated_count = 0
    
    for row in rows:
        api_key = row["api_key"]
        needs_update = False
        updates = {}
        
        # Check and encrypt slack_webhook_url if plain text
        if row.get("slack_webhook_url"):
            webhook = row["slack_webhook_url"]
            # If starts with http(s):// it's plain text - needs encryption
            if webhook.startswith(('https://', 'http://')):
                updates["slack_webhook_url"] = crypto.encrypt_token(webhook)
                needs_update = True
        
        # Check and encrypt slack_bot_token if plain text
        if row.get("slack_bot_token"):
            token = row["slack_bot_token"]
            # If starts with xox prefix it's plain text - needs encryption
            if token.startswith(('xoxb-', 'xoxp-', 'xoxe-', 'xoxa-')):
                updates["slack_bot_token"] = crypto.encrypt_token(token)
                needs_update = True
        
        # Check and encrypt webhook_secret if plain text
        if row.get("webhook_secret"):
            secret = row["webhook_secret"]
            # If it doesn't look like encrypted data (base64), encrypt it
            if not (len(secret) > 20 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in secret)):
                updates["webhook_secret"] = crypto.encrypt_token(secret)
                needs_update = True
        
        # Update if any field needs encryption
        if needs_update:
            update_fields = []
            values = []
            
            if "slack_webhook_url" in updates:
                update_fields.append("slack_webhook_url = %s")
                values.append(updates["slack_webhook_url"])
            
            if "slack_bot_token" in updates:
                update_fields.append("slack_bot_token = %s")
                values.append(updates["slack_bot_token"])
            
            if "webhook_secret" in updates:
                update_fields.append("webhook_secret = %s")
                values.append(updates["webhook_secret"])
            
            values.append(api_key)
            
            cur.execute(f"""
                UPDATE user_notification_settings
                SET {', '.join(update_fields)}, updated_at = NOW()
                WHERE api_key = %s
            """, values)
            
            migrated_count += 1
    
    conn.commit()
    cur.close()
    conn.close()
    
    return migrated_count


# =============================================================================
# Phase 1.4 Fix: Approval Token Functions (for Slack/Landing page auth)
# =============================================================================

def create_approval_token(change_id: str) -> str:
    """
    Create one-time approval token for change_id.
    Used by Slack/Landing page for authentication without API key.
    
    Returns: 32-byte URL-safe token
    """
    import secrets
    token = secrets.token_urlsafe(32)
    
    exec("""
        INSERT INTO approval_tokens(token, change_id, created_at, used)
        VALUES (%s, %s, NOW(), FALSE)
    """, (token, change_id))
    
    return token


def verify_approval_token(change_id: str, token: str) -> bool:
    """
    Verify and consume one-time approval token.
    
    Returns: True if token is valid and unused, False otherwise
    Side effect: Marks token as used if valid
    """
    row = fetchone("""
        SELECT used, change_id FROM approval_tokens
        WHERE token=%s
    """, (token,))
    
    if not row:
        return False  # Token doesn't exist
    
    if row['used']:
        return False  # Token already used
    
    if row['change_id'] != change_id:
        return False  # Token belongs to different change_id
    
    # Mark as used (one-time token)
    exec("""
        UPDATE approval_tokens
        SET used=TRUE, used_at=NOW()
        WHERE token=%s
    """, (token,))
    
    return True


def get_approval_token_info(token: str) -> Optional[Dict[str, Any]]:
    """
    Get approval token info without consuming it.
    Used by GET endpoint to verify token before showing UI.
    
    Returns: Dict with token info or None if invalid
    """
    return fetchone("""
        SELECT token, change_id, created_at, used, used_at
        FROM approval_tokens
        WHERE token=%s
    """, (token,))


# =============================================================================
# Slack OAuth Functions
# =============================================================================

def store_oauth_state(state: str, api_key: str, expires_minutes: int = 10):
    """
    Store OAuth state for CSRF protection.
    
    Args:
        state: UUID state parameter
        api_key: API key to link after OAuth completes
        expires_minutes: TTL for state (default 10 min)
    """
    expires_at = now_utc() + timedelta(minutes=expires_minutes)
    
    exec("""
        INSERT INTO oauth_states(state, api_key, created_at, expires_at, used)
        VALUES (%s, %s, NOW(), %s, FALSE)
        ON CONFLICT (state) DO UPDATE SET
            api_key = EXCLUDED.api_key,
            expires_at = EXCLUDED.expires_at,
            used = FALSE
    """, (state, api_key, expires_at))


def verify_oauth_state(state: str) -> Optional[Dict[str, Any]]:
    """
    Verify OAuth state is valid and not expired.
    
    Returns: Dict with api_key if valid, None otherwise
    """
    row = fetchone("""
        SELECT state, api_key, expires_at, used
        FROM oauth_states
        WHERE state = %s
    """, (state,))
    
    if not row:
        return None
    
    if row['used']:
        return None  # Already used
    
    # Check expiration
    expires_at = parse_dt(row['expires_at']) if isinstance(row['expires_at'], str) else row['expires_at']
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    if now_utc() > expires_at:
        return None  # Expired
    
    return {"api_key": row['api_key']}


def mark_oauth_state_used(state: str):
    """Mark OAuth state as used."""
    exec("""
        UPDATE oauth_states SET used = TRUE
        WHERE state = %s
    """, (state,))


def cleanup_expired_oauth_states():
    """
    Delete expired OAuth states (housekeeping).
    
    IMPORTANT: For unified setup (Slack + GitHub), we keep states that:
    - Have completed Slack but not GitHub (is_slack_connected=TRUE, is_github_installed=FALSE)
    - Are not yet expired
    
    This allows the GitHub callback to find the state after Slack OAuth completes.
    """
    exec("""
        DELETE FROM oauth_states
        WHERE expires_at < NOW()
           OR (used = TRUE AND is_slack_connected = TRUE AND is_github_installed = TRUE)
    """)


# =============================================================================
# Unified Cloud Setup Functions
# =============================================================================

def get_setup_session_status(state: str) -> Optional[Dict[str, Any]]:
    """
    Get current status of a setup session (used by CLI polling).
    
    Returns dict with:
    - api_key: The associated API key
    - is_slack_connected: Whether Slack OAuth completed
    - is_github_installed: Whether GitHub App was installed
    - expires_at: Session expiration time
    
    Returns None if state is invalid or expired.
    """
    row = fetchone("""
        SELECT state, api_key, expires_at, used,
               COALESCE(is_slack_connected, FALSE) as is_slack_connected,
               COALESCE(is_github_installed, FALSE) as is_github_installed,
               github_installation_id
        FROM oauth_states
        WHERE state = %s
    """, (state,))
    
    if not row:
        return None
    
    # Check expiration (allow checking status even if used, for multi-provider flow)
    expires_at = parse_dt(row['expires_at']) if isinstance(row['expires_at'], str) else row['expires_at']
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    if now_utc() > expires_at:
        return None  # Expired
    
    return {
        "api_key": row['api_key'],
        "is_slack_connected": row['is_slack_connected'],
        "is_github_installed": row['is_github_installed'],
        "github_installation_id": row.get('github_installation_id'),
        "expires_at": expires_at
    }


def update_slack_connected_status(state: str) -> bool:
    """
    Mark Slack as connected for a setup session.
    Called after successful Slack OAuth completion.
    
    Returns True if updated, False if state not found/expired.
    """
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            UPDATE oauth_states 
            SET is_slack_connected = TRUE
            WHERE state = %s 
              AND expires_at > NOW()
            RETURNING state
        """, (state,))
        
        row = cur.fetchone()
        conn.commit()
        return row is not None
        
    except Exception as e:
        conn.rollback()
        import logging
        logging.getLogger(__name__).error(f"update_slack_connected_status failed: {e}")
        return False
    finally:
        cur.close()
        conn.close()


def complete_github_installation(state: str, installation_id: int) -> tuple[str | None, str | None]:
    """
    Atomic GitHub App installation completion.
    
    SECURITY: Uses UPDATE...RETURNING with row-level lock to prevent race conditions.
    Links GitHub installation_id to the setup session and marks GitHub as installed.
    
    Args:
        state: OAuth state UUID from the setup session
        installation_id: GitHub App installation ID
    
    Returns:
        Tuple of (api_key, error_message)
        - Success: (api_key, None)
        - Failure: (None, error_message)
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # Step 1: Atomic state update with row-level lock
        cur.execute("""
            UPDATE oauth_states 
            SET is_github_installed = TRUE,
                github_installation_id = %s
            WHERE state = %s 
              AND expires_at > NOW()
            RETURNING api_key
        """, (installation_id, state))
        
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return None, "Invalid or expired setup session. Please restart setup."
        
        api_key = row['api_key']
        
        # Step 2: Check if this installation_id is already linked to another api_key
        cur.execute("""
            SELECT api_key FROM github_installations WHERE installation_id = %s
        """, (installation_id,))
        existing = cur.fetchone()
        
        if existing and existing['api_key'] != api_key:
            conn.rollback()
            return None, "This GitHub App installation is already linked to another SafeRun account."
        
        # Step 3: Upsert github_installations table
        cur.execute("""
            INSERT INTO github_installations(installation_id, api_key, installed_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (installation_id) DO UPDATE SET
                api_key = EXCLUDED.api_key,
                installed_at = NOW()
        """, (installation_id, api_key))
        
        # Step 4: Also update api_keys.github_installation_id for quick lookup
        cur.execute("""
            UPDATE api_keys 
            SET github_installation_id = %s
            WHERE api_key = %s
        """, (installation_id, api_key))
        
        conn.commit()
        return api_key, None
        
    except Exception as e:
        conn.rollback()
        import logging
        logging.getLogger(__name__).error(f"complete_github_installation failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def store_slack_installation(
    api_key: str,
    team_id: str,
    team_name: str,
    bot_token: str,
    bot_user_id: str = None,
    channel_id: str = None
):
    """
    Store Slack installation with encrypted bot token.
    
    Upserts: If api_key already has installation, updates it.
    """
    # Encrypt bot token before storing
    encrypted_token = crypto.encrypt_token(bot_token)
    
    exec("""
        INSERT INTO slack_installations(
            api_key, team_id, team_name, bot_token, bot_user_id, channel_id, installed_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (api_key) DO UPDATE SET
            team_id = EXCLUDED.team_id,
            team_name = EXCLUDED.team_name,
            bot_token = EXCLUDED.bot_token,
            bot_user_id = EXCLUDED.bot_user_id,
            channel_id = EXCLUDED.channel_id,
            updated_at = NOW()
    """, (api_key, team_id, team_name, encrypted_token, bot_user_id, channel_id))


def get_slack_installation(api_key: str) -> Optional[Dict[str, Any]]:
    """
    Get Slack installation for API key.
    
    Returns: Dict with decrypted bot_token, or None if not found
    """
    row = fetchone("""
        SELECT api_key, team_id, team_name, bot_token, bot_user_id, channel_id, installed_at
        FROM slack_installations
        WHERE api_key = %s
    """, (api_key,))
    
    if not row:
        return None
    
    # Decrypt bot token
    decrypted_token = crypto.decrypt_token(row['bot_token'])
    if not decrypted_token:
        # Decryption failed - token may be corrupted
        return None
    
    return {
        "api_key": row['api_key'],
        "team_id": row['team_id'],
        "team_name": row['team_name'],
        "bot_token": decrypted_token,
        "bot_user_id": row['bot_user_id'],
        "channel_id": row['channel_id'],
        "installed_at": row['installed_at']
    }


def get_slack_installation_by_team(team_id: str) -> Optional[Dict[str, Any]]:
    """
    Get Slack installation by team_id.
    
    Used to check if a workspace is already connected to another account.
    Returns: Dict with api_key, team info, and bot_user_id (no token), or None if not found
    """
    row = fetchone("""
        SELECT api_key, team_id, team_name, bot_user_id, channel_id, installed_at
        FROM slack_installations
        WHERE team_id = %s
    """, (team_id,))
    
    if not row:
        return None
    
    return {
        "api_key": row['api_key'],
        "team_id": row['team_id'],
        "team_name": row['team_name'],
        "bot_user_id": row.get('bot_user_id'),
        "channel_id": row.get('channel_id'),
        "installed_at": row['installed_at']
    }


def update_slack_channel(team_id: str, channel_id: str) -> bool:
    """
    Update channel_id for a Slack installation.
    
    Called when bot joins a channel (member_joined_channel event).
    This enables zero-config channel detection.
    
    Args:
        team_id: Slack workspace ID
        channel_id: Channel ID where bot was added
    
    Returns: True if updated, False if team not found
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE slack_installations 
            SET channel_id = %s, updated_at = NOW()
            WHERE team_id = %s
        """, (channel_id, team_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
        conn.close()


def delete_slack_installation(api_key: str) -> bool:
    """
    Delete Slack installation for API key.
    
    Returns: True if deleted, False if not found
    """
    row = fetchone("""
        SELECT api_key FROM slack_installations WHERE api_key = %s
    """, (api_key,))
    
    if not row:
        return False
    
    exec("""
        DELETE FROM slack_installations WHERE api_key = %s
    """, (api_key,))
    
    return True


def complete_slack_oauth(
    state: str,
    team_id: str,
    team_name: str,
    bot_token: str,
    bot_user_id: str = None,
    channel_id: str = None
) -> tuple[str | None, str | None]:
    """
    Atomic OAuth completion: verify state + store installation in single transaction.
    
    SECURITY: Prevents race conditions by using UPDATE ... RETURNING with row-level lock.
    All operations happen in a single transaction - if any step fails, everything rolls back.
    
    Args:
        state: OAuth state UUID to consume
        team_id: Slack workspace ID
        team_name: Slack workspace name
        bot_token: Bot OAuth token (will be encrypted)
        bot_user_id: Bot user ID
        channel_id: Default channel ID
    
    Returns:
        Tuple of (api_key, error_message)
        - Success: (api_key, None)
        - Failure: (None, error_message)
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # Step 1: Atomic state consumption with row-level lock
        # UPDATE ... RETURNING ensures only ONE request can consume the state
        # Also set is_slack_connected for unified setup polling
        cur.execute("""
            UPDATE oauth_states 
            SET used = TRUE,
                is_slack_connected = TRUE
            WHERE state = %s 
              AND used = FALSE 
              AND expires_at > NOW()
            RETURNING api_key
        """, (state,))
        
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return None, "Invalid or expired authorization link. Please try again."
        
        api_key = row['api_key']
        
        # Step 2: Encrypt bot token
        encrypted_token = crypto.encrypt_token(bot_token)
        
        # Step 3: UPSERT by team_id (atomic workspace transfer)
        # If workspace exists under different api_key, it gets transferred
        # This is Banking Grade - single atomic operation, no DELETE + INSERT
        cur.execute("""
            INSERT INTO slack_installations(
                api_key, team_id, team_name, bot_token, 
                bot_user_id, channel_id, installed_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (team_id) DO UPDATE SET
                api_key = EXCLUDED.api_key,
                team_name = EXCLUDED.team_name,
                bot_token = EXCLUDED.bot_token,
                bot_user_id = EXCLUDED.bot_user_id,
                channel_id = EXCLUDED.channel_id,
                updated_at = NOW()
            RETURNING (xmax = 0) AS inserted
        """, (api_key, team_id, team_name, encrypted_token, bot_user_id, channel_id))
        
        result = cur.fetchone()
        was_insert = result['inserted'] if result else True
        
        # Audit log for workspace transfer (update case)
        if not was_insert:
            import logging
            logging.getLogger(__name__).warning(
                f"AUDIT: Slack workspace '{team_name}' ({team_id}) transferred to api_key={api_key[:15]}... "
                f"(authorized via Slack OAuth)"
            )
        
        # Commit entire transaction atomically
        conn.commit()
        
        return api_key, None
        
    except Exception as e:
        conn.rollback()
        # Log but don't expose internal error details
        import logging
        logging.getLogger(__name__).error(f"complete_slack_oauth failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()
