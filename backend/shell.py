"""Shell execution route."""
from __future__ import annotations

import subprocess
import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from .behavior_store import log_behavior

router = APIRouter()


class ShellReq(BaseModel):
    command: str
    cwd: Optional[str] = None


@router.post("/api/run_shell")
def run_shell(req: ShellReq):
    started = time.time()
    try:
        r = subprocess.run(
            req.command, shell=True, capture_output=True,
            text=True, timeout=30, cwd=req.cwd,
        )
        output = (r.stdout + r.stderr).rstrip()
        log_behavior(
            "shell",
            "run_shell",
            {
                "command_len": len(req.command),
                "command_words": len(req.command.split()),
                "cwd_len": len(req.cwd or ""),
                "duration_ms": int((time.time() - started) * 1000),
                "exit_code": r.returncode,
                "output_len": len(output),
            },
        )
        return {"output": output, "code": r.returncode}
    except subprocess.TimeoutExpired:
        log_behavior(
            "shell",
            "run_shell_timeout",
            {
                "command_len": len(req.command),
                "command_words": len(req.command.split()),
                "cwd_len": len(req.cwd or ""),
                "duration_ms": int((time.time() - started) * 1000),
            },
        )
        return {"output": "Command timed out after 30s", "code": -1}
    except Exception as e:
        log_behavior(
            "shell",
            "run_shell_error",
            {
                "command_len": len(req.command),
                "command_words": len(req.command.split()),
                "cwd_len": len(req.cwd or ""),
                "duration_ms": int((time.time() - started) * 1000),
            },
        )
        return {"output": str(e), "code": -1}
