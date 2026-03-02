"""Provider base class and registry."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Iterator


class Provider(ABC):
    """Base class for AI model providers."""

    name: str

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if credentials exist and provider can be used."""

    @abstractmethod
    def get_models(self) -> list[str]:
        """Return list of model slugs this provider offers."""

    @abstractmethod
    def generate(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> str:
        """Single-shot generation. Returns full text."""

    @abstractmethod
    def generate_stream(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> Iterator[str]:
        """Streaming generation. Yields SSE lines: data: {"delta": "..."}\n\n"""


def sse_delta(text: str) -> str:
    """Format a text chunk as an SSE delta event."""
    return f"data: {json.dumps({'delta': text})}\n\n"


def sse_tool_start(tool_name: str, args: dict) -> str:
    return f"data: {json.dumps({'tool_start': tool_name, 'args': args})}\n\n"


def sse_tool_end(tool_name: str, result_preview: str, path: str | None = None) -> str:
    payload: dict = {'tool_end': tool_name, 'preview': result_preview[:2000]}
    if path:
        payload['path'] = path
    return f"data: {json.dumps(payload)}\n\n"


def sse_thinking(active: bool) -> str:
    return f"data: {json.dumps({'thinking': active})}\n\n"

def sse_thinking_delta(text: str) -> str:
    return f"data: {json.dumps({'thinking_delta': text})}\n\n"


def sse_done() -> str:
    return "data: [DONE]\n\n"


def _smart_truncate(text: str, limit: int = 16_000) -> str:
    """Truncate keeping start + end with a marker in the middle."""
    if len(text) <= limit:
        return text
    keep = limit - 60
    half = keep // 2
    return (
        text[:half]
        + "\n\n... [truncated — showing first and last portions] ...\n\n"
        + text[-half:]
    )
