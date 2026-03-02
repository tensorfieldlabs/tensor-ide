#!/usr/bin/env python3
"""tensor-ide — entry point."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.files     import router as files_router
from backend.shell     import router as shell_router
from backend.terminal  import router as terminal_router
from backend.ai        import router as ai_router
from backend.auth_state import (
    check_rate_limit, clear_login_attempts,
    is_valid_session, mint_session, record_login_attempt, revoke_session,
)

PORT   = 41900
STATIC = Path(__file__).parent / "builds" / "static"

_ALLOWED_ORIGINS = [
    "http://localhost:41900",
    "http://127.0.0.1:41900",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://ide.reeshogue.com",
]

_PIN_FILE   = Path.home() / ".tensor" / "ide_pin"
_COOKIE     = "tensor_session"
_NO_AUTH    = {"/api/login", "/api/logout", "/api/auth_status", "/robots.txt"}

# ── PIN bootstrap ──────────────────────────────────────────────────────────────

def _load_pin() -> str:
    if _PIN_FILE.exists():
        return _PIN_FILE.read_text().strip()
    _PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    pin = secrets.token_hex(8)
    _PIN_FILE.write_text(pin)
    print(f"\n  [auth] generated PIN: {pin}\n  saved to {_PIN_FILE}\n", flush=True)
    return pin

_PIN = _load_pin()

# ── Auth middleware ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.cdp_browser import cdp_browser
    try:
        await cdp_browser.start()
    except Exception as e:
        print(f"[cdp] Failed to start browser: {e}")
    yield
    await cdp_browser.stop()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in _NO_AUTH or path.startswith("/assets/") or path.startswith("/ws/"):
        return await call_next(request)
    token = request.cookies.get(_COOKIE)
    if is_valid_session(token):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    # Let unauthenticated users reach the React app — it handles login UI
    return await call_next(request)


# ── Auth endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/login")
async def api_login(request: Request):
    ip = request.client.host if request.client else "unknown"
    allowed, retry_after = check_rate_limit(ip)
    if not allowed:
        return JSONResponse({"detail": f"too many attempts, retry in {retry_after}s"}, status_code=429)
    body = await request.json()
    pin = body.get("pin", "")
    if not hmac.compare_digest(
        hashlib.sha256(pin.encode()).digest(),
        hashlib.sha256(_PIN.encode()).digest(),
    ):
        record_login_attempt(ip)
        return JSONResponse({"detail": "incorrect PIN"}, status_code=401)
    clear_login_attempts(ip)
    token = mint_session()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(_COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 12)
    return resp


@app.post("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get(_COOKIE)
    revoke_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(_COOKIE)
    return resp


@app.get("/api/auth_status")
async def api_auth_status(request: Request):
    token = request.cookies.get(_COOKIE)
    return {"authed": is_valid_session(token)}


# ── App endpoints ──────────────────────────────────────────────────────────────

@app.get("/api/logo_version")
def api_logo_version():
    logo = STATIC / "tensor.svg"
    if not logo.exists():
        logo = Path(__file__).parent / "public" / "tensor.svg"
    version = str(logo.stat().st_mtime_ns) if logo.exists() else "0"
    return {"version": version}


@app.get("/robots.txt")
def robots():
    return Response(content="User-agent: *\nDisallow: /\n", media_type="text/plain")


app.include_router(files_router)
app.include_router(shell_router)
app.include_router(terminal_router)
app.include_router(ai_router)


@app.post("/api/browser/control")
async def api_browser_control(request: Request):
    data = await request.json()
    cmd = data.get("cmd", "")
    from backend.cdp_browser import cdp_browser
    await cdp_browser.broadcast_control(cmd)
    return {"ok": True}


@app.websocket("/ws/browser")
async def ws_browser(websocket: WebSocket):
    from backend.cdp_browser import cdp_browser
    await websocket.accept()
    cdp_browser.add_client(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        cdp_browser.remove_client(websocket)


if STATIC.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = STATIC / full_path
        if full_path and candidate.is_file() and candidate.resolve().is_relative_to(STATIC.resolve()):
            return FileResponse(candidate)
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
else:
    @app.get("/")
    def no_build():
        return {"error": "run: pnpm build"}


if __name__ == "__main__":
    print(f"\n  tensor-ide  http://0.0.0.0:{PORT}\n", flush=True)
    host = "0.0.0.0" if os.environ.get("DOCKER") else "127.0.0.1"
    uvicorn.run("main:app", host=host, port=PORT, reload=not os.environ.get("DOCKER"), reload_dirs=["backend"])
