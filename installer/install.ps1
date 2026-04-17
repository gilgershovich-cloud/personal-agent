# Personal AI Agent - Installer
# Run this once on your computer to connect to the AI agent

$BACKEND_URL = "wss://personal-agent-q29j.onrender.com/ws/bridge"
$AGENT_TOKEN = "__TOKEN__"
$INSTALL_DIR = "$env:USERPROFILE\PersonalAgent"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Personal AI Agent - התקנה" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "סוכן ה-AI האישי שלך מתחבר למחשב..." -ForegroundColor White
Write-Host ""

# Check Python
Write-Host "בודק Python..." -ForegroundColor Yellow
$pyCmd = $null
foreach ($cmd in @("python", "py", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $pyCmd = $cmd
            break
        }
    } catch {}
}

if (-not $pyCmd) {
    Write-Host "Python לא מותקן. מוריד ומתקין..." -ForegroundColor Yellow
    $installer = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe" -OutFile $installer
    Start-Process -Wait -FilePath $installer -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1"
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "User") + ";" + $env:PATH
    $pyCmd = "python"
    Write-Host "Python הותקן בהצלחה!" -ForegroundColor Green
} else {
    Write-Host "Python נמצא: $pyCmd" -ForegroundColor Green
}

# Create install dir
New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null

# Install websockets
Write-Host "מתקין תלויות..." -ForegroundColor Yellow
& $pyCmd -m pip install websockets --quiet
Write-Host "תלויות הותקנו!" -ForegroundColor Green

# Write bridge.py
Write-Host "יוצר קבצי הגשר..." -ForegroundColor Yellow
$bridgeCode = @'
import asyncio, glob, json, os, subprocess, sys, webbrowser
import websockets

BACKEND_URL = os.environ.get("BACKEND_URL", "")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")

async def execute_command(command, working_dir=None):
    try:
        full_cmd = ["powershell", "-NoProfile", "-Command", command] if sys.platform == "win32" else ["bash", "-c", command]
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=60, cwd=working_dir, encoding="utf-8", errors="replace")
        output = result.stdout.strip()
        if result.stderr.strip():
            output += f"\n[stderr]:\n{result.stderr.strip()}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: timed out"
    except Exception as e:
        return f"Error: {e}"

async def read_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content[:50000] + "\n...[truncated]" if len(content) > 50000 else content
    except Exception as e:
        return f"Error: {e}"

async def write_file(path, content):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"Error: {e}"

async def list_directory(path):
    try:
        items = sorted(os.listdir(path))
        lines = [f"[{'DIR ' if os.path.isdir(os.path.join(path,i)) else 'FILE'}] {i}" for i in items]
        return "\n".join(lines) or "(empty)"
    except Exception as e:
        return f"Error: {e}"

async def open_browser_tool(url):
    try:
        webbrowser.open(url)
        return f"Opened {url}"
    except Exception as e:
        return f"Error: {e}"

async def search_files(directory, pattern="**/*", content_search=None):
    try:
        pat = os.path.join(directory, pattern if "**" in pattern else f"**/{pattern}")
        files = [f for f in glob.glob(pat, recursive=True) if os.path.isfile(f)]
        if content_search:
            files = [f for f in files if _file_contains(f, content_search)]
        return "\n".join(files[:200]) or "No files found"
    except Exception as e:
        return f"Error: {e}"

def _file_contains(path, text):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return text.lower() in f.read().lower()
    except:
        return False

async def read_md_files(directory, max_files=15):
    try:
        files = glob.glob(os.path.join(directory, "**", "*.md"), recursive=True)
        files.sort(key=lambda f: (os.path.dirname(f) != directory, f))
        parts = []
        for f in files[:max_files]:
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    c = fh.read()[:5000]
                parts.append(f"=== {f} ===\n{c}")
            except:
                pass
        return "\n\n".join(parts) or "No .md files found"
    except Exception as e:
        return f"Error: {e}"

async def open_claude_code(working_dir, prompt=None):
    try:
        cmd = f'start cmd /k "cd /d {working_dir} && claude' + (f' -p \"{prompt}\"' if prompt else '') + '"'
        subprocess.Popen(cmd, shell=True)
        return f"Opened Claude Code in {working_dir}"
    except Exception as e:
        return f"Error: {e}"

HANDLERS = {
    "execute_command": lambda i: execute_command(i["command"], i.get("working_dir")),
    "read_file": lambda i: read_file(i["path"]),
    "write_file": lambda i: write_file(i["path"], i["content"]),
    "list_directory": lambda i: list_directory(i["path"]),
    "open_browser": lambda i: open_browser_tool(i["url"]),
    "search_files": lambda i: search_files(i["directory"], i.get("pattern","**/*"), i.get("content_search")),
    "read_md_files": lambda i: read_md_files(i["directory"], i.get("max_files",15)),
    "open_claude_code": lambda i: open_claude_code(i["working_dir"], i.get("prompt")),
}

async def run():
    url = f"{BACKEND_URL}?token={AGENT_TOKEN}"
    print(f"Connecting to agent server...")
    while True:
        try:
            async with websockets.connect(url, ping_interval=30, ping_timeout=20) as ws:
                print("Connected! Agent is ready.")
                while True:
                    data = json.loads(await ws.recv())
                    handler = HANDLERS.get(data["tool"])
                    result = await handler(data["input"]) if handler else f"Unknown tool: {data['tool']}"
                    await ws.send(json.dumps({"id": data["id"], "result": result}))
        except Exception as e:
            print(f"Reconnecting... ({e})")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run())
'@

$bridgeCode | Out-File -FilePath "$INSTALL_DIR\bridge.py" -Encoding UTF8

# Write launcher batch
$launcherContent = "@echo off`nset BACKEND_URL=$BACKEND_URL`nset AGENT_TOKEN=$AGENT_TOKEN`n$pyCmd `"$INSTALL_DIR\bridge.py`"`npause"
$launcherContent | Out-File -FilePath "$INSTALL_DIR\start.bat" -Encoding ASCII

# Create desktop shortcut
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\Personal AI Agent.lnk")
$Shortcut.TargetPath = "$INSTALL_DIR\start.bat"
$Shortcut.WorkingDirectory = $INSTALL_DIR
$Shortcut.IconLocation = "shell32.dll,13"
$Shortcut.Description = "Personal AI Agent Bridge"
$Shortcut.Save()

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "   ההתקנה הושלמה בהצלחה!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "נוצר קיצור דרך בשולחן העבודה:" -ForegroundColor White
Write-Host "  'Personal AI Agent'" -ForegroundColor Cyan
Write-Host ""
Write-Host "כדי להשתמש:" -ForegroundColor White
Write-Host "  1. לחץ פעול כפול על הקיצור בשולחן העבודה" -ForegroundColor White
Write-Host "  2. פתח את הקישור לאתר שקיבלת" -ForegroundColor White
Write-Host "  3. כתוב מה שתרצה!" -ForegroundColor White
Write-Host ""

# Auto-start bridge
Write-Host "מפעיל את הגשר..." -ForegroundColor Yellow
$env:BACKEND_URL = $BACKEND_URL
$env:AGENT_TOKEN = $AGENT_TOKEN
Start-Process -FilePath $pyCmd -ArgumentList "`"$INSTALL_DIR\bridge.py`"" -WindowStyle Normal

Write-Host "הגשר פועל! אפשר להשתמש בצ'אט." -ForegroundColor Green
Write-Host ""
Read-Host "לחץ Enter לסגור"
