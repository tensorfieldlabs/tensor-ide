"""AI generation routes — supports multi-turn conversations with auto-compression."""
from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .model import generate, generate_stream, get_models
from .conversation import ConversationManager

router = APIRouter()
conversations = ConversationManager()


@router.get("/api/models")
def api_models():
    return {"models": get_models()}


@router.get("/api/conversations")
def api_list_conversations():
    return {"conversations": conversations.list_all()}


@router.get("/api/conversations/{conv_id}")
def api_get_conversation(conv_id: str):
    conv = conversations.get(conv_id)
    return {
        "id": conv_id,
        "turns": [{"role": t.role, "text": t.text} for t in conv.turns],
    }


@router.delete("/api/conversations/{conv_id}")
def api_clear_conversation(conv_id: str):
    conversations.clear(conv_id)
    return {"ok": True}


class GenerateReq(BaseModel):
    prompt: str
    max_tokens: int = 2048
    temperature: float = 0.0
    use_cloud: bool = True
    model: str = "claude-sonnet-4-6"
    conversation_id: str | None = None


@router.post("/api/generate")
def api_generate(req: GenerateReq):
    return {"result": generate(req.prompt, req.max_tokens, req.temperature, req.use_cloud, req.model)}


@router.post("/api/generate/stream")
def api_generate_stream(req: GenerateReq):
    conv_id = req.conversation_id or "default"
    conv = conversations.get(conv_id)
    conv.add_user(req.prompt)

    # Build structured messages for providers that support it
    structured_messages = conv.build_messages(query=req.prompt)

    def stream_and_capture():
        accumulated = ""
        for chunk in generate_stream(
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            use_cloud=req.use_cloud,
            model_name=req.model,
            messages=structured_messages,
        ):
            yield chunk
            # Capture text deltas to save assistant response
            if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                try:
                    delta = json.loads(chunk[6:]).get("delta", "")
                    accumulated += delta
                except Exception:
                    pass
        if accumulated:
            conv.add_assistant(accumulated)

    return StreamingResponse(
        stream_and_capture(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
