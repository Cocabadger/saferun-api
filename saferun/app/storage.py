from abc import ABC, abstractmethod
import os
import json
import redis
from typing import Dict, Any, Optional

from .metrics import record_change_status
from . import db_adapter as db

class Storage(ABC):
    @abstractmethod
    def save_change(self, change_id: str, data: Dict[str, Any], ttl_seconds: int) -> None:
        pass

    @abstractmethod
    def get_change(self, change_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def save_token(self, token: str, data: Dict[str, Any], ttl_seconds: int) -> None:
        pass

    @abstractmethod
    def get_token(self, token: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def use_token(self, token: str) -> None:
        pass

    @abstractmethod
    def get_change_by_revert_token(self, revert_token: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def set_change_status(self, change_id: str, status: str) -> None:
        pass

    @abstractmethod
    def set_revert_token(self, change_id: str, token: str) -> None:
        pass

    @abstractmethod
    def update_summary_json(self, change_id: str, summary_json: dict) -> None:
        pass

    @abstractmethod
    def run_gc(self) -> None:
        pass


class SqliteStorage(Storage):
    def save_change(self, change_id: str, data: Dict[str, Any], ttl_seconds: int) -> None:
        # ttl_seconds is implicitly handled by expires_at in the data
        db.upsert_change(data)

    def get_change(self, change_id: str) -> Optional[Dict[str, Any]]:
        row = db.get_change(change_id)
        return dict(row) if row else None

    def save_token(self, token: str, data: Dict[str, Any], ttl_seconds: int) -> None:
        # ttl_seconds is implicitly handled by expires_at in the data
        db.insert_token(token, data["kind"], data["ref"], data["expires_at"])

    def get_token(self, token: str) -> Optional[Dict[str, Any]]:
        row = db.get_token(token)
        return dict(row) if row else None

    def use_token(self, token: str) -> None:
        db.use_token(token)

    def get_change_by_revert_token(self, revert_token: str) -> Optional[Dict[str, Any]]:
        row = db.get_by_revert_token(revert_token)
        return dict(row) if row else None

    def set_change_status(self, change_id: str, status: str) -> None:
        db.set_change_status(change_id, status)
        # Emit metrics on terminal states
        try:
            if status in ("applied", "reverted"):
                record_change_status(status)
        except Exception:
            pass

    def set_revert_token(self, change_id: str, token: str) -> None:
        db.set_revert_token(change_id, token)

    def update_summary_json(self, change_id: str, summary_json: dict) -> None:
        db.update_summary_json(change_id, summary_json)

    def set_change_approved(self, change_id: str, approved: bool) -> None:
        # Persist requires_approval flip (toggle to False once approved)
        try:
            rec = db.get_change(change_id)
            if rec:
                # If approved we clear requires_approval so subsequent apply passes
                new_rec = dict(rec)
                new_rec["requires_approval"] = 0 if approved else rec.get("requires_approval")
                db.upsert_change(new_rec)
        except Exception:
            pass

    def run_gc(self) -> None:
        db.gc_expired()


class RedisStorage(Storage):
    def __init__(self, url: str):
        self.redis = redis.from_url(url, decode_responses=True)

    def save_change(self, change_id: str, data: Dict[str, Any], ttl_seconds: int) -> None:
        key = f"changes:{change_id}"
        self.redis.set(key, json.dumps(data), ex=ttl_seconds)
        if data.get("revert_token"):
            revert_key = f"revert_tokens:{data['revert_token']}"
            self.redis.set(revert_key, change_id, ex=ttl_seconds)

    def get_change(self, change_id: str) -> Optional[Dict[str, Any]]:
        key = f"changes:{change_id}"
        data = self.redis.get(key)
        return json.loads(data) if data else None

    def save_token(self, token: str, data: Dict[str, Any], ttl_seconds: int) -> None:
        key = f"tokens:{token}"
        self.redis.set(key, json.dumps(data), ex=ttl_seconds)

    def get_token(self, token: str) -> Optional[Dict[str, Any]]:
        key = f"tokens:{token}"
        data = self.redis.get(key)
        return json.loads(data) if data else None

    def use_token(self, token: str) -> None:
        key = f"tokens:{token}"
        data = self.get_token(token)
        if data:
            data["used"] = 1
            # Re-save with the original TTL if possible, otherwise it will be short
            self.redis.set(key, json.dumps(data), keepttl=True)

    def get_change_by_revert_token(self, revert_token: str) -> Optional[Dict[str, Any]]:
        revert_key = f"revert_tokens:{revert_token}"
        change_id = self.redis.get(revert_key)
        return self.get_change(change_id) if change_id else None

    def _update_change_field(self, change_id: str, field: str, value: Any) -> None:
        change = self.get_change(change_id)
        if change:
            change[field] = value
            ttl = self.redis.ttl(f"changes:{change_id}")
            self.save_change(change_id, change, ttl if ttl > 0 else 3600)

    def set_change_status(self, change_id: str, status: str) -> None:
        self._update_change_field(change_id, "status", status)
        # Emit metrics on terminal states
        try:
            if status in ("applied", "reverted"):
                record_change_status(status)
        except Exception:
            pass

    def set_revert_token(self, change_id: str, token: str) -> None:
        self._update_change_field(change_id, "revert_token", token)
    
    def update_summary_json(self, change_id: str, summary_json: dict) -> None:
        self._update_change_field(change_id, "summary_json", summary_json)
    
    def set_change_approved(self, change_id: str, approved: bool) -> None:
        # For Redis we rewrite the whole record similar to other helpers
        change = self.get_change(change_id)
        if change:
            if approved:
                change["requires_approval"] = 0
            ttl = self.redis.ttl(f"changes:{change_id}")
            self.save_change(change_id, change, ttl if ttl > 0 else 3600)

    def run_gc(self) -> None:
        # No-op for Redis, as we rely on TTL for expiration
        print("GC: Redis TTL handles expiration.")
        return


# Global storage instance, to be initialized on app startup
storage: Storage = None

def get_storage() -> Storage:
    global storage
    if storage is None:
        # Auto-detect from DATABASE_URL (same logic as db_adapter.py)
        db_url = os.getenv("DATABASE_URL", "")
        backend = os.getenv("SR_STORAGE_BACKEND", "").lower()
        
        if backend == "redis":
            # Explicit redis backend
            redis_url = os.getenv("SR_REDIS_URL")
            if not redis_url:
                raise ValueError("SR_REDIS_URL must be set for Redis storage backend")
            storage = RedisStorage(url=redis_url)
        elif db_url.startswith("postgres"):
            # Auto-detect PostgreSQL from DATABASE_URL
            # SqliteStorage works with both SQLite and PostgreSQL via db_adapter
            storage = SqliteStorage()
        else:
            # Default SQLite
            sqlite_path = os.getenv("SR_SQLITE_PATH")
            if sqlite_path:
                db.reload_db_path(sqlite_path)
            storage = SqliteStorage()
    return storage
