#!/usr/bin/env python3
"""tensor-ide — entry point."""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from backend.files     import router as files_router
from backend.shell     import router as shell_router
from backend.terminal  import router as terminal_router
from backend.ai        import router as ai_router

PORT   = 41900
STATIC = Path(__file__).parent / "builds" / "static"

_ALLOWED_ORIGINS = [
    "http://localhost:41900",
    "http://127.0.0.1:41900",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


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
    allow_credentials=False,
)


@app.get("/api/logo_version")
def api_logo_version():
    logo = STATIC / "hogue.svg"
    if not logo.exists():
        logo = Path(__file__).parent / "public" / "hogue.svg"
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
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, reload=True, reload_dirs=["backend"])
