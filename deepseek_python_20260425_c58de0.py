#!/usr/bin/env python3
"""
Telegram Script Hosting Bot - Based on the image
Fresh working version - No Updater errors
Web server on port 8000 for Render
"""

import os
import sys
import subprocess

# ==================== AUTO INSTALL DEPENDENCIES ====================
try:
    import telegram
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot==20.7", "--quiet"])
    import telegram
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

try:
    from flask import Flask
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "--quiet"])
    from flask import Flask

# ==================== IMPORTS ====================
import asyncio
import threading
import json
import zipfile
import shutil
import tempfile
import logging
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path

# ==================== WEB SERVER (for Render - keeps bot alive) ====================
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram Bot is Running 24/7 | Script Hosting Bot"

@app_web.route('/health')
def health():
    return "OK", 200

def run_web_server():
    app_web.run(host='0.0.0.0', port=8000, debug=False, use_reloader=False)

threading.Thread(target=run_web_server, daemon=True).start()
print("🌐 Web server running on http://0.0.0.0:8000")

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8377202202:AAHxKZevXD5AhmQtoTjGKq9SjJ_nSJfnBiI"
ADMIN_IDS = [5696490206, 7317733740]  # Added the user ID from image
MAX_FILES = 10
WORK_DIR = Path("/tmp/script_hosting_bot")
WORK_DIR.mkdir(exist_ok=True)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== SCRIPT MANAGER ====================
@dataclass
class ScriptInfo:
    filename: str
    script_type: str
    uploaded_at: str
    is_running: bool
    process_id: Optional[int]
    started_at: Optional[str]

class ScriptManager:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.user_dir = WORK_DIR / str(user_id)
        self.user_dir.mkdir(exist_ok=True)
        self.scripts_file = self.user_dir / "scripts.json"
        self.scripts: List[ScriptInfo] = []
        self.load()
    
    def load(self):
        if self.scripts_file.exists():
            with open(self.scripts_file) as f:
                data = json.load(f)
                self.scripts = [ScriptInfo(**item) for item in data]
    
    def save(self):
        with open(self.scripts_file, 'w') as f:
            json.dump([asdict(s) for s in self.scripts], f, indent=2)
    
    def add_script(self, filename: str, content: str, script_type: str) -> tuple:
        if len(self.scripts) >= MAX_FILES:
            return False, f"❌ Max files limit reached ({MAX_FILES}/10)"
        
        path = self.user_dir / filename
        if path.exists():
            return False, f"❌ '{filename}' already exists"
        
        path.write_text(content)
        
        self.scripts.append(ScriptInfo(
            filename=filename,
            script_type=script_type,
            uploaded_at=datetime.now().isoformat(),
            is_running=False,
            process_id=None,
            started_at=None
        ))
        self.save()
        return True, f"✅ Uploaded: `{filename}`"
    
    def delete_script(self, filename: str) -> str:
        (self.user_dir / filename).unlink(missing_ok=True)
        (self.user_dir / f"{filename}.log").unlink(missing_ok=True)
        self.scripts = [s for s in self.scripts if s.filename != filename]
        self.save()
        return f"🗑️ Deleted `{filename}`"
    
    def list_scripts(self) -> List[ScriptInfo]:
        return self.scripts
    
    async def run_script(self, filename: str) -> tuple:
        script = next((s for s in self.scripts if s.filename == filename), None)
        if not script:
            return False, "❌ Script not found"
        if script.is_running:
            return False, f"⚠️ `{filename}` is already running"
        
        path = self.user_dir / filename
        if not path.exists():
            return False, "❌ File missing"
        
        try:
            if script.script_type == 'py':
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, str(path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "node", str(path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            
            script.is_running = True
            script.process_id = proc.pid
            script.started_at = datetime.now().isoformat()
            self.save()
            asyncio.create_task(self._monitor(proc, filename, script))
            return True, f"🚀 Running `{filename}` (PID: {proc.pid})"
        except Exception as e:
            return False, f"❌ Error: {str(e)}"
    
    async def _monitor(self, proc, filename, script):
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            log_file = self.user_dir / f"{filename}.log"
            with open(log_file, 'a') as f:
                f.write(f"\n{'='*50}\nTime: {datetime.now()}\nExit: {proc.returncode}\n")
                if stdout:
                    f.write(f"OUTPUT:\n{stdout.decode()}\n")
                if stderr:
                    f.write(f"ERRORS:\n{stderr.decode()}\n")
        except asyncio.TimeoutError:
            proc.kill()
        finally:
            script.is_running = False
            script.process_id = None
            self.save()
    
    def stop_script(self, filename: str) -> tuple:
        script = next((s for s in self.scripts if s.filename == filename), None)
        if script and script.is_running and script.process_id:
            try:
                os.kill(script.process_id, 9)
                script.is_running = False
                script.process_id = None
                self.save()
                return True, f"🛑 Stopped `{filename}`"
            except:
                return False, "Could not stop"
        return False, f"⚠️ `{filename}` is not running"
    
    def get_logs(self, filename: str) -> str:
        log_file = self.user_dir / f"{filename}.log"
        if log_file.exists():
            content = log_file.read_text()
            if len(content) > 3900:
                return "...(truncated)\n\n" + content[-3900:]
            return content
        return "📭 No logs yet. Run the script first."

# ==================== TELEGRAM HANDLERS ====================
def get_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Upload File", callback_data="upload"),
         InlineKeyboardButton("📋 My Scripts", callback_data="list")],
        [InlineKeyboardButton("📢 Updates Channel", url="https://t.me/ethicalhacking13"),
         InlineKeyboardButton("👤 Contact Owner", url="https://t.me/ethicalhacking13")],
        [InlineKeyboardButton("🏠 Home", callback_data="home"),
         InlineKeyboardButton("📺 Shorts", callback_data="shorts"),
         InlineKeyboardButton("➕ Subscribe", callback_data="subscribe")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "Unknown"
    mgr = ScriptManager(user_id)
    files_count = len(mgr.list_scripts())
    
    text = f"""Welcome, {username}!

ID Your User ID: {user_id}
Username: @{username}
Your Status: {"Admin" if user_id in ADMIN_IDS else "Free User"}
Files Uploaded: {files_count} / {MAX_FILES}

Host & run Python (.py) or JS (.js) scripts.
Upload single scripts or .zip archives.

Use buttons or type commands."""
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_keyboard())

async def upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not update.message.document:
        await update.message.reply_text("Please send a .py, .js, or .zip file", reply_markup=get_keyboard())
        return
    
    doc = update.message.document
    filename = doc.file_name
    
    if not any(filename.endswith(ext) for ext in ('.py', '.js', '.zip')):
        await update.message.reply_text("Only .py, .js, or .zip files are allowed", reply_markup=get_keyboard())
        return
    
    status = await update.message.reply_text(f"Downloading {filename}...")
    file_obj = await doc.get_file()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix)
    await file_obj.download_to_drive(tmp.name)
    
    mgr = ScriptManager(user_id)
    
    try:
        if filename.endswith('.zip'):
            await status.edit_text("Extracting ZIP...")
            with zipfile.ZipFile(tmp.name, 'r') as zf:
                extract_dir = tempfile.mkdtemp()
                zf.extractall(extract_dir)
                count = 0
                for root, _, files in os.walk(extract_dir):
                    for f in files:
                        if f.endswith(('.py', '.js')):
                            path = Path(root) / f
                            content = path.read_text(encoding='utf-8', errors='ignore')
                            typ = 'py' if f.endswith('.py') else 'js'
                            ok, msg = mgr.add_script(f, content, typ)
                            if ok:
                                count += 1
                shutil.rmtree(extract_dir)
                await status.edit_text(f"✅ Uploaded {count} scripts from ZIP", reply_markup=get_keyboard())
        else:
            content = Path(tmp.name).read_text(encoding='utf-8', errors='ignore')
            typ = 'py' if filename.endswith('.py') else 'js'
            ok, msg = mgr.add_script(filename, content, typ)
            await status.edit_text(msg, parse_mode="Markdown", reply_markup=get_keyboard())
    except Exception as e:
        await status.edit_text(f"❌ Error: {str(e)}", reply_markup=get_keyboard())
    finally:
        os.unlink(tmp.name)

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    scripts = mgr.list_scripts()
    
    if not scripts:
        await update.message.reply_text("No files uploaded yet. Use the Upload button!", reply_markup=get_keyboard())
        return
    
    text = "*Your Files:*\n\n"
    buttons = []
    for s in scripts:
        icon = "🟢" if s.is_running else "⚪"
        text += f"{icon} `{s.filename}` - {s.script_type.upper()}\n"
        text += f"   📅 {s.uploaded_at[:10]}\n\n"
        buttons.append([InlineKeyboardButton(f"{icon} {s.filename[:20]}", callback_data=f"file_{s.filename}")])
    
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /run <filename>")
        return
    
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    ok, msg = await mgr.run_script(" ".join(context.args))
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_keyboard())

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /stop <filename>")
        return
    
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    ok, msg = mgr.stop_script(" ".join(context.args))
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_keyboard())

async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /logs <filename>")
        return
    
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    logs = mgr.get_logs(" ".join(context.args))
    await update.message.reply_text(f"📄 Logs:\n```\n{logs}\n```", parse_mode="Markdown", reply_markup=get_keyboard())

async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delete <filename>")
        return
    
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    msg = mgr.delete_script(" ".join(context.args))
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_keyboard())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """*Available Commands:*

/start - Welcome screen
/upload - Upload .py/.js/.zip
/list - Show your files
/run <file> - Run a script
/stop <file> - Stop a script
/logs <file> - View output
/delete <file> - Delete a file
/help - Show this message

*Features:*
• Host Python & JavaScript
• Upload ZIP archives
• Free hosting
• 10 files max

Use buttons below for quick actions!"""
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_keyboard())

# Callback handler for buttons
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    
    if data == "upload":
        await query.message.reply_text("Send me a .py, .js, or .zip file!")
    
    elif data == "list":
        scripts = mgr.list_scripts()
        if not scripts:
            await query.message.reply_text("No files uploaded yet.")
        else:
            text = "*Your Files:*\n"
            for s in scripts:
                icon = "🟢" if s.is_running else "⚪"
                text += f"{icon} `{s.filename}`\n"
            await query.message.reply_text(text, parse_mode="Markdown")
    
    elif data == "home":
        await start(update, context)
    
    elif data == "shorts":
        await query.message.reply_text("📺 *Shorts*\n\nComing soon! Stay tuned for updates.", parse_mode="Markdown")
    
    elif data == "subscribe":
        await query.message.reply_text(
            "✅ *Subscribe*\n\nFollow @ethicalhacking13 for updates!\n\nJoin our channel for latest features.",
            parse_mode="Markdown"
        )
    
    elif data == "back":
        await start(update, context)
    
    elif data.startswith("file_"):
        filename = data[5:]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Run", callback_data=f"run_{filename}"),
             InlineKeyboardButton("⏹️ Stop", callback_data=f"stop_{filename}")],
            [InlineKeyboardButton("📄 Logs", callback_data=f"logs_{filename}"),
             InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{filename}")],
            [InlineKeyboardButton("🔙 Back", callback_data="list")]
        ])
        await query.edit_message_text(f"Options for `{filename}`", parse_mode="Markdown", reply_markup=kb)
    
    elif data.startswith("run_"):
        filename = data[4:]
        ok, msg = await mgr.run_script(filename)
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_keyboard())
    
    elif data.startswith("stop_"):
        filename = data[5:]
        ok, msg = mgr.stop_script(filename)
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_keyboard())
    
    elif data.startswith("logs_"):
        filename = data[5:]
        logs = mgr.get_logs(filename)
        await query.message.reply_text(f"📄 *Logs:*\n```\n{logs}\n```", parse_mode="Markdown", reply_markup=get_keyboard())
    
    elif data.startswith("delete_"):
        filename = data[7:]
        msg = mgr.delete_script(filename)
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_keyboard())

# ==================== MAIN ====================
async def main():
    print("="*50)
    print("🤖 Telegram Script Hosting Bot")
    print("="*50)
    print(f"✅ Bot Token: {'Loaded' if BOT_TOKEN else 'Missing'}")
    print(f"✅ Admin IDs: {ADMIN_IDS}")
    print(f"✅ Max Files: {MAX_FILES}")
    print(f"✅ Web Server: http://0.0.0.0:8000")
    print("="*50)
    print("🚀 Bot is running...")
    print("="*50)
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("upload", upload_handler))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("run", run_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("logs", logs_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())