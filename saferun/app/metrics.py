from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from contextlib import contextmanager
import time

REQUESTS = Counter("saferun_requests_total", "Requests count", ["provider", "action"])
LATENCY  = Histogram("saferun_latency_seconds", "Operation latency", ["provider", "action"])
CHANGES  = Counter("saferun_changes_total", "Changes by status", ["status"])

# Ensure histogram series exists so *_count appears in exposition even before first request
try:
    LATENCY.labels("bootstrap", "init").observe(0.0)
except Exception:
    pass

def render_latest():
    return generate_latest(), CONTENT_TYPE_LATEST

@contextmanager
def _timer(provider: str, action: str):
    t0 = time.time()
    try:
        yield
    finally:
        LATENCY.labels(provider, action).observe(time.time() - t0)
        REQUESTS.labels(provider, action).inc()

def time_dryrun(provider: str):  return _timer(provider, "dryrun")
def time_apply(provider: str):   return _timer(provider, "apply")
def time_revert(provider: str):  return _timer(provider, "revert")

def record_change_status(status: str) -> None:
    try:
        CHANGES.labels(status=status).inc()
    except Exception:
        # best-effort; avoid breaking main flow if metrics fail
        pass
