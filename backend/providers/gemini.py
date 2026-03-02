"""Google Gemini provider — uses OAuth via Code Assist API.

Native function calling: tools defined as functionDeclarations,
functionCall parts in response, functionResponse parts sent back.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import httpx

from . import Provider, sse_delta, sse_tool_start, sse_tool_end, sse_thinking_delta, _smart_truncate

_CREDS_PATH = Path.home() / ".gemini" / "oauth_creds.json"
_CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
_CODE_ASSIST_VERSION = "v1internal"
_OAUTH_CLIENT_ID = ""      # set via ~/.gemini/client_id
_OAUTH_CLIENT_SECRET = ""  # set via ~/.gemini/client_secret

_MODEL_CANDIDATES = [
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-preview",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

_project_id: str | None = None
_access_token: str | None = None
_probed_models: list[str] | None = None


def _load_refresh_token() -> str | None:
    if not _CREDS_PATH.exists():
        return None
    try:
        data = json.loads(_CREDS_PATH.read_text())
        return data.get("refresh_token")
    except Exception:
        return None


def _refresh_access_token() -> str | None:
    global _access_token
    refresh_token = _load_refresh_token()
    if not refresh_token:
        return None
    try:
        resp = httpx.post("https://oauth2.googleapis.com/token", data={
            "client_id": _OAUTH_CLIENT_ID,
            "client_secret": _OAUTH_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=15.0)
        resp.raise_for_status()
        _access_token = resp.json().get("access_token")
        return _access_token
    except Exception as e:
        print(f"[gemini] Token refresh failed: {e}")
        return None


def _get_access_token() -> str | None:
    global _access_token
    if _access_token:
        return _access_token
    return _refresh_access_token()


def _ensure_project_id(token: str) -> str | None:
    global _project_id
    if _project_id:
        return _project_id
    try:
        resp = httpx.post(
            f"{_CODE_ASSIST_ENDPOINT}/{_CODE_ASSIST_VERSION}:loadCodeAssist",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"metadata": {"ideType": "IDE_UNSPECIFIED", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}},
            timeout=15.0,
        )
        resp.raise_for_status()
        _project_id = resp.json().get("cloudaicompanionProject")
        return _project_id
    except Exception as e:
        print(f"[gemini] loadCodeAssist failed: {e}")
        return None


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _probe_models() -> list[str]:
    """Probe which model names actually work on Code Assist."""
    global _probed_models
    if _probed_models is not None:
        return _probed_models
    token = _get_access_token()
    if not token:
        return list(_MODEL_CANDIDATES[:5])
    project_id = _ensure_project_id(token)
    if not project_id:
        return list(_MODEL_CANDIDATES[:5])
    available = []
    for m in _MODEL_CANDIDATES:
        try:
            payload = {
                "model": m, "project": project_id,
                "request": {"contents": [{"role": "user", "parts": [{"text": "hi"}]}],
                            "generationConfig": {"maxOutputTokens": 1}},
            }
            r = httpx.post(
                f"{_CODE_ASSIST_ENDPOINT}/{_CODE_ASSIST_VERSION}:generateContent",
                headers=_headers(token), json=payload, timeout=8.0,
            )
            # 200 = works, 429 = exists but rate-limited — both mean model is valid
            if r.status_code in (200, 429):
                available.append(m)
        except Exception:
            pass
    _probed_models = available if available else list(_MODEL_CANDIDATES[:5])
    print(f"[gemini] Available models: {_probed_models}")
    return _probed_models


def _build_payload(model_name: str, project_id: str, prompt: str, system: str,
                   max_tokens: int, temperature: float, tools: list[dict] | None = None,
                   contents: list[dict] | None = None) -> dict:
    if contents is None:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
    request: dict = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        request["systemInstruction"] = {"role": "user", "parts": [{"text": system}]}
    if temperature > 0:
        request["generationConfig"]["temperature"] = temperature
    # Native function calling: functionDeclarations
    if tools:
        request["tools"] = [{
            "functionDeclarations": [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("inputSchema", {"type": "object"}),
                }
                for t in tools
            ]
        }]
    return {
        "model": model_name,
        "project": project_id,
        "request": request,
    }


def _extract_text(response_json: dict) -> str:
    candidates = response_json.get("response", {}).get("candidates", [])
    parts_text = []
    for c in candidates:
        for p in c.get("content", {}).get("parts", []):
            if "text" in p and not p.get("thought"):
                parts_text.append(p["text"])
    return "".join(parts_text)


def _extract_function_calls(response_json: dict) -> list[dict]:
    """Extract functionCall parts from Gemini response."""
    calls = []
    candidates = response_json.get("response", response_json).get("candidates", [])
    for c in candidates:
        for p in c.get("content", {}).get("parts", []):
            if "functionCall" in p:
                fc = p["functionCall"]
                calls.append({"name": fc["name"], "args": fc.get("args", {})})
    return calls


class GeminiProvider(Provider):
    name = "gemini"

    def is_available(self) -> bool:
        return _load_refresh_token() is not None

    def get_models(self) -> list[str]:
        if not self.is_available():
            return []
        return _probe_models()

    def generate(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> str:
        token = _get_access_token()
        if not token:
            return "Error: No Gemini credentials found."
        project_id = _ensure_project_id(token)
        if not project_id:
            return "Error: Could not load Gemini project."
        payload = _build_payload(model_name, project_id, prompt, system, max_tokens, temperature)
        try:
            resp = httpx.post(
                f"{_CODE_ASSIST_ENDPOINT}/{_CODE_ASSIST_VERSION}:generateContent",
                headers=_headers(token), json=payload, timeout=120.0,
            )
            if resp.status_code == 401:
                token = _refresh_access_token()
                if not token:
                    return "Error: Gemini token refresh failed."
                resp = httpx.post(
                    f"{_CODE_ASSIST_ENDPOINT}/{_CODE_ASSIST_VERSION}:generateContent",
                    headers=_headers(token), json=payload, timeout=120.0,
                )
            resp.raise_for_status()
            return _extract_text(resp.json()) or "Error: Empty Gemini response."
        except Exception as e:
            return f"Error communicating with Gemini: {e}"

    def generate_stream_with_tools(self, prompt: str, system: str, max_tokens: int,
                                    temperature: float, model_name: str,
                                    tools: list[dict], tool_executor) -> Iterator[str]:
        """Stream with native Gemini function calling."""
        token = _get_access_token()
        if not token:
            yield sse_delta("Error: No Gemini credentials found.")
            return
        project_id = _ensure_project_id(token)
        if not project_id:
            yield sse_delta("Error: Could not load Gemini project.")
            return

        contents = [{"role": "user", "parts": [{"text": prompt}]}]

        for _ in range(5):
            payload = _build_payload(model_name, project_id, prompt, system,
                                     max_tokens, temperature, tools=tools, contents=contents)
            text_accum = ""
            fn_calls = []

            try:
                with httpx.stream(
                    "POST",
                    f"{_CODE_ASSIST_ENDPOINT}/{_CODE_ASSIST_VERSION}:streamGenerateContent",
                    params={"alt": "sse"},
                    headers=_headers(token),
                    json=payload,
                    timeout=120.0,
                ) as resp:
                    if resp.status_code == 401:
                        token = _refresh_access_token()
                        if not token:
                            yield sse_delta("Error: Gemini token refresh failed.")
                            return
                        # Retry with non-streaming for this round
                        payload_retry = _build_payload(model_name, project_id, prompt, system,
                                                        max_tokens, temperature, tools=tools, contents=contents)
                        r2 = httpx.post(
                            f"{_CODE_ASSIST_ENDPOINT}/{_CODE_ASSIST_VERSION}:generateContent",
                            headers=_headers(token), json=payload_retry, timeout=120.0,
                        )
                        r2.raise_for_status()
                        data = r2.json()
                        text_accum = _extract_text(data)
                        if text_accum:
                            yield sse_delta(text_accum)
                        fn_calls = _extract_function_calls(data)
                    else:
                        resp.raise_for_status()
                        for line in resp.iter_lines():
                            if not line.startswith("data: "):
                                continue
                            try:
                                data = json.loads(line[6:])
                            except Exception:
                                continue
                            candidates = data.get("response", data).get("candidates", [])
                            for c in candidates:
                                for p in c.get("content", {}).get("parts", []):
                                    if "text" in p:
                                        if p.get("thought"):
                                            yield sse_thinking_delta(p["text"])
                                        else:
                                            text_accum += p["text"]
                                            yield sse_delta(p["text"])
                                    elif "functionCall" in p:
                                        fc = p["functionCall"]
                                        fn_calls.append({"name": fc["name"], "args": fc.get("args", {})})

            except httpx.HTTPStatusError as e:
                yield sse_delta(f"\nGemini API error ({e.response.status_code}): {e.response.text[:300]}\n")
                return
            except Exception as e:
                yield sse_delta(f"\nError communicating with Gemini: {e}\n")
                return

            if not fn_calls:
                return

            # Add model response to contents
            model_parts = []
            if text_accum:
                model_parts.append({"text": text_accum})
            for fc in fn_calls:
                model_parts.append({"functionCall": {"name": fc["name"], "args": fc["args"]}})
            contents.append({"role": "model", "parts": model_parts})

            # Execute tools and send functionResponse back
            response_parts = []
            for fc in fn_calls:
                yield sse_tool_start(fc["name"], fc["args"])
                result = tool_executor(fc["name"], fc["args"])
                preview = result[:200] if result.startswith("IMAGE:") else result
                yield sse_tool_end(fc["name"], preview, path=fc["args"].get("path"))
                # Gemini: images go as inlineData in functionResponse
                if result.startswith("IMAGE:"):
                    b64_data = result[6:]
                    response_parts.append({
                        "functionResponse": {
                            "name": fc["name"],
                            "response": {"result": "Screenshot captured (image attached)"},
                        }
                    })
                    # Also append inline image as a separate user part
                    response_parts.append({
                        "inlineData": {"mimeType": "image/png", "data": b64_data},
                    })
                else:
                    response_parts.append({
                        "functionResponse": {
                            "name": fc["name"],
                            "response": {"result": _smart_truncate(result)},
                        }
                    })
            contents.append({"role": "user", "parts": response_parts})
            text_accum = ""

    def generate_stream(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> Iterator[str]:
        """Basic stream without tools."""
        token = _get_access_token()
        if not token:
            yield sse_delta("Error: No Gemini credentials found.")
            return
        project_id = _ensure_project_id(token)
        if not project_id:
            yield sse_delta("Error: Could not load Gemini project.")
            return
        payload = _build_payload(model_name, project_id, prompt, system, max_tokens, temperature)
        try:
            with httpx.stream(
                "POST",
                f"{_CODE_ASSIST_ENDPOINT}/{_CODE_ASSIST_VERSION}:streamGenerateContent",
                params={"alt": "sse"},
                headers=_headers(token), json=payload, timeout=120.0,
            ) as resp:
                if resp.status_code == 401:
                    token = _refresh_access_token()
                    if not token:
                        yield sse_delta("Error: Gemini token refresh failed.")
                        return
                    text = self.generate(prompt, system, max_tokens, temperature, model_name)
                    for w in text.split(" "):
                        yield sse_delta(w + " ")
                    return
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except Exception:
                        continue
                    candidates = data.get("response", {}).get("candidates", [])
                    for c in candidates:
                        for p in c.get("content", {}).get("parts", []):
                            if "text" in p:
                                yield sse_delta(p["text"])
        except httpx.HTTPStatusError as e:
            yield sse_delta(f"\nGemini API error ({e.response.status_code}): {e.response.text[:300]}\n")
        except Exception as e:
            yield sse_delta(f"\nError communicating with Gemini: {e}\n")
