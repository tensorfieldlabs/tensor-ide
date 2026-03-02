"""Groq provider — OpenAI-compatible API, key at ~/.tensor/groq_key."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import httpx

from . import Provider, sse_delta, sse_tool_start, sse_tool_end, _smart_truncate

_KEY_PATH = Path.home() / ".tensor" / "groq_key"
_API_BASE = "https://api.groq.com/openai/v1"

_MODELS = [
    "moonshotai/kimi-k2-instruct",
    "qwen/qwen3-32b",
    "deepseek-r1-distill-llama-70b",
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
    "gemma2-9b-it",
]


def _load_key() -> str | None:
    if not _KEY_PATH.exists():
        return None
    key = _KEY_PATH.read_text().strip()
    return key if key else None


def _headers(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


class GroqProvider(Provider):
    name = "groq"

    def is_available(self) -> bool:
        return _load_key() is not None

    def get_models(self) -> list[str]:
        if not self.is_available():
            return []
        key = _load_key()
        try:
            resp = httpx.get(f"{_API_BASE}/models", headers=_headers(key), timeout=10.0)
            resp.raise_for_status()
            models = [m["id"] for m in resp.json().get("data", [])
                      if m.get("id")
                      and m.get("context_window", 0) >= 1000
                      and "guard" not in m["id"].lower()
                      and "orpheus" not in m["id"].lower()
                      and "compound" not in m["id"].lower()]
            models.sort()
            return models if models else list(_MODELS)
        except Exception:
            return list(_MODELS)

    def generate(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> str:
        result = []
        for chunk in self.generate_stream(prompt, system, max_tokens, temperature, model_name):
            if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                try:
                    result.append(json.loads(chunk[6:]).get("delta", ""))
                except Exception:
                    pass
        return "".join(result) or "Error: Empty Groq response."

    def generate_stream(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> Iterator[str]:
        key = _load_key()
        if not key:
            yield sse_delta("Error: No Groq API key found.")
            return

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if temperature > 0:
            payload["temperature"] = temperature

        try:
            with httpx.stream("POST", f"{_API_BASE}/chat/completions",
                              headers=_headers(key), json=payload, timeout=120.0) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        text = chunk["choices"][0]["delta"].get("content", "")
                        if text:
                            yield sse_delta(text)
                    except Exception:
                        pass
        except httpx.HTTPStatusError as e:
            yield sse_delta(f"\nGroq API error ({e.response.status_code}): {e.response.text[:300]}\n")
        except Exception as e:
            yield sse_delta(f"\nError communicating with Groq: {e}\n")

    def generate_stream_with_tools(self, messages_or_prompt, system: str, max_tokens: int,
                                    temperature: float, model_name: str,
                                    tools: list[dict], tool_executor) -> Iterator[str]:
        """Stream with OpenAI-compatible function calling."""
        key = _load_key()
        if not key:
            yield sse_delta("Error: No Groq API key found.")
            return

        if isinstance(messages_or_prompt, list):
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            for m in messages_or_prompt:
                role = m.get("role", "user")
                content = m.get("content", "")
                if isinstance(content, list):
                    text = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                else:
                    text = str(content)
                if text:
                    messages.append({"role": role, "content": text})
        else:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": messages_or_prompt})

        api_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("inputSchema", {"type": "object"}),
                },
            }
            for t in tools
        ] if tools else []

        for _ in range(5):
            payload: dict = {
                "model": model_name,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True,
            }
            if temperature > 0:
                payload["temperature"] = temperature
            if api_tools:
                payload["tools"] = api_tools

            text_accum = ""
            tool_calls: dict[int, dict] = {}  # index → {id, name, arguments}

            try:
                with httpx.stream("POST", f"{_API_BASE}/chat/completions",
                                  headers=_headers(key), json=payload, timeout=120.0) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except Exception:
                            continue
                        delta = chunk["choices"][0]["delta"]

                        if delta.get("content"):
                            text_accum += delta["content"]
                            yield sse_delta(delta["content"])

                        for tc in delta.get("tool_calls", []):
                            idx = tc["index"]
                            if idx not in tool_calls:
                                tool_calls[idx] = {"id": tc.get("id", ""), "name": "", "arguments": ""}
                            if tc.get("id"):
                                tool_calls[idx]["id"] = tc["id"]
                            fn = tc.get("function", {})
                            if fn.get("name"):
                                tool_calls[idx]["name"] = fn["name"]
                                yield sse_tool_start(fn["name"], {})
                            if fn.get("arguments"):
                                tool_calls[idx]["arguments"] += fn["arguments"]

            except httpx.HTTPStatusError as e:
                yield sse_delta(f"\nGroq API error ({e.response.status_code}): {e.response.text[:300]}\n")
                return
            except Exception as e:
                yield sse_delta(f"\nError communicating with Groq: {e}\n")
                return

            if not tool_calls:
                return

            # Add assistant turn
            assistant_msg: dict = {"role": "assistant", "content": text_accum or None, "tool_calls": []}
            for idx in sorted(tool_calls):
                tc = tool_calls[idx]
                assistant_msg["tool_calls"].append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                })
            messages.append(assistant_msg)

            # Execute tools
            for idx in sorted(tool_calls):
                tc = tool_calls[idx]
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                result = tool_executor(tc["name"], args)
                preview = result[:200] if result.startswith("IMAGE:") else result
                yield sse_tool_end(tc["name"], preview, path=args.get("path"))
                if result.startswith("IMAGE:"):
                    content = f"[screenshot captured — {len(result)-6} bytes]"
                else:
                    content = _smart_truncate(result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": content,
                })
            text_accum = ""
