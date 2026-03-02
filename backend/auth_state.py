"""Shared in-memory auth session state with rate limiting."""
from __future__ import annotations

import secrets
import time
from threading import Lock

_SESSION_TTL_SECONDS = 60 * 60 * 12  # 12 hours
_SESSIONS: dict[str, float] = {}     # token -> expiry timestamp
_LOCK = Lock()

# ── Rate limiting for login attempts ─────────────────────────────
_LOGIN_WINDOW = 300       # 5-minute window
_LOGIN_MAX_ATTEMPTS = 5   # max attempts per IP per window
_LOCKOUT_DURATION = 900   # 15-minute lockout after exceeding limit
# ip -> list of timestamps
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
# ip -> lockout-until timestamp
_LOCKOUTS: dict[str, float] = {}


def configure_session_ttl(seconds: int) -> None:
    global _SESSION_TTL_SECONDS
    _SESSION_TTL_SECONDS = max(60, int(seconds))


def _prune(now: float | None = None) -> None:
    if now is None:
        now = time.time()
    expired = [token for token, expiry in _SESSIONS.items() if expiry <= now]
    for token in expired:
        _SESSIONS.pop(token, None)


def mint_session() -> str:
    with _LOCK:
        _prune()
        token = secrets.token_urlsafe(32)
        _SESSIONS[token] = time.time() + _SESSION_TTL_SECONDS
        return token


def is_valid_session(token: str | None) -> bool:
    if not token:
        return False
    with _LOCK:
        _prune()
        expiry = _SESSIONS.get(token)
        if not expiry:
            return False
        if expiry <= time.time():
            _SESSIONS.pop(token, None)
            return False
        return True


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with _LOCK:
        _SESSIONS.pop(token, None)


# ── Rate limiting ────────────────────────────────────────────────

def check_rate_limit(ip: str) -> tuple[bool, int]:
    """Check if an IP is allowed to attempt login.

    Returns (allowed, retry_after_seconds).
    """
    now = time.time()
    with _LOCK:
        # Check lockout
        lockout_until = _LOCKOUTS.get(ip, 0)
        if now < lockout_until:
            return False, int(lockout_until - now)

        # Clean old lockout
        if ip in _LOCKOUTS and now >= lockout_until:
            _LOCKOUTS.pop(ip, None)

        # Prune old attempts outside the window
        attempts = _LOGIN_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if t > now - _LOGIN_WINDOW]
        _LOGIN_ATTEMPTS[ip] = attempts

        if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
            # Lock them out
            _LOCKOUTS[ip] = now + _LOCKOUT_DURATION
            _LOGIN_ATTEMPTS.pop(ip, None)
            return False, _LOCKOUT_DURATION

        return True, 0


def record_login_attempt(ip: str) -> None:
    """Record a failed login attempt for rate limiting."""
    now = time.time()
    with _LOCK:
        if ip not in _LOGIN_ATTEMPTS:
            _LOGIN_ATTEMPTS[ip] = []
        _LOGIN_ATTEMPTS[ip].append(now)


def clear_login_attempts(ip: str) -> None:
    """Clear attempts after successful login."""
    with _LOCK:
        _LOGIN_ATTEMPTS.pop(ip, None)
        _LOCKOUTS.pop(ip, None)
