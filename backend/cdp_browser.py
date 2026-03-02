"""Headless Chromium manager with CDP screencast streaming.

Launches a dedicated Chromium instance on a fixed CDP port.
Streams live JPEG frames to connected frontend WebSocket clients.
AI tools connect via playwright.chromium.connect_over_cdp().
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import urllib.request
from pathlib import Path
from typing import Set

import websockets

# Playwright's bundled Chromium (macOS arm64)
_CHROMIUM_CANDIDATES = [
    Path.home() / "Library/Caches/ms-playwright/chromium-1208/chrome-mac-arm64"
    / "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    # Fallback: find any playwright chromium
]

_CDP_PORT = 9222


def _find_chromium() -> Path:
    for p in _CHROMIUM_CANDIDATES:
        if p.exists():
            return p
    # Try to find via glob
    base = Path.home() / "Library/Caches/ms-playwright"
    for candidate in base.glob("chromium-*/chrome-mac-arm64/Google Chrome for Testing.app"
                               "/Contents/MacOS/Google Chrome for Testing"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Chromium not found. Run: playwright install chromium")


class CDPBrowser:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._ws = None
        self._clients: Set = set()
        self._msg_id = 0
        self._receive_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._started = False

    async def start(self):
        async with self._lock:
            if self._started:
                return
            chromium = _find_chromium()
            self._proc = subprocess.Popen(
                [
                    str(chromium),
                    f"--remote-debugging-port={_CDP_PORT}",
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1440,900",
                    "--user-data-dir=/tmp/tensor-cdp-profile",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Wait for Chromium to be ready
            for _ in range(20):
                await asyncio.sleep(0.2)
                try:
                    self._ws = await self._open_cdp_ws()
                    break
                except Exception:
                    continue
            else:
                raise RuntimeError("Chromium CDP not ready after 4s")

            await self._send("Page.enable")
            await self._send("Page.startScreencast", {
                "format": "jpeg",
                "quality": 75,
                "maxWidth": 1280,
                "maxHeight": 800,
                "everyNthFrame": 1,
            })
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._started = True
            print(f"[cdp] Chromium started, streaming on CDP port {_CDP_PORT}")

    async def _open_cdp_ws(self):
        with urllib.request.urlopen(f"http://localhost:{_CDP_PORT}/json", timeout=2) as r:
            targets = json.loads(r.read())
        page = next((t for t in targets if t["type"] == "page"), None)
        if not page:
            raise RuntimeError("No page target")
        return await websockets.connect(
            page["webSocketDebuggerUrl"],
            max_size=20_000_000,
        )

    async def _send(self, method: str, params: dict | None = None):
        self._msg_id += 1
        msg: dict = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        await self._ws.send(json.dumps(msg))

    async def _receive_loop(self):
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                if data.get("method") == "Page.screencastFrame":
                    p = data["params"]
                    # Ack immediately so Chromium keeps sending
                    await self._send("Page.screencastFrameAck", {"sessionId": p["sessionId"]})
                    await self._broadcast(p["data"])
        except Exception as e:
            print(f"[cdp] receive loop ended: {e}")

    async def _broadcast(self, frame_b64: str):
        dead: Set = set()
        for client in list(self._clients):
            try:
                await client.send_text(frame_b64)
            except Exception:
                dead.add(client)
        self._clients -= dead

    def add_client(self, ws):
        self._clients.add(ws)

    def remove_client(self, ws):
        self._clients.discard(ws)

    async def broadcast_control(self, cmd: str):
        """Send a control message (e.g. 'CMD:OPEN') to all frontend clients."""
        dead: Set = set()
        for client in list(self._clients):
            try:
                await client.send_text(f"CMD:{cmd}")
            except Exception:
                dead.add(client)
        self._clients -= dead

    @property
    def cdp_url(self) -> str:
        return f"http://localhost:{_CDP_PORT}"

    async def stop(self):
        if self._receive_task:
            self._receive_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._proc:
            self._proc.terminate()
        self._started = False


# Singleton
cdp_browser = CDPBrowser()
