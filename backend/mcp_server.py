"""Standalone MCP tool server — spawned as subprocess by the tool client.

Run with: python3 -m backend.mcp_server
Communicates over stdio using the MCP protocol.
"""
from __future__ import annotations

import base64 as _b64
import json
import os
import subprocess
import threading as _threading
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tensor-tools")

# ── Safety ───────────────────────────────────────────────────────

_BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".avi", ".mkv", ".mov",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".pyc", ".pyo", ".class", ".wasm",
    ".sqlite", ".db",
})

_SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".next", ".nuxt",
    "dist", "build", ".cache", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "target", "out", "bin", "obj", ".DS_Store",
})


def _is_binary(path: Path) -> bool:
    if path.suffix.lower() in _BINARY_EXTENSIONS:
        return True
    try:
        with open(path, "rb") as f:
            chunk = f.read(512)
            return b"\x00" in chunk
    except Exception:
        return True


def _safe_read(path: Path, max_bytes: int = 512_000) -> str:
    """Read a text file safely with size limit."""
    if _is_binary(path):
        return f"[Binary file: {path.name} ({path.stat().st_size:,} bytes)]"
    size = path.stat().st_size
    if size > max_bytes:
        text = path.read_text(encoding="utf-8", errors="replace")[:max_bytes]
        return text + f"\n\n... [truncated — file is {size:,} bytes, showing first {max_bytes:,}]"
    return path.read_text(encoding="utf-8", errors="replace")


# ── File operations ──────────────────────────────────────────────

@mcp.tool()
def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    """Read a file's contents. Optionally specify start_line and end_line
    (1-indexed) to read a specific range. If both are 0, reads the entire file."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"Error: File not found: {p}"
    if not p.is_file():
        return f"Error: Not a file: {p}"
    if start_line > 0:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        total = len(lines)
        s = max(1, start_line) - 1
        e = min(total, end_line) if end_line > 0 else total
        selected = lines[s:e]
        numbered = [f"{i+s+1:>5} | {line}" for i, line in enumerate(selected)]
        header = f"[{p.name} — lines {s+1}-{s+len(selected)} of {total}]\n"
        return header + "".join(numbered)
    return _safe_read(p)


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed. Overwrites existing files."""
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content):,} bytes to {p}"


@mcp.tool()
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    """Replace exact text in a file. Finds `old_text` and replaces it with `new_text`.
    If replace_all is True, replaces every occurrence. Otherwise replaces only the first.
    Fails if old_text is not found or if it's ambiguous (multiple matches when replace_all=False)."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"Error: File not found: {p}"
    content = p.read_text(encoding="utf-8", errors="replace")
    count = content.count(old_text)
    if count == 0:
        return f"Error: old_text not found in {p.name}. Make sure it matches exactly (including whitespace)."
    if count > 1 and not replace_all:
        return f"Error: old_text found {count} times in {p.name}. Set replace_all=True or provide more context to make it unique."
    if replace_all:
        new_content = content.replace(old_text, new_text)
    else:
        new_content = content.replace(old_text, new_text, 1)
    p.write_text(new_content, encoding="utf-8")
    replaced = count if replace_all else 1
    return f"Replaced {replaced} occurrence{'s' if replaced > 1 else ''} in {p.name}"


@mcp.tool()
def append_file(path: str, content: str) -> str:
    """Append content to the end of a file. Creates the file if it doesn't exist."""
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(content)
    return f"Appended {len(content):,} bytes to {p}"


# ── Directory / file discovery ───────────────────────────────────

@mcp.tool()
def list_files(directory: str = ".", recursive: bool = False, max_depth: int = 3) -> str:
    """List files in a directory. Shows file type indicators and sizes.
    With recursive=True, shows a tree up to max_depth levels deep."""
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        return f"Error: Not a directory: {root}"
    lines = []

    def _walk(d: Path, prefix: str, depth: int):
        if depth > max_depth:
            lines.append(f"{prefix}... (max depth reached)")
            return
        try:
            entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            lines.append(f"{prefix}[permission denied]")
            return
        for entry in entries:
            if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                continue
            if entry.is_dir():
                lines.append(f"{prefix}{entry.name}/")
                if recursive:
                    _walk(entry, prefix + "  ", depth + 1)
            else:
                size = entry.stat().st_size
                if size < 1024:
                    sz = f"{size}B"
                elif size < 1024 * 1024:
                    sz = f"{size // 1024}K"
                else:
                    sz = f"{size // (1024*1024)}M"
                lines.append(f"{prefix}{entry.name}  ({sz})")

    _walk(root, "", 1)
    if not lines:
        return f"Directory is empty: {root}"
    header = f"[{root}]\n"
    return header + "\n".join(lines[:500]) + (f"\n... ({len(lines)-500} more)" if len(lines) > 500 else "")


@mcp.tool()
def glob_files(pattern: str, directory: str = ".") -> str:
    """Find files matching a glob pattern (e.g. '**/*.tsx', 'src/**/*.py').
    Searches recursively from the given directory."""
    root = Path(directory).expanduser().resolve()
    matches = []
    for p in root.glob(pattern):
        if _SKIP_DIRS.intersection(p.parts):
            continue
        if p.is_file():
            try:
                rel = p.relative_to(root)
            except ValueError:
                rel = p
            matches.append(str(rel))
    matches.sort()
    if not matches:
        return f"No files matching '{pattern}' in {root}"
    result = f"Found {len(matches)} file(s):\n" + "\n".join(matches[:200])
    if len(matches) > 200:
        result += f"\n... ({len(matches)-200} more)"
    return result


# ── Search ───────────────────────────────────────────────────────

@mcp.tool()
def search_codebase(pattern: str, directory: str = ".", file_pattern: str = "",
                    context_lines: int = 2, max_results: int = 50) -> str:
    """Search for a regex pattern across source files using grep.
    - file_pattern: optional glob to filter files (e.g. '*.py', '*.ts')
    - context_lines: lines of context around each match (default 2)
    - max_results: maximum number of matches to return"""
    args = ["grep", "-rn", f"-C{context_lines}", "--color=never"]

    if file_pattern:
        args.extend(["--include", file_pattern])
    else:
        # Search all common source file types
        for ext in ("*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.json",
                     "*.css", "*.scss", "*.html", "*.md", "*.yaml", "*.yml",
                     "*.toml", "*.cfg", "*.ini", "*.sh", "*.bash", "*.zsh",
                     "*.rs", "*.go", "*.java", "*.c", "*.cpp", "*.h",
                     "*.sql", "*.graphql", "*.prisma", "*.svelte", "*.vue",
                     "*.rb", "*.php", "*.swift", "*.kt", "*.scala",
                     "*.tf", "*.hcl", "*.dockerfile", "Makefile", "*.mk"):
            args.extend(["--include", ext])

    for skip in _SKIP_DIRS:
        args.extend(["--exclude-dir", skip])

    args.extend([pattern, directory])

    r = subprocess.run(args, capture_output=True, text=True, timeout=15)
    output = r.stdout.strip()
    if not output:
        return f"No matches for '{pattern}' in {directory}"
    lines = output.split("\n")
    if len(lines) > max_results * (1 + 2 * context_lines):
        lines = lines[:max_results * (1 + 2 * context_lines)]
        output = "\n".join(lines) + f"\n\n... (truncated, showing ~{max_results} matches)"
    return output


# ── Shell ────────────────────────────────────────────────────────

@mcp.tool()
def run_shell(command: str, cwd: Optional[str] = None, timeout: int = 30) -> str:
    """Run a shell command and return stdout+stderr.
    - cwd: working directory (default: current)
    - timeout: max seconds to wait (default 30, max 120)"""
    timeout = min(max(timeout, 1), 120)
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
        )
        out = r.stdout
        if r.stderr:
            out += f"\nSTDERR:\n{r.stderr}"
        out = out.strip()
        if not out:
            out = f"(exit {r.returncode})"
        elif r.returncode != 0:
            out += f"\n(exit {r.returncode})"
        return out
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"


# ── Git ──────────────────────────────────────────────────────────

def _git(args: list[str], cwd: str | None = None) -> str:
    r = subprocess.run(
        ["git"] + args, capture_output=True, text=True, timeout=15, cwd=cwd,
    )
    out = (r.stdout + r.stderr).strip()
    return out or f"(exit {r.returncode})"


@mcp.tool()
def git_status(directory: str = ".") -> str:
    """Show git status: branch, staged changes, modified files, untracked files."""
    branch = _git(["branch", "--show-current"], cwd=directory)
    status = _git(["status", "--short"], cwd=directory)
    log = _git(["log", "--oneline", "-5"], cwd=directory)
    return f"Branch: {branch}\n\nStatus:\n{status}\n\nRecent commits:\n{log}"


@mcp.tool()
def git_diff(path: str = "", staged: bool = False, directory: str = ".") -> str:
    """Show git diff. Optionally for a specific file path.
    Set staged=True to see staged (added) changes."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    if path:
        args.extend(["--", path])
    return _git(args, cwd=directory)


@mcp.tool()
def git_log(count: int = 10, path: str = "", directory: str = ".") -> str:
    """Show git commit log. Optionally filter by file path."""
    count = min(max(count, 1), 50)
    args = ["log", f"-{count}", "--oneline", "--decorate"]
    if path:
        args.extend(["--", path])
    return _git(args, cwd=directory)


@mcp.tool()
def git_commit(message: str, files: str = "", directory: str = ".") -> str:
    """Stage and commit files. If files is empty, commits all modified/tracked files.
    files can be space-separated paths or '.' for everything."""
    if files:
        for f in files.split():
            _git(["add", f], cwd=directory)
    else:
        _git(["add", "-u"], cwd=directory)
    return _git(["commit", "-m", message], cwd=directory)


# ── Browser (CDP-connected Playwright) ──────────────────────────

_BROWSER_LOCK = _threading.Lock()
_PLAYWRIGHT_CTX: "object | None" = None
_BROWSER: "object | None" = None
_BROWSER_PAGE: "object | None" = None
_CDP_URL = "http://localhost:9222"


def _get_page():
    """Connect to the running Chromium instance via CDP. Reuses across calls."""
    global _PLAYWRIGHT_CTX, _BROWSER, _BROWSER_PAGE
    with _BROWSER_LOCK:
        if _BROWSER_PAGE is not None:
            try:
                _BROWSER_PAGE.title()
                return _BROWSER_PAGE
            except Exception:
                _BROWSER_PAGE = None
                _BROWSER = None
                _PLAYWRIGHT_CTX = None

        from playwright.sync_api import sync_playwright
        _PLAYWRIGHT_CTX = sync_playwright().start()
        # Connect to the existing Chromium running on CDP port 9222
        _BROWSER = _PLAYWRIGHT_CTX.chromium.connect_over_cdp(_CDP_URL)
        ctx = _BROWSER.contexts[0] if _BROWSER.contexts else _BROWSER.new_context()
        _BROWSER_PAGE = ctx.pages[0] if ctx.pages else ctx.new_page()
        return _BROWSER_PAGE


@mcp.tool()
def browser_goto(url: str, wait_ms: int = 2000) -> str:
    """Navigate the browser to a URL and wait for it to load.
    Returns the page title and current URL."""
    page = _get_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        if wait_ms > 0:
            page.wait_for_timeout(min(wait_ms, 10000))
        return f"Navigated to: {page.url}\nTitle: {page.title()}"
    except Exception as e:
        return f"Error navigating to {url}: {e}"


@mcp.tool()
def browser_screenshot(full_page: bool = False) -> str:
    """Take a screenshot of the current browser page.
    Returns base64-encoded PNG prefixed with 'IMAGE:' so the system knows to pass it as an image.
    Set full_page=True to capture the entire scrollable page."""
    page = _get_page()
    try:
        png = page.screenshot(full_page=full_page)
        b64 = _b64.b64encode(png).decode("ascii")
        return f"IMAGE:{b64}"
    except Exception as e:
        return f"Error taking screenshot: {e}"


@mcp.tool()
def browser_click(selector: str) -> str:
    """Click an element on the page by CSS selector.
    Examples: 'button:text(\"Submit\")', '#login-btn', 'a[href=\"/about\"]'"""
    page = _get_page()
    try:
        page.click(selector, timeout=5000)
        page.wait_for_timeout(500)
        return f"Clicked: {selector}\nURL: {page.url}"
    except Exception as e:
        return f"Error clicking '{selector}': {e}"


@mcp.tool()
def browser_click_at(x: int, y: int) -> str:
    """Click at specific pixel coordinates on the browser page (1280x800 viewport).
    Use after browser_screenshot to click on visible elements by position."""
    page = _get_page()
    try:
        page.mouse.click(x, y)
        page.wait_for_timeout(500)
        return f"Clicked at ({x}, {y})\nURL: {page.url}"
    except Exception as e:
        return f"Error clicking at ({x}, {y}): {e}"


@mcp.tool()
def browser_right_click(x: int, y: int) -> str:
    """Right-click at specific pixel coordinates to open a context menu.
    Use browser_screenshot after to see the context menu."""
    page = _get_page()
    try:
        page.mouse.click(x, y, button="right")
        page.wait_for_timeout(300)
        return f"Right-clicked at ({x}, {y})"
    except Exception as e:
        return f"Error right-clicking at ({x}, {y}): {e}"


@mcp.tool()
def browser_type_at(x: int, y: int, text: str, press_enter: bool = False) -> str:
    """Click at coordinates then type text — for input fields identified by position in a screenshot."""
    page = _get_page()
    try:
        page.mouse.click(x, y)
        page.wait_for_timeout(200)
        page.keyboard.type(text)
        if press_enter:
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)
        return f"Typed at ({x}, {y}): '{text[:50]}{'...' if len(text) > 50 else ''}'"
    except Exception as e:
        return f"Error typing at ({x}, {y}): {e}"


@mcp.tool()
def browser_type(selector: str, text: str, press_enter: bool = False) -> str:
    """Type text into an input element by CSS selector.
    Set press_enter=True to submit after typing."""
    page = _get_page()
    try:
        page.fill(selector, text, timeout=5000)
        if press_enter:
            page.press(selector, "Enter")
            page.wait_for_timeout(500)
        return f"Typed into {selector}: '{text[:50]}{'...' if len(text) > 50 else ''}'"
    except Exception as e:
        return f"Error typing into '{selector}': {e}"


@mcp.tool()
def browser_eval(expression: str) -> str:
    """Evaluate a JavaScript expression in the browser and return the result.
    Useful for extracting data, checking element state, or running custom logic."""
    page = _get_page()
    try:
        result = page.evaluate(expression)
        text = json.dumps(result, indent=2, default=str) if not isinstance(result, str) else result
        return text[:8000]
    except Exception as e:
        return f"Error evaluating JS: {e}"


@mcp.tool()
def browser_get_text(selector: str = "body") -> str:
    """Get the visible text content of an element (default: entire page body).
    Useful for reading page content without a screenshot."""
    page = _get_page()
    try:
        text = page.inner_text(selector, timeout=5000)
        return text[:16000] if text else "(empty)"
    except Exception as e:
        return f"Error getting text from '{selector}': {e}"


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


@mcp.tool()
def browser_start(url: str) -> str:
    """Open the browser panel for the user and navigate to a URL. Use this to begin a browsing session."""
    _browser_control("OPEN")
    page = _get_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)
        return f"Opened browser at: {page.url} — {page.title()}"
    except Exception as e:
        return f"Navigated (timeout or error): {e}"


@mcp.tool()
def browser_open() -> str:
    """Open the browser panel in the agent pane so the user can watch what you're doing."""
    _browser_control("OPEN")
    return "Browser panel opened"


@mcp.tool()
def browser_close() -> str:
    """Close the browser panel in the agent pane."""
    _browser_control("CLOSE")
    return "Browser panel closed"


if __name__ == "__main__":
    mcp.run(transport="stdio")
