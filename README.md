# Personal AI Agent

סוכן AI אישי עם גישה מלאה למחשב, דרך ממשק ווב בענן.

## ארכיטקטורה

```
Browser  ──►  Cloud Backend (Railway)  ──►  Claude Opus 4.6
                      │                           │
                      │ WebSocket                 │ Tool calls
                      ▼                           ▼
               Local Bridge (PC)  ◄──────────────┘
               (קבצים, טרמינל, דפדפן)
```

## שלב 1 — Deploy ל-Railway

1. [railway.app](https://railway.app) → New Project → Deploy from GitHub (או drag the folder)
2. הגדר Environment Variables:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   AGENT_TOKEN=בחר-סיסמא-חזקה
   ```
3. Railway יתן לך URL כמו `https://personal-agent-xxx.up.railway.app`

## שלב 2 — הגדר את ה-Bridge המקומי

ערוך את `start-bridge.bat`:
```bat
set BACKEND_URL=wss://YOUR-APP.up.railway.app/ws/bridge
set AGENT_TOKEN=הסיסמא-שהגדרת
```

התקן dependencies (פעם אחת):
```
cd local_bridge
pip install -r requirements.txt
```

## שלב 3 — הפעל

1. לחץ פעול כפול על `start-bridge.bat` — חלון שחור שמחכה לפקודות
2. פתח את ה-URL של Railway בדפדפן
3. הכנס את ה-AGENT_TOKEN
4. תראה "Bridge מחובר ✓" בירוק בפינה

## מה הסוכן יכול לעשות

| כלי | תיאור |
|-----|--------|
| `execute_command` | מריץ פקודות PowerShell |
| `read_file` | קורא קבצים |
| `write_file` | כותב/עורך קבצים |
| `list_directory` | רואה תוכן תיקיות |
| `open_browser` | פותח URLs בדפדפן |
| `search_files` | מחפש קבצים לפי שם/תוכן |
| `read_md_files` | קורא כל קבצי ה-MD לקונטקסט |
| `open_claude_code` | פותח Claude Code CLI בטרמינל |

## דוגמאות לפקודות

```
תיגש לפרויקט social-ai-platform ותראה לי מה המצב
תפתח Claude Code ב-C:\Users\Gilge\whatsapp_ai_bot ותבנה פיצ'ר חדש
תחפש בכל הפרויקטים קבצים שמכילים את המילה "celery"
תקרא את כל קבצי ה-MD בפרויקטים שלי ותסכם מה יש לי
```
