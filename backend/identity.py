"""Identity behavior endpoints (local-only event ingestion + stats)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .behavior_store import behavior_enabled, log_behavior, recent_stats

router = APIRouter()


class BehaviorEvent(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    metrics: dict[str, Any] = Field(default_factory=dict)
    client_ts: float | None = None


class BehaviorIngestReq(BaseModel):
    events: list[BehaviorEvent] = Field(default_factory=list)


@router.get("/api/identity/status")
def identity_status():
    return {"enabled": behavior_enabled()}


@router.get("/api/identity/stats")
def identity_stats(window_seconds: int = 60 * 60 * 24 * 14):
    return recent_stats(window_seconds=window_seconds)


@router.post("/api/identity/events")
def identity_events(req: BehaviorIngestReq):
    if not behavior_enabled():
        return {"ok": False, "enabled": False, "written": 0}
    written = 0
    for event in req.events[:500]:
        payload = dict(event.metrics)
        if event.client_ts is not None:
            payload["client_ts"] = event.client_ts
        log_behavior(event.source, event.action, payload)
        written += 1
    return {"ok": True, "enabled": True, "written": written}

