"""Unified model router — dispatches to Claude, Gemini, Groq, or Ollama."""
from __future__ import annotations

import json
from typing import Iterator

from .providers import sse_delta, sse_done, sse_tool_start, sse_tool_end, _smart_truncate
from .providers.claude import ClaudeProvider
from .providers.gemini import GeminiProvider
from .providers.groq import GroqProvider
from .providers.ollama import OllamaProvider
from .tool_client import get_tool_client

# --- Provider registry ---

_claude = ClaudeProvider()
_gemini = GeminiProvider()
_groq = GroqProvider()
_local = OllamaProvider()

_ALL_PROVIDERS = [_claude, _gemini, _groq, _local]

_GROQ_PREFIXES = ("llama", "meta-llama/", "deepseek-r1-distill", "gemma", "moonshotai/", "qwen/", "mixtral", "compound", "canopy", "gpt-", "whisper")


def _route(model_name: str):
    if model_name.startswith("claude-"):
        return _claude
    if model_name.startswith("gemini-"):
        return _gemini
    if model_name.startswith("local/"):
        return _local
    if any(model_name.startswith(p) for p in _GROQ_PREFIXES):
        return _groq
    return _claude  # default


_FALLBACK_MODELS = [
    "claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001",
    "gemini-2.5-pro", "gemini-2.5-flash",
]


def get_models() -> list[dict]:
    result = []
    for p in _ALL_PROVIDERS:
        try:
            if p.is_available():
                for m in p.get_models():
                    result.append({"id": m, "provider": p.name})
        except Exception as e:
            print(f"[router] Error fetching models from {p.name}: {e}")
    if not result:
        return [{"id": m, "provider": _route(m).name} for m in _FALLBACK_MODELS]
    return result


def generate(prompt: str, max_tokens: int = 2048, temperature: float = 0.0,
             use_cloud: bool = True, model_name: str = "claude-sonnet-4-6") -> str:
    provider = _route(model_name)
    tc = get_tool_client()
    return provider.generate(prompt, _build_system_prompt(model_name, tc), max_tokens, temperature, model_name)


def generate_stream(prompt: str = "", max_tokens: int = 2048, temperature: float = 0.0,
                    use_cloud: bool = True, model_name: str = "claude-sonnet-4-6",
                    messages: list[dict] | None = None) -> Iterator[str]:
    provider = _route(model_name)
    tc = get_tool_client()
    sys_prompt = _build_system_prompt(model_name, tc)
    tools = tc.tools if tc else []

    def tool_executor(name: str, args: dict) -> str:
        return tc.call_tool(name, args)

    # ── Claude: native tool_use ───────────────────────────────────
    if model_name.startswith("claude-"):
        msgs = messages if messages else [{"role": "user", "content": prompt}]
        yield from provider.generate_stream_with_tools(
            msgs, sys_prompt, max_tokens, temperature, model_name, tools, tool_executor)
        yield sse_done()
        return

    # ── Gemini: native function calling ──────────────────────────
    if model_name.startswith("gemini-") and hasattr(provider, "generate_stream_with_tools") and tools:
        flat_prompt = _messages_to_prompt(messages) if messages else prompt
        yield from provider.generate_stream_with_tools(
            flat_prompt, sys_prompt, max_tokens, temperature, model_name, tools, tool_executor)
        yield sse_done()
        return

    # ── Groq: OpenAI-compatible function calling ──────────────────
    if any(model_name.startswith(p) for p in _GROQ_PREFIXES) and tools:
        yield from provider.generate_stream_with_tools(
            messages or prompt, sys_prompt, max_tokens, temperature, model_name, tools, tool_executor)
        yield sse_done()
        return

    # ── Local / fallback: text-based tool loop ────────────────────
    flat_prompt = _messages_to_prompt(messages) if messages else prompt
    conversation = [flat_prompt]
    for _ in range(5):
        current_prompt = "\n\n".join(conversation)
        full_response = ""
        for chunk in provider.generate_stream(current_prompt, sys_prompt, max_tokens, temperature, model_name):
            yield chunk
            if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                try:
                    delta = json.loads(chunk[6:]).get("delta", "")
                    full_response += delta
                except Exception:
                    pass

        tool_call = None
        for line in full_response.splitlines():
            line = line.strip()
            if line.startswith('{"tool"'):
                try:
                    tool_call = json.loads(line)
                    break
                except json.JSONDecodeError:
                    pass

        if not tool_call:
            break

        tool_name = tool_call.pop("tool", "unknown")
        yield sse_tool_start(tool_name, tool_call)
        result = tool_executor(tool_name, tool_call)
        yield sse_tool_end(tool_name, result)
        conversation.append(full_response)
        conversation.append(f"Tool result for {tool_name}:\n{_smart_truncate(result)}")

    yield sse_done()


def _messages_to_prompt(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        prefix = "User" if m["role"] == "user" else "Tensor"
        raw = m["content"]
        if isinstance(raw, str):
            content = raw
        elif isinstance(raw, list):
            text_parts = [b.get("text", "") for b in raw if isinstance(b, dict) and b.get("type") == "text"]
            content = " ".join(text_parts) if text_parts else "[multimodal content]"
        else:
            content = str(raw)
        parts.append(f"{prefix}: {content}")
    return "\n\n".join(parts)


_SYSTEM_PROMPT_BASE = """You are Tensor, a highly capable peer programmer.
You are professional, concise, and direct. You treat the user as an equal.

STRICT IDENTITY RULES:
- Your name is Tensor. Never refer to yourself as anything else.
- NEVER mention your underlying model architecture.
- Do not use emojis. Do not use overly enthusiastic or annoying conversational fillers."""

_TOOLS_ADDENDUM = """

You have tools available. Use them proactively when the user asks you to do anything that requires reading files, writing files, running commands, or searching. Do not say you cannot do something — use your tools."""


def _build_system_prompt(model_name: str, tc) -> str:
    has_tools = bool(tc and tc.tools)
    base = _SYSTEM_PROMPT_BASE + (_TOOLS_ADDENDUM if has_tools else "")
    if model_name.startswith(("claude-", "gemini-")) or any(model_name.startswith(p) for p in _GROQ_PREFIXES):
        return base
    tools = tc.tools if tc else []
    if not tools:
        return base
    tool_docs = "\n".join(f'- {t["name"]}: {t["description"]}' for t in tools)
    return base + f"""

AVAILABLE TOOLS:
{tool_docs}

To call a tool, output a JSON object on its own line:
{{"tool": "tool_name", "arg1": "value1", "arg2": "value2"}}

After you output a tool call, you will receive the result. Then continue your response.
Always use tools when the user asks to read, write, list, search, or run anything."""
