import asyncio
import json
import os
import uuid
from typing import Optional

import anthropic
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Personal AI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- State ----
bridge_ws: Optional[WebSocket] = None
pending_tool_calls: dict[str, asyncio.Future] = {}

AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "change-me-secret")

TOOLS = [
    {
        "name": "execute_command",
        "description": (
            "Execute a terminal/shell command on Gil's local Windows machine. "
            "Use PowerShell syntax. Returns stdout + stderr."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run"},
                "working_dir": {"type": "string", "description": "Working directory (optional)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the full contents of a file on Gil's local machine.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute file path"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write (or overwrite) a file on Gil's local machine.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List contents of a directory on Gil's local machine.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "open_browser",
        "description": "Open a URL in the default browser on Gil's local machine.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "search_files",
        "description": (
            "Search for files by glob pattern and/or text content on Gil's local machine. "
            "Returns matching file paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Root directory to search"},
                "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.py' or '**/*.md'"},
                "content_search": {"type": "string", "description": "Return only files containing this text"},
            },
            "required": ["directory"],
        },
    },
    {
        "name": "read_md_files",
        "description": (
            "Read all .md (Markdown) files from a directory recursively. "
            "Use this to quickly load context about a project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string"},
                "max_files": {"type": "integer", "description": "Max files to read (default 15)"},
            },
            "required": ["directory"],
        },
    },
    {
        "name": "open_claude_code",
        "description": (
            "Open Claude Code CLI in a new terminal window on Gil's machine, "
            "optionally with an initial prompt. Use this to delegate complex coding tasks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "working_dir": {"type": "string", "description": "Project directory to open"},
                "prompt": {"type": "string", "description": "Initial prompt to pass to Claude Code"},
            },
            "required": ["working_dir"],
        },
    },
]

SYSTEM_PROMPT = """You are Gil's personal AI assistant — always available, always helpful.

Gil is a developer working on multiple projects:
- Social AI Platform (social media automation)
- WhatsApp AI bot
- Various side projects in C:\\Users\\Gilge\\

When the local bridge IS connected, you have full computer access:
- Execute shell commands (Windows/PowerShell)
- Read and write files
- Search through codebases
- Open browsers to specific URLs
- Read project .md files for context
- Launch Claude Code for complex coding tasks

When the local bridge is NOT connected (computer is off or bridge not running):
- Work as a regular AI assistant — answer questions, help with code, write content, analyze, plan
- Do NOT repeatedly complain about the bridge being disconnected
- Just help with whatever Gil needs using your knowledge

How to work:
1. When asked about a project and bridge is connected, first read its .md files for context
2. For file operations, use absolute Windows paths
3. Be direct — take action, then report what you did
4. If a tool fails due to bridge disconnection, continue helping in whatever way you can without the tool
5. Never say "I can't help" — always find a way to assist

Gil communicates in Hebrew and English. Always respond in the same language he used."""


async def dispatch(tool_name: str, tool_input: dict) -> str:
    if bridge_ws is None:
        return "⚠️ Local bridge not connected. Start bridge.py on your machine."

    call_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    pending_tool_calls[call_id] = future

    await bridge_ws.send_json({"id": call_id, "tool": tool_name, "input": tool_input})

    try:
        result = await asyncio.wait_for(future, timeout=90.0)
        return result
    except asyncio.TimeoutError:
        pending_tool_calls.pop(call_id, None)
        return "⚠️ Tool execution timed out after 90s"


# ---- API ----

class ChatRequest(BaseModel):
    message: str
    history: list = []


def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization or authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.post("/chat")
async def chat(request: ChatRequest, authorization: Optional[str] = Header(None)):
    verify_token(authorization)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages = list(request.history) + [{"role": "user", "content": request.message}]
    response_text = ""
    tool_log = []

    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            assistant_content = [b.model_dump() for b in response.content]
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_log.append({"tool": block.name, "input": block.input})
                    result = await dispatch(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    response_text += block.text
            messages.append({"role": "assistant", "content": response_text})
            break
        else:
            break

    return {
        "response": response_text,
        "history": messages,
        "tools_used": tool_log,
    }


@app.get("/bridge-status")
async def bridge_status():
    return {"connected": bridge_ws is not None}


@app.websocket("/ws/bridge")
async def bridge_endpoint(websocket: WebSocket):
    global bridge_ws

    token = websocket.query_params.get("token", "")
    if token != AGENT_TOKEN:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    bridge_ws = websocket
    print("✅ Local bridge connected")

    try:
        while True:
            data = await websocket.receive_json()
            call_id = data.get("id")
            result = data.get("result", "")

            future = pending_tool_calls.pop(call_id, None)
            if future and not future.done():
                future.set_result(result)
    except WebSocketDisconnect:
        bridge_ws = None
        print("❌ Local bridge disconnected")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
