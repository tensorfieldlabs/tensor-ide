"""PTY terminal WebSocket."""
from __future__ import annotations

import asyncio
import json
import os
import time

import ptyprocess
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .behavior_store import log_behavior

router = APIRouter()


@router.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket):
    await ws.accept()
    started = time.time()
    input_events = 0
    input_chars = 0
    output_bytes = 0
    last_input_at = started
    log_behavior(
        "terminal",
        "connect",
        {
            "has_session_query": bool(ws.query_params.get("session")),
        },
    )

    proc = ptyprocess.PtyProcess.spawn(
        [os.environ.get("SHELL", "/bin/zsh"), "-l"],
        cwd=os.path.expanduser("~"),
        env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"},
    )
    loop = asyncio.get_event_loop()

    async def read_pty():
        nonlocal output_bytes
        while proc.isalive():
            try:
                data = await loop.run_in_executor(None, proc.read, 4096)
                output_bytes += len(data)
                await ws.send_bytes(data)
            except Exception:
                break

    task = asyncio.create_task(read_pty())
    try:
        while True:
            msg = await ws.receive()
            if "bytes" in msg:
                payload = msg["bytes"] or b""
                input_events += 1
                input_chars += len(payload)
                now = time.time()
                log_behavior(
                    "terminal",
                    "input",
                    {
                        "chars": len(payload),
                        "delta_ms": int((now - last_input_at) * 1000),
                    },
                )
                last_input_at = now
                proc.write(payload)
            elif "text" in msg:
                d = json.loads(msg["text"])
                if d.get("type") == "resize":
                    log_behavior(
                        "terminal",
                        "resize",
                        {
                            "rows": int(d.get("rows", 0)),
                            "cols": int(d.get("cols", 0)),
                        },
                    )
                    proc.setwinsize(d["rows"], d["cols"])
                elif d.get("type") == "input":
                    payload_text = str(d.get("data", ""))
                    payload = payload_text.encode()
                    input_events += 1
                    input_chars += len(payload)
                    now = time.time()
                    log_behavior(
                        "terminal",
                        "input",
                        {
                            "chars": len(payload),
                            "newlines": payload_text.count("\n"),
                            "delta_ms": int((now - last_input_at) * 1000),
                        },
                    )
                    last_input_at = now
                    proc.write(payload)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        task.cancel()
        if proc.isalive():
            proc.terminate()
        log_behavior(
            "terminal",
            "disconnect",
            {
                "duration_ms": int((time.time() - started) * 1000),
                "input_events": input_events,
                "input_chars": input_chars,
                "output_bytes": output_bytes,
            },
        )
