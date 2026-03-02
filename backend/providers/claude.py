"""Anthropic Claude provider — uses OAuth token from ~/.claude/.credentials.json.

Native tool calling via Claude tool_use blocks, matching the pattern used by
the Codex and Gemini providers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import httpx

from . import Provider, sse_delta, sse_tool_start, sse_tool_end, sse_thinking_delta, _smart_truncate

_CREDS_PATH = Path.home() / ".claude" / ".credentials.json"
_API_BASE = "https://api.anthropic.com"

_MODELS = [
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
]

def _load_token() -> str | None:
    if not _CREDS_PATH.exists():
        return None
    try:
        data = json.loads(_CREDS_PATH.read_text())
        return data.get("claudeAiOauth", {}).get("accessToken")
    except Exception:
        return None


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
        "content-type": "application/json",
    }


class ClaudeProvider(Provider):
    name = "claude"

    def is_available(self) -> bool:
        return _load_token() is not None

    def get_models(self) -> list[str]:
        if not self.is_available():
            return []
        return list(_MODELS)

    def generate(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> str:
        token = _load_token()
        if not token:
            return "Error: No Claude credentials found."

        payload: dict = {
            "model": model_name,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        if temperature > 0:
            payload["temperature"] = temperature

        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(f"{_API_BASE}/v1/messages", headers=_headers(token), json=payload)
                resp.raise_for_status()
                data = resp.json()
                parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
                return "".join(parts) if parts else "Error: Empty Claude response."
        except httpx.HTTPStatusError as e:
            return f"Error from Claude API ({e.response.status_code}): {e.response.text}"
        except Exception as e:
            return f"Error communicating with Claude: {e}"

    def generate_stream(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> Iterator[str]:
        token = _load_token()
        if not token:
            yield sse_delta("Error: No Claude credentials found.")
            return

        payload: dict = {
            "model": model_name,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        if temperature > 0:
            payload["temperature"] = temperature

        try:
            with httpx.stream("POST", f"{_API_BASE}/v1/messages", headers=_headers(token), json=payload, timeout=120.0) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except Exception:
                        continue
                    etype = event.get("type", "")
                    if etype == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield sse_delta(delta.get("text", ""))
                    elif etype == "message_stop":
                        break
        except httpx.HTTPStatusError as e:
            yield sse_delta(f"\nClaude API error ({e.response.status_code}): {e.response.text}\n")
        except Exception as e:
            yield sse_delta(f"\nError communicating with Claude: {e}\n")

    def generate_stream_with_tools(self, messages: list[dict], system: str,
                                    max_tokens: int, temperature: float,
                                    model_name: str, tools: list[dict],
                                    tool_executor) -> Iterator[str]:
        """Stream with native Claude tool_use blocks.

        `messages` is a pre-built list of {"role": ..., "content": ...} dicts
        from Conversation.build_messages().
        """
        token = _load_token()
        if not token:
            yield sse_delta("Error: No Claude credentials found.")
            return

        # Convert tool defs from MCP format (inputSchema) to Claude format (input_schema)
        claude_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t.get("inputSchema", t.get("input_schema", {"type": "object"})),
            }
            for t in tools
        ] if tools else []

        for _ in range(5):
            payload: dict = {
                "model": model_name,
                "max_tokens": max_tokens,
                "stream": True,
                "messages": messages,
            }
            if claude_tools:
                payload["tools"] = claude_tools
            if system:
                payload["system"] = system
            if temperature > 0:
                payload["temperature"] = temperature

            text_accum = ""
            tool_uses: list[dict] = []
            current_tool: dict | None = None
            current_tool_json = ""

            try:
                with httpx.stream("POST", f"{_API_BASE}/v1/messages", headers=_headers(token), json=payload, timeout=120.0) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:])
                        except Exception:
                            continue

                        etype = event.get("type", "")

                        if etype == "content_block_start":
                            block = event.get("content_block", {})
                            if block.get("type") == "tool_use":
                                current_tool = {"id": block["id"], "name": block["name"], "input": {}}
                                current_tool_json = ""
                                yield sse_tool_start(block["name"], {})

                        elif etype == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text_accum += delta.get("text", "")
                                yield sse_delta(delta.get("text", ""))
                            elif delta.get("type") == "thinking_delta":
                                yield sse_thinking_delta(delta.get("thinking", ""))
                            elif delta.get("type") == "input_json_delta":
                                current_tool_json += delta.get("partial_json", "")

                        elif etype == "content_block_stop":
                            if current_tool:
                                try:
                                    current_tool["input"] = json.loads(current_tool_json) if current_tool_json else {}
                                except json.JSONDecodeError:
                                    current_tool["input"] = {}
                                tool_uses.append(current_tool)
                                current_tool = None
                                current_tool_json = ""

                        elif etype == "message_stop":
                            break

            except httpx.HTTPStatusError as e:
                yield sse_delta(f"\nClaude API error ({e.response.status_code}): {e.response.text}\n")
                return
            except Exception as e:
                yield sse_delta(f"\nError communicating with Claude: {e}\n")
                return

            if not tool_uses:
                break

            # Build assistant message with tool_use blocks
            assistant_content = []
            if text_accum:
                assistant_content.append({"type": "text", "text": text_accum})
            for tu in tool_uses:
                assistant_content.append({"type": "tool_use", "id": tu["id"], "name": tu["name"], "input": tu["input"]})
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tools and send results back
            tool_results = []
            for tu in tool_uses:
                args = tu.get("input", {})
                result = tool_executor(tu["name"], args)
                preview = result[:200] if result.startswith("IMAGE:") else result
                yield sse_tool_end(tu["name"], preview, path=args.get("path"))
                # Handle image tool results (base64 PNG from browser_screenshot)
                if result.startswith("IMAGE:"):
                    b64_data = result[6:]
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64_data}},
                        ],
                    })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": _smart_truncate(result),
                    })
            messages.append({"role": "user", "content": tool_results})
            text_accum = ""
