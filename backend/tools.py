"""Agent tools — definitions + execution for native provider tool-calling.

This module defines the tool schemas (used by text-based providers that don't
use MCP) and provides direct execution functions for the web_tools API routes.
The MCP server (mcp_server.py) is the primary tool interface; this exists for
backward compatibility and the REST API.
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path

# ── Safety constants (shared with mcp_server.py) ─────────────────

_BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".mp3", ".mp4", ".wav", ".zip", ".tar", ".gz", ".bz2",
    ".exe", ".dll", ".so", ".dylib", ".o", ".wasm",
    ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".pyc",
    ".sqlite", ".db",
})

_SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".next", "dist", "build",
    ".cache", ".venv", "venv",
})

# ── Tool schema (provider-neutral, converted per-provider) ──────

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file's contents. Optionally specify start_line and end_line (1-indexed) for a range.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative file path"},
                "start_line": {"type": "integer", "description": "First line to read (1-indexed, 0 = entire file)"},
                "end_line": {"type": "integer", "description": "Last line to read (1-indexed, 0 = to end)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates or overwrites.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in a file. Finds old_text and replaces with new_text. Fails if old_text not found or ambiguous.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit"},
                "old_text": {"type": "string", "description": "Exact text to find"},
                "new_text": {"type": "string", "description": "Replacement text"},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "append_file",
        "description": "Append content to the end of a file. Creates the file if it doesn't exist.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Content to append"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a directory with sizes. Set recursive=true for a tree view.",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory path (default: .)"},
                "recursive": {"type": "boolean", "description": "Recurse into subdirectories"},
                "max_depth": {"type": "integer", "description": "Max recursion depth (default 3)"},
            },
        },
    },
    {
        "name": "glob_files",
        "description": "Find files matching a glob pattern (e.g. '**/*.tsx', 'src/**/*.py').",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern"},
                "directory": {"type": "string", "description": "Root directory (default: .)"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "search_codebase",
        "description": "Search for a regex pattern across source files. Returns matches with context.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex)"},
                "directory": {"type": "string", "description": "Directory to search in (default: .)"},
                "file_pattern": {"type": "string", "description": "Optional glob to filter files (e.g. '*.py')"},
                "context_lines": {"type": "integer", "description": "Context lines around each match (default 2)"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_shell",
        "description": "Run a shell command and return its output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 120)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "git_status",
        "description": "Show git branch, staged/modified/untracked files, and recent commits.",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Repo directory (default: .)"},
            },
        },
    },
    {
        "name": "git_diff",
        "description": "Show git diff. Optionally for a specific file. Set staged=true for staged changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Optional file path to diff"},
                "staged": {"type": "boolean", "description": "Show staged changes (default false)"},
                "directory": {"type": "string", "description": "Repo directory (default: .)"},
            },
        },
    },
    {
        "name": "git_log",
        "description": "Show git commit log.",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of commits (default 10, max 50)"},
                "path": {"type": "string", "description": "Optional file path to filter by"},
                "directory": {"type": "string", "description": "Repo directory (default: .)"},
            },
        },
    },
    {
        "name": "git_commit",
        "description": "Stage and commit files. If files is empty, commits all modified tracked files.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "files": {"type": "string", "description": "Space-separated file paths to stage (default: all modified)"},
                "directory": {"type": "string", "description": "Repo directory (default: .)"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "browser_goto",
        "description": "Navigate the headless browser to a URL. Returns page title and URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
                "wait_ms": {"type": "integer", "description": "Milliseconds to wait after load (default 2000)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_screenshot",
        "description": "Take a screenshot of the current browser page. Returns the image for visual inspection. Use this to see what a webpage or your app looks like.",
        "parameters": {
            "type": "object",
            "properties": {
                "full_page": {"type": "boolean", "description": "Capture full scrollable page (default false)"},
            },
        },
    },
    {
        "name": "browser_click",
        "description": "Click an element on the browser page by CSS selector.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element to click"},
            },
            "required": ["selector"],
        },
    },
    {
        "name": "browser_type",
        "description": "Type text into an input element on the browser page.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of input element"},
                "text": {"type": "string", "description": "Text to type"},
                "press_enter": {"type": "boolean", "description": "Press Enter after typing (default false)"},
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "browser_eval",
        "description": "Evaluate JavaScript in the browser page and return the result.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "JavaScript expression to evaluate"},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "browser_get_text",
        "description": "Get visible text content of an element on the current browser page.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector (default: body)"},
            },
        },
    },
    {
        "name": "browser_click_at",
        "description": "Click at pixel coordinates (x, y) on the browser page (1280x800 viewport). Use after browser_screenshot to click by visual position.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate (0-1280)"},
                "y": {"type": "integer", "description": "Y coordinate (0-800)"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "browser_right_click",
        "description": "Right-click at pixel coordinates to open a context menu. Follow with browser_screenshot to see the menu.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "browser_type_at",
        "description": "Click at coordinates then type text — for input fields identified by position in a screenshot.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "text": {"type": "string"},
                "press_enter": {"type": "boolean", "description": "Press Enter after typing"},
            },
            "required": ["x", "y", "text"],
        },
    },
    {
        "name": "browser_start",
        "description": "Open the browser panel for the user and navigate to a URL. Use this to begin a browsing session.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_open",
        "description": "Open the browser panel in the agent pane so the user can see what you're doing in the browser.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "browser_close",
        "description": "Close the browser panel in the agent pane.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]


# ── Format converters for each provider ──────────────────────────

def tools_for_claude() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in TOOLS]

def tools_for_openai() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in TOOLS]

def tools_for_gemini() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "parameters": t["parameters"]} for t in TOOLS]


# ── Tool execution ───────────────────────────────────────────────

def run_tool(name: str, args: dict) -> str:
    """Execute a tool by name. Delegates to the implementations below."""
    try:
        handler = _HANDLERS.get(name)
        if handler:
            return handler(args)
        return f"Unknown tool: {name}"
    except Exception as e:
        return f"Error executing {name}: {e}"


# ── Web tools (also used by web_tools.py routes) ─────────────────




# ── Implementation handlers ──────────────────────────────────────

def _is_binary(path: Path) -> bool:
    if path.suffix.lower() in _BINARY_EXTENSIONS:
        return True
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(512)
    except Exception:
        return True


def _h_read_file(args: dict) -> str:
    p = Path(args["path"]).expanduser().resolve()
    if not p.exists():
        return f"Error: File not found: {p}"
    start = args.get("start_line", 0) or 0
    end = args.get("end_line", 0) or 0
    if start > 0:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        total = len(lines)
        s = max(1, start) - 1
        e = min(total, end) if end > 0 else total
        selected = lines[s:e]
        numbered = [f"{i+s+1:>5} | {line}" for i, line in enumerate(selected)]
        return f"[{p.name} — lines {s+1}-{s+len(selected)} of {total}]\n" + "".join(numbered)
    if _is_binary(p):
        return f"[Binary file: {p.name} ({p.stat().st_size:,} bytes)]"
    return p.read_text(encoding="utf-8", errors="replace")


def _h_write_file(args: dict) -> str:
    p = Path(args["path"]).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"], encoding="utf-8")
    return f"Wrote {len(args['content']):,} bytes to {p}"


def _h_edit_file(args: dict) -> str:
    p = Path(args["path"]).expanduser().resolve()
    if not p.exists():
        return f"Error: File not found: {p}"
    content = p.read_text(encoding="utf-8", errors="replace")
    old = args["old_text"]
    new = args["new_text"]
    count = content.count(old)
    if count == 0:
        return f"Error: old_text not found in {p.name}"
    replace_all = args.get("replace_all", False)
    if count > 1 and not replace_all:
        return f"Error: old_text found {count} times. Set replace_all=true or provide more context."
    new_content = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    p.write_text(new_content, encoding="utf-8")
    return f"Replaced {count if replace_all else 1} occurrence(s) in {p.name}"


def _h_append_file(args: dict) -> str:
    p = Path(args["path"]).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(args["content"])
    return f"Appended {len(args['content']):,} bytes to {p}"


def _h_list_files(args: dict) -> str:
    root = Path(args.get("directory", ".")).expanduser().resolve()
    if not root.is_dir():
        return f"Error: Not a directory: {root}"
    recursive = args.get("recursive", False)
    lines = []
    for entry in sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        if entry.name in _SKIP_DIRS or entry.name.startswith("."):
            continue
        if entry.is_dir():
            lines.append(f"{entry.name}/")
        else:
            lines.append(entry.name)
    return "\n".join(lines[:200]) if lines else "(empty)"


def _h_glob_files(args: dict) -> str:
    root = Path(args.get("directory", ".")).expanduser().resolve()
    matches = []
    for p in root.glob(args["pattern"]):
        if any(skip in p.parts for skip in _SKIP_DIRS):
            continue
        if p.is_file():
            try:
                matches.append(str(p.relative_to(root)))
            except ValueError:
                matches.append(str(p))
    matches.sort()
    if not matches:
        return f"No files matching '{args['pattern']}'"
    return "\n".join(matches[:200])


def _h_search_codebase(args: dict) -> str:
    pattern = args["pattern"]
    directory = args.get("directory", ".")
    file_pattern = args.get("file_pattern", "")
    ctx = args.get("context_lines", 2)
    cmd = ["grep", "-rn", f"-C{ctx}", "--color=never"]
    if file_pattern:
        cmd.extend(["--include", file_pattern])
    else:
        for ext in ("*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.json",
                     "*.css", "*.html", "*.md", "*.yaml", "*.yml",
                     "*.toml", "*.sh", "*.rs", "*.go", "*.java", "*.c", "*.cpp", "*.h",
                     "*.sql", "*.svelte", "*.vue", "*.rb", "*.php", "*.swift"):
            cmd.extend(["--include", ext])
    for skip in ("node_modules", ".git", "__pycache__", "dist", "build"):
        cmd.extend(["--exclude-dir", skip])
    cmd.extend([pattern, directory])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return r.stdout.strip() if r.stdout.strip() else f"No matches for '{pattern}'"


def _h_run_shell(args: dict) -> str:
    timeout = min(max(args.get("timeout", 30), 1), 120)
    try:
        r = subprocess.run(args["command"], shell=True, capture_output=True, text=True,
                           timeout=timeout, cwd=args.get("cwd"))
        out = r.stdout
        if r.stderr:
            out += f"\nSTDERR:\n{r.stderr}"
        out = out.strip()
        if not out:
            return f"(exit {r.returncode})"
        if r.returncode != 0:
            out += f"\n(exit {r.returncode})"
        return out
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"


def _git(cmd_args: list[str], cwd: str | None = None) -> str:
    r = subprocess.run(["git"] + cmd_args, capture_output=True, text=True, timeout=15, cwd=cwd)
    return (r.stdout + r.stderr).strip() or f"(exit {r.returncode})"


def _h_git_status(args: dict) -> str:
    d = args.get("directory", ".")
    branch = _git(["branch", "--show-current"], cwd=d)
    status = _git(["status", "--short"], cwd=d)
    log = _git(["log", "--oneline", "-5"], cwd=d)
    return f"Branch: {branch}\n\nStatus:\n{status}\n\nRecent commits:\n{log}"


def _h_git_diff(args: dict) -> str:
    d = args.get("directory", ".")
    cmd = ["diff"]
    if args.get("staged"):
        cmd.append("--staged")
    if args.get("path"):
        cmd.extend(["--", args["path"]])
    return _git(cmd, cwd=d)


def _h_git_log(args: dict) -> str:
    d = args.get("directory", ".")
    count = min(max(args.get("count", 10), 1), 50)
    cmd = ["log", f"-{count}", "--oneline", "--decorate"]
    if args.get("path"):
        cmd.extend(["--", args["path"]])
    return _git(cmd, cwd=d)


def _h_git_commit(args: dict) -> str:
    d = args.get("directory", ".")
    files = args.get("files", "")
    if files:
        for f in files.split():
            _git(["add", f], cwd=d)
    else:
        _git(["add", "-u"], cwd=d)
    return _git(["commit", "-m", args["message"]], cwd=d)




# ── Browser tool handlers (use playwright directly) ──────────────

import base64 as _b64
import threading as _browser_lock_mod

_BROWSER_LOCK = _browser_lock_mod.Lock()
_BROWSER_STATE: dict = {}


_CDP_URL = "http://localhost:9222"


def _get_browser_page():
    with _BROWSER_LOCK:
        page = _BROWSER_STATE.get("page")
        if page is not None:
            try:
                page.title()
                return page
            except Exception:
                _BROWSER_STATE.clear()

        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(_CDP_URL)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _BROWSER_STATE["pw"] = pw
        _BROWSER_STATE["browser"] = browser
        _BROWSER_STATE["page"] = page
        return page


def _h_browser_goto(args: dict) -> str:
    page = _get_browser_page()
    url = args["url"]
    wait_ms = args.get("wait_ms", 2000)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        if wait_ms > 0:
            page.wait_for_timeout(min(wait_ms, 10000))
        return f"Navigated to: {page.url}\nTitle: {page.title()}"
    except Exception as e:
        return f"Error navigating to {url}: {e}"


def _h_browser_screenshot(args: dict) -> str:
    page = _get_browser_page()
    full_page = args.get("full_page", False)
    try:
        png = page.screenshot(full_page=full_page)
        b64 = _b64.b64encode(png).decode("ascii")
        return f"IMAGE:{b64}"
    except Exception as e:
        return f"Error taking screenshot: {e}"


def _h_browser_click(args: dict) -> str:
    page = _get_browser_page()
    sel = args["selector"]
    try:
        page.click(sel, timeout=5000)
        page.wait_for_timeout(500)
        return f"Clicked: {sel}\nURL: {page.url}"
    except Exception as e:
        return f"Error clicking '{sel}': {e}"


def _h_browser_type(args: dict) -> str:
    page = _get_browser_page()
    sel = args["selector"]
    text = args["text"]
    try:
        page.fill(sel, text, timeout=5000)
        if args.get("press_enter"):
            page.press(sel, "Enter")
            page.wait_for_timeout(500)
        return f"Typed into {sel}"
    except Exception as e:
        return f"Error typing into '{sel}': {e}"


def _h_browser_eval(args: dict) -> str:
    page = _get_browser_page()
    try:
        import json as _json
        result = page.evaluate(args["expression"])
        text = _json.dumps(result, indent=2, default=str) if not isinstance(result, str) else result
        return text[:8000]
    except Exception as e:
        return f"Error evaluating JS: {e}"


def _h_browser_get_text(args: dict) -> str:
    page = _get_browser_page()
    sel = args.get("selector", "body")
    try:
        text = page.inner_text(sel, timeout=5000)
        return text[:16000] if text else "(empty)"
    except Exception as e:
        return f"Error getting text from '{sel}': {e}"


def _h_browser_click_at(args: dict) -> str:
    page = _get_browser_page()
    x, y = int(args["x"]), int(args["y"])
    try:
        page.mouse.click(x, y)
        page.wait_for_timeout(500)
        return f"Clicked at ({x}, {y})\nURL: {page.url}"
    except Exception as e:
        return f"Error clicking at ({x}, {y}): {e}"


def _h_browser_right_click(args: dict) -> str:
    page = _get_browser_page()
    x, y = int(args["x"]), int(args["y"])
    try:
        page.mouse.click(x, y, button="right")
        page.wait_for_timeout(300)
        return f"Right-clicked at ({x}, {y})"
    except Exception as e:
        return f"Error right-clicking at ({x}, {y}): {e}"


def _h_browser_type_at(args: dict) -> str:
    page = _get_browser_page()
    x, y = int(args["x"]), int(args["y"])
    text = args["text"]
    try:
        page.mouse.click(x, y)
        page.wait_for_timeout(200)
        page.keyboard.type(text)
        if args.get("press_enter"):
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)
        return f"Typed at ({x}, {y}): '{text[:50]}'"
    except Exception as e:
        return f"Error typing at ({x}, {y}): {e}"


def _browser_control(cmd: str) -> None:
    import urllib.request as _ur
    import json as _json
    try:
        body = _json.dumps({"cmd": cmd}).encode()
        req = _ur.Request("http://localhost:41900/api/browser/control",
                          data=body, headers={"Content-Type": "application/json"}, method="POST")
        _ur.urlopen(req, timeout=3)
    except Exception:
        pass


def _h_browser_start(args: dict) -> str:
    _browser_control("OPEN")
    return _h_browser_goto(args)


def _h_browser_open(_args: dict) -> str:
    _browser_control("OPEN")
    return "Browser panel opened"


def _h_browser_close(_args: dict) -> str:
    _browser_control("CLOSE")
    return "Browser panel closed"


_HANDLERS = {
    "read_file": _h_read_file,
    "write_file": _h_write_file,
    "edit_file": _h_edit_file,
    "append_file": _h_append_file,
    "list_files": _h_list_files,
    "glob_files": _h_glob_files,
    "search_codebase": _h_search_codebase,
    "run_shell": _h_run_shell,
    "git_status": _h_git_status,
    "git_diff": _h_git_diff,
    "git_log": _h_git_log,
    "git_commit": _h_git_commit,
    "browser_goto": _h_browser_goto,
    "browser_screenshot": _h_browser_screenshot,
    "browser_click": _h_browser_click,
    "browser_click_at": _h_browser_click_at,
    "browser_right_click": _h_browser_right_click,
    "browser_type": _h_browser_type,
    "browser_type_at": _h_browser_type_at,
    "browser_eval": _h_browser_eval,
    "browser_get_text": _h_browser_get_text,
    "browser_start": _h_browser_start,
    "browser_open": _h_browser_open,
    "browser_close": _h_browser_close,
}
