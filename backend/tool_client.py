"""MCP tool client — connects to our own MCP server to discover and call tools.

This is the bridge between the AI model router and the MCP tool server.
Tools are discovered dynamically via tools/list and executed via tools/call.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


class ToolClient:
    """Manages an MCP client session to our tool server."""

    def __init__(self):
        self._tools: list[dict] = []
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: ClientSession | None = None
        self._read = None
        self._write = None
        self._cm = None
        self._session_cm = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        """Start the MCP server subprocess and connect in a background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=15)

    def _run_loop(self):
        import time
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        delay = 3
        while True:
            try:
                self._loop.run_until_complete(self._connect())
            except Exception as e:
                print(f"[mcp-client] connection lost: {e}, restarting in {delay}s")
                self._session = None
                self._ready.clear()
                time.sleep(delay)
                delay = min(delay * 2, 30)
                self._ready.set()

    async def _connect(self):
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "backend.mcp_server"],
        )
        self._cm = stdio_client(server_params)
        self._read, self._write = await self._cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()

        # Discover tools
        result = await self._session.list_tools()
        self._tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema if hasattr(t, 'inputSchema') else {"type": "object"},
            }
            for t in result.tools
        ]
        print(f"[mcp-client] Discovered {len(self._tools)} tools: {[t['name'] for t in self._tools]}")
        self._ready.set()

        # Keep the loop alive
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    @property
    def tools(self) -> list[dict]:
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool synchronously (blocks until result)."""
        if not self._session or not self._loop:
            return f"Error: MCP client not connected"
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments),
            self._loop,
        )
        try:
            result = future.result(timeout=30)
            # Extract text from content blocks
            parts = []
            for block in result.content:
                if hasattr(block, 'text'):
                    parts.append(block.text)
            return "\n".join(parts) if parts else "(empty result)"
        except Exception as e:
            return f"Error calling tool {name}: {e}"

    # ── Format converters for each provider ──────────────────────

    def tools_for_claude(self) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["inputSchema"],
            }
            for t in self._tools
        ]

    def tools_for_openai(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"],
                },
            }
            for t in self._tools
        ]

    def tools_for_gemini(self) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            }
            for t in self._tools
        ]


# Singleton
_client: ToolClient | None = None


def get_tool_client() -> ToolClient:
    global _client
    if _client is None:
        _client = ToolClient()
        _client.start()
    return _client
