"""File I/O routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

router = APIRouter()


class ReadReq(BaseModel):
    path: str

class WriteReq(BaseModel):
    path: str
    content: str

class ListReq(BaseModel):
    path: str


@router.post("/api/read_file")
def read_file(req: ReadReq):
    try:
        return {"content": Path(req.path).read_text(encoding="utf-8", errors="replace")}
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/write_file")
def write_file(req: WriteReq):
    try:
        p = Path(req.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(req.content, encoding="utf-8")
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/upload")
async def upload_files(dir: str = Form(...), files: list[UploadFile] = File(...)):
    saved = []
    errors = []
    dest = Path(dir)
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        try:
            safe_name = Path(f.filename).name if f.filename else "upload"
            out = dest / safe_name
            out.write_bytes(await f.read())
            saved.append(str(out))
        except Exception as e:
            errors.append({"name": f.filename, "error": str(e)})
    return {"saved": saved, "errors": errors}


@router.post("/api/list_dir")
def list_dir(req: ListReq):
    try:
        entries = [
            {"name": p.name, "path": str(p), "is_dir": p.is_dir()}
            for p in sorted(Path(req.path).iterdir(),
                            key=lambda x: (not x.is_dir(), x.name.lower()))
        ]
        return {"entries": entries}
    except Exception as e:
        return {"error": str(e)}
