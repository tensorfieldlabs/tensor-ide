"""Local behavior event storage for identity/risk signals."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

# Privacy-first default: disabled unless explicitly enabled.
_BEHAVIOR_ENABLED = os.environ.get("TENSOR_BEHAVIOR_LOGGING", "0").lower() in {"1", "true", "yes"}
_BASE_DIR = Path.home() / ".tensor" / "identity"
_EVENTS_FILE = _BASE_DIR / "events.jsonl"
_LOCK = threading.Lock()


def behavior_enabled() -> bool:
    return _BEHAVIOR_ENABLED


def events_file() -> Path:
    return _EVENTS_FILE


def _safe_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in metrics.items():
        if value is None:
            continue
        if isinstance(value, (int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, str):
            cleaned[key] = value[:256]
        else:
            cleaned[key] = str(value)[:256]
    return cleaned


def log_behavior(source: str, action: str, metrics: dict[str, Any] | None = None) -> None:
    if not _BEHAVIOR_ENABLED:
        return
    payload = {
        "ts": time.time(),
        "source": source,
        "action": action,
        "metrics": _safe_metrics(metrics or {}),
    }
    _BASE_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, separators=(",", ":"))
    with _LOCK:
        with _EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")


def recent_stats(window_seconds: int = 60 * 60 * 24 * 14) -> dict[str, Any]:
    now = time.time()
    cutoff = now - max(1, window_seconds)
    counts_by_source: dict[str, int] = {}
    counts_by_action: dict[str, int] = {}
    total = 0
    first_ts: float | None = None
    last_ts: float | None = None
    if not _EVENTS_FILE.exists():
        return {
            "enabled": _BEHAVIOR_ENABLED,
            "total_events": 0,
            "window_seconds": window_seconds,
            "counts_by_source": counts_by_source,
            "counts_by_action": counts_by_action,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "path": str(_EVENTS_FILE),
        }
    with _EVENTS_FILE.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            ts = float(row.get("ts", 0))
            if ts < cutoff:
                continue
            source = str(row.get("source", "unknown"))
            action = str(row.get("action", "unknown"))
            counts_by_source[source] = counts_by_source.get(source, 0) + 1
            counts_by_action[action] = counts_by_action.get(action, 0) + 1
            total += 1
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
    return {
        "enabled": _BEHAVIOR_ENABLED,
        "total_events": total,
        "window_seconds": window_seconds,
        "counts_by_source": counts_by_source,
        "counts_by_action": counts_by_action,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "path": str(_EVENTS_FILE),
    }
