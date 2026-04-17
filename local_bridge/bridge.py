"""
Personal Agent - Local Bridge
==============================
Run this script on your local machine to give the cloud agent
full access to your computer: files, terminal, browser, etc.

Usage:
    set BACKEND_URL=wss://your-app.railway.app/ws/bridge
    set AGENT_TOKEN=your-secret-token
    python bridge.py
"""

import asyncio
import glob
import json
import os
import subprocess
import sys
import webbrowser

import websockets

BACKEND_URL = os.environ.get("BACKEND_URL", "wss://personal-agent.up.railway.app/ws/bridge")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "change-me-secret")


# ---- Tool implementations ----

async def execute_command(command: str, working_dir: str = None) -> str:
    print(f"  [CMD] {command}")
    try:
        # Use PowerShell on Windows
        if sys.platform == "win32":
            full_cmd = ["powershell", "-NoProfile", "-Command", command]
        else:
            full_cmd = ["bash", "-c", command]

        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=working_dir,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += f"\n[stderr]:\n{result.stderr.strip()}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds"
    except Exception as e:
        return f"Error: {e}"


async def read_file(path: str) -> str:
    print(f"  [READ] {path}")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Limit to 50k chars to avoid huge payloads
        if len(content) > 50_000:
            content = content[:50_000] + "\n\n... [truncated]"
        return content
    except Exception as e:
        return f"Error: {e}"


async def write_file(path: str, content: str) -> str:
    print(f"  [WRITE] {path}")
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"Error: {e}"


async def list_directory(path: str) -> str:
    print(f"  [LS] {path}")
    try:
        items = sorted(os.listdir(path))
        lines = []
        for item in items:
            full = os.path.join(path, item)
            kind = "DIR " if os.path.isdir(full) else "FILE"
            lines.append(f"[{kind}] {item}")
        return "\n".join(lines) or "(empty directory)"
    except Exception as e:
        return f"Error: {e}"


async def open_browser_tool(url: str) -> str:
    print(f"  [BROWSER] {url}")
    try:
        webbrowser.open(url)
        return f"Opened {url}"
    except Exception as e:
        return f"Error: {e}"


async def search_files(directory: str, pattern: str = "**/*", content_search: str = None) -> str:
    print(f"  [SEARCH] {directory} / {pattern}")
    try:
        search_pattern = os.path.join(directory, pattern if "**" in pattern else f"**/{pattern}")
        files = glob.glob(search_pattern, recursive=True)
        files = [f for f in files if os.path.isfile(f)]

        if content_search:
            matching = []
            for f in files:
                try:
                    with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                        if content_search.lower() in fh.read().lower():
                            matching.append(f)
                except Exception:
                    pass
            files = matching

        files = files[:200]
        return "\n".join(files) if files else "No files found"
    except Exception as e:
        return f"Error: {e}"


async def read_md_files(directory: str, max_files: int = 15) -> str:
    print(f"  [MD] {directory}")
    try:
        md_files = glob.glob(os.path.join(directory, "**", "*.md"), recursive=True)
        # Prioritize root-level and CLAUDE.md files
        md_files.sort(key=lambda f: (os.path.dirname(f) != directory, "claude" not in f.lower(), f))
        md_files = md_files[:max_files]

        parts = []
        for f in md_files:
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                if len(content) > 5000:
                    content = content[:5000] + "\n... [truncated]"
                parts.append(f"=== {f} ===\n{content}")
            except Exception:
                pass

        return "\n\n".join(parts) if parts else "No .md files found"
    except Exception as e:
        return f"Error: {e}"


async def open_claude_code(working_dir: str, prompt: str = None) -> str:
    print(f"  [CLAUDE CODE] {working_dir}")
    try:
        if sys.platform == "win32":
            if prompt:
                # Pass prompt via stdin piping
                cmd = f'start cmd /k "cd /d {working_dir} && claude -p \"{prompt}\""'
            else:
                cmd = f'start cmd /k "cd /d {working_dir} && claude"'
            subprocess.Popen(cmd, shell=True)
        else:
            cmd = f"cd {working_dir} && claude" + (f' -p "{prompt}"' if prompt else "")
            subprocess.Popen(["bash", "-c", f"open -a Terminal . && {cmd}"])
        return f"Opened Claude Code in {working_dir}"
    except Exception as e:
        return f"Error: {e}"


HANDLERS = {
    "execute_command": lambda i: execute_command(i["command"], i.get("working_dir")),
    "read_file": lambda i: read_file(i["path"]),
    "write_file": lambda i: write_file(i["path"], i["content"]),
    "list_directory": lambda i: list_directory(i["path"]),
    "open_browser": lambda i: open_browser_tool(i["url"]),
    "search_files": lambda i: search_files(i["directory"], i.get("pattern", "**/*"), i.get("content_search")),
    "read_md_files": lambda i: read_md_files(i["directory"], i.get("max_files", 15)),
    "open_claude_code": lambda i: open_claude_code(i["working_dir"], i.get("prompt")),
}


# ---- WebSocket loop ----

async def run():
    url = f"{BACKEND_URL}?token={AGENT_TOKEN}"
    print(f"Connecting to {BACKEND_URL} ...")

    while True:
        try:
            async with websockets.connect(url, ping_interval=30, ping_timeout=20) as ws:
                print("✅ Bridge connected! Waiting for commands...\n")

                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)

                    tool = data.get("tool")
                    inp = data.get("input", {})
                    call_id = data.get("id")

                    print(f"→ {tool}  {json.dumps(inp)[:120]}")

                    handler = HANDLERS.get(tool)
                    if handler:
                        try:
                            result = await handler(inp)
                        except Exception as e:
                            result = f"Unhandled error: {e}"
                    else:
                        result = f"Unknown tool: {tool}"

                    await ws.send(json.dumps({"id": call_id, "result": result}))
                    print(f"← sent result ({len(result)} chars)\n")

        except Exception as e:
            print(f"❌ Connection lost: {e}  — reconnecting in 5s...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
