import asyncio
import json
import os
import uuid
from typing import Optional

import anthropic
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

app = FastAPI(title="Personal AI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Multi-user state ----
# Each user token maps to their own bridge WebSocket and pending calls
bridges: dict[str, WebSocket] = {}
pending: dict[str, dict[str, asyncio.Future]] = {}

# Admin token — only used to create new user tokens
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "admin-change-me")

# User tokens stored in memory: {token: {"name": str}}
# Pre-populate from env: USERS="gil:gil1988,ima:ima2024"
users: dict[str, dict] = {}

def load_users_from_env():
    raw = os.environ.get("USERS", "")
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            name, token = pair.split(":", 1)
            users[token.strip()] = {"name": name.strip()}

load_users_from_env()

def get_user(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.replace("Bearer ", "").strip()
    if token not in users:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"token": token, **users[token]}


TOOLS = [
    {
        "name": "execute_command",
        "description": "Execute a terminal/shell command on the user's local Windows machine. Use PowerShell syntax.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "working_dir": {"type": "string"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the full contents of a file on the user's local machine.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write (or overwrite) a file on the user's local machine.",
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
        "description": "List contents of a directory on the user's local machine.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "open_browser",
        "description": "Open a URL in the default browser on the user's local machine.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for files by glob pattern and/or text content on the user's local machine.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string"},
                "pattern": {"type": "string"},
                "content_search": {"type": "string"},
            },
            "required": ["directory"],
        },
    },
    {
        "name": "read_md_files",
        "description": "Read all .md files from a directory recursively for context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string"},
                "max_files": {"type": "integer"},
            },
            "required": ["directory"],
        },
    },
    {
        "name": "open_claude_code",
        "description": "Open Claude Code CLI in a new terminal window, optionally with a prompt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "prompt": {"type": "string"},
            },
            "required": ["working_dir"],
        },
    },
]

SYSTEM_PROMPT = """You are {name}'s personal AI assistant with full access to their computer.

When the local bridge IS connected you can:
- Execute shell commands (Windows/PowerShell)
- Read and write files
- Search through files and folders
- Open URLs in the browser
- Read .md files for project context
- Open Claude Code for coding tasks

When the bridge is NOT connected:
- Work as a regular helpful AI assistant
- Answer questions, help with tasks, explain things
- Never say "I can't help" — always find a way to assist

Rules:
1. Be direct — take action, then report what you did
2. Use absolute Windows paths for file operations
3. If a tool fails, continue helping without it
4. Respond in the same language the user writes in (Hebrew or English)"""


async def dispatch(token: str, tool_name: str, tool_input: dict) -> str:
    ws = bridges.get(token)
    if ws is None:
        return "⚠️ המחשב שלך לא מחובר. הפעל את bridge.py."

    call_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    pending.setdefault(token, {})[call_id] = future

    await ws.send_json({"id": call_id, "tool": tool_name, "input": tool_input})

    try:
        return await asyncio.wait_for(future, timeout=90.0)
    except asyncio.TimeoutError:
        pending.get(token, {}).pop(call_id, None)
        return "⚠️ הפעולה פגה את הזמן (90 שניות)"


# ---- API ----

class ChatRequest(BaseModel):
    message: str
    history: list = []


@app.post("/chat")
async def chat(request: ChatRequest, authorization: Optional[str] = Header(None)):
    user = get_user(authorization)
    token = user["token"]
    name = user["name"]

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system = SYSTEM_PROMPT.format(name=name)

    messages = list(request.history) + [{"role": "user", "content": request.message}]
    response_text = ""
    tool_log = []

    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=8096,
            system=system,
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
                    result = await dispatch(token, block.name, block.input)
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

    return {"response": response_text, "history": messages, "tools_used": tool_log}


@app.get("/bridge-status")
async def bridge_status(authorization: Optional[str] = Header(None)):
    user = get_user(authorization)
    return {"connected": user["token"] in bridges}


@app.websocket("/ws/bridge")
async def bridge_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token", "")
    if token not in users:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    bridges[token] = websocket
    name = users[token]["name"]
    print(f"✅ Bridge connected: {name}")

    try:
        while True:
            data = await websocket.receive_json()
            call_id = data.get("id")
            result = data.get("result", "")

            future = pending.get(token, {}).pop(call_id, None)
            if future and not future.done():
                future.set_result(result)
    except WebSocketDisconnect:
        bridges.pop(token, None)
        print(f"❌ Bridge disconnected: {name}")


# ---- Admin: create new user ----
class NewUserRequest(BaseModel):
    name: str
    token: str

@app.post("/admin/add-user")
async def add_user(req: NewUserRequest, authorization: Optional[str] = Header(None)):
    if not authorization or authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Admin only")
    users[req.token] = {"name": req.name}
    return {"ok": True, "name": req.name, "token": req.token}

@app.get("/admin/users")
async def list_users(authorization: Optional[str] = Header(None)):
    if not authorization or authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Admin only")
    return {token: info for token, info in users.items()}


def build_installer(host: str, token: str) -> str:
    bridge_code = (
        'import asyncio,glob,json,os,subprocess,sys,webbrowser\n'
        'import websockets\n'
        'BACKEND_URL=os.environ.get("BACKEND_URL","")\n'
        'AGENT_TOKEN=os.environ.get("AGENT_TOKEN","")\n'
        'async def run():\n'
        '    url=BACKEND_URL+"?token="+AGENT_TOKEN\n'
        '    while True:\n'
        '        try:\n'
        '            async with websockets.connect(url,ping_interval=30) as ws:\n'
        '                print("Connected! Agent ready.")\n'
        '                while True:\n'
        '                    d=json.loads(await ws.recv())\n'
        '                    r=await handle(d["tool"],d["input"])\n'
        '                    await ws.send(json.dumps({"id":d["id"],"result":r}))\n'
        '        except Exception as e:\n'
        '            print("Reconnecting...",e)\n'
        '            await asyncio.sleep(5)\n'
        'async def handle(tool,i):\n'
        '    try:\n'
        '        if tool=="execute_command":\n'
        '            r=subprocess.run(["powershell","-NoProfile","-Command",i["command"]],capture_output=True,text=True,timeout=60,cwd=i.get("working_dir"),encoding="utf-8",errors="replace")\n'
        '            return (r.stdout+"\\n"+r.stderr).strip() or "(no output)"\n'
        '        if tool=="read_file":\n'
        '            return open(i["path"],encoding="utf-8",errors="replace").read()[:50000]\n'
        '        if tool=="write_file":\n'
        '            os.makedirs(os.path.dirname(os.path.abspath(i["path"])),exist_ok=True); open(i["path"],"w",encoding="utf-8").write(i["content"]); return "OK"\n'
        '        if tool=="list_directory":\n'
        '            items=sorted(os.listdir(i["path"])); return "\\n".join(("[DIR] " if os.path.isdir(os.path.join(i["path"],x)) else "[FILE] ")+x for x in items)\n'
        '        if tool=="open_browser":\n'
        '            webbrowser.open(i["url"]); return "Opened"\n'
        '        if tool=="search_files":\n'
        '            files=[f for f in glob.glob(os.path.join(i["directory"],"**",i.get("pattern","*")),recursive=True) if os.path.isfile(f)]; return "\\n".join(files[:200])\n'
        '        if tool=="read_md_files":\n'
        '            files=glob.glob(os.path.join(i["directory"],"**","*.md"),recursive=True)[:15]; return "\\n\\n".join("==="+f+"===\\n"+open(f,encoding="utf-8",errors="replace").read()[:3000] for f in files)\n'
        '        return "unknown tool: "+tool\n'
        '    except Exception as e:\n'
        '        return "Error: "+str(e)\n'
        'asyncio.run(run())\n'
    )

    lines = [
        '$BACKEND_URL = "wss://' + host + '/ws/bridge"',
        '$AGENT_TOKEN = "' + token + '"',
        '$INSTALL_DIR = "$env:USERPROFILE\\PersonalAgent"',
        '$pyCmd = "python"',
        '',
        'Write-Host "מתקין את הסוכן האישי שלך..." -ForegroundColor Cyan',
        '',
        'foreach ($cmd in @("python","py","python3")) {',
        '    try { $v = & $cmd --version 2>&1; if ($v -match "Python 3") { $pyCmd = $cmd; break } } catch {}',
        '}',
        'if (-not $pyCmd) {',
        '    Write-Host "Python לא נמצא, מתקין..." -ForegroundColor Yellow',
        '    try {',
        '        winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements',
        '        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")',
        '        $pyCmd = "python"',
        '    } catch {',
        '        Write-Host "לא הצלחנו להתקין Python אוטומטית." -ForegroundColor Red',
        '        Write-Host "הורד מהאתר: https://www.python.org/downloads/" -ForegroundColor Yellow',
        '        Read-Host "אחרי ההתקנה לחץ Enter להמשך"',
        '        $pyCmd = "python"',
        '    }',
        '}',
        '',
        'New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null',
        '& $pyCmd -m pip install websockets --quiet',
        '',
        '@\'' ,
    ]
    lines.append(bridge_code)
    lines += [
        '\'@ | Out-File "$INSTALL_DIR\\bridge.py" -Encoding UTF8',
        '',
        '"@echo off`r`nset BACKEND_URL=$BACKEND_URL`r`nset AGENT_TOKEN=$AGENT_TOKEN`r`n$pyCmd `"$INSTALL_DIR\\bridge.py`"`r`npause" | Out-File "$INSTALL_DIR\\start.bat" -Encoding ASCII',
        '',
        '$sh = New-Object -comObject WScript.Shell',
        '$sc = $sh.CreateShortcut("$env:USERPROFILE\\Desktop\\Personal AI Agent.lnk")',
        '$sc.TargetPath="$INSTALL_DIR\\start.bat"; $sc.IconLocation="shell32.dll,13"; $sc.Save()',
        '',
        '$env:BACKEND_URL=$BACKEND_URL; $env:AGENT_TOKEN=$AGENT_TOKEN',
        'Start-Process $pyCmd -ArgumentList "`"$INSTALL_DIR\\bridge.py`""',
        'Write-Host "הותקן! נוצר קיצור דרך בשולחן העבודה." -ForegroundColor Green',
        'Write-Host "פתח עכשיו: https://' + host + '" -ForegroundColor Cyan',
        'Write-Host "הסיסמא שלך: ' + token + '" -ForegroundColor Yellow',
        'Read-Host "לחץ Enter לסגור"',
    ]
    return "\n".join(lines)

@app.get("/installer/{token}")
async def get_installer(token: str, request_host: Optional[str] = Header(None, alias="host")):
    if token not in users:
        raise HTTPException(status_code=404, detail="Token not found")
    host = request_host or "personal-agent-q29j.onrender.com"
    script = build_installer(host, token)
    return PlainTextResponse(content=script, media_type="text/plain; charset=utf-8")


@app.get("/")
async def root():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
