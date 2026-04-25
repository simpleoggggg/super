#!/usr/bin/env python3
"""
Telegram Script Hosting Bot - Full Featured
- No Updater, only Application (python-telegram-bot v20.7)
- Web server on 0.0.0.0:8000
- Many commands (script hosting, system stats, admin, AI)
- Runs on Render 24/7
"""

import os
import sys
import subprocess
import asyncio
import threading
import json
import zipfile
import shutil
import tempfile
import re
import logging
import time
import platform
import psutil
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, asdict
from pathlib import Path
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ==================== INSTALL CORRECT VERSION ====================
def install_package(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet", "--no-cache-dir"])

try:
    import telegram
    ver = tuple(map(int, telegram.__version__.split('.')))
    if ver < (20, 0):
        install_package("python-telegram-bot==20.7")
except ImportError:
    install_package("python-telegram-bot==20.7")

# Additional packages for system info and web server
try:
    import psutil
except ImportError:
    install_package("psutil")
    import psutil
try:
    from flask import Flask
except ImportError:
    install_package("flask")
    from flask import Flask

# ==================== WEB SERVER (for Render health check) ====================
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running 24/7 | Script Hosting Bot"

@app_web.route('/health')
def health():
    return "OK", 200

def run_web_server():
    app_web.run(host='0.0.0.0', port=8000, debug=False, use_reloader=False)

threading.Thread(target=run_web_server, daemon=True).start()
print("🌐 Web server started on http://0.0.0.0:8000")

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8377202202:AAHxKZevXD5AhmQtoTjGKq9SjJ_nSJfnBiI"
ADMIN_IDS = [5696490206]
MAX_FILES = 20                     # Increased from 10
MAX_CONCURRENT_SCRIPTS = 5
SCRIPT_TIMEOUT = 600               # 10 minutes
WORK_DIR = Path("/tmp/script_hosting_bot")
WORK_DIR.mkdir(exist_ok=True)
START_TIME = datetime.now()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

running_processes = 0
process_lock = asyncio.Lock()

# ==================== AI ASSISTANT ====================
class AIAssistant:
    @staticmethod
    async def chat(question: str) -> str:
        q = question.lower()
        if any(w in q for w in ('error','syntax','bug','fix')):
            return "🔍 *Debugging help*\n• Use `/logs <file>` to see errors\n• Check indentation / brackets\n• Add print() statements\n• Share error message with me!"
        elif any(w in q for w in ('run','execute','start')):
            return "🚀 *Run a script*\n`/run filename.py`\nFirst upload with `/upload`"
        elif any(w in q for w in ('upload','add')):
            return "📤 *Upload*\nSend `.py`, `.js`, or `.zip` (multiple scripts)."
        elif any(w in q for w in ('stop','kill')):
            return "🛑 *Stop a script*\n`/stop filename.py`"
        elif any(w in q for w in ('log','output')):
            return "📄 *View logs*\n`/logs filename.py`"
        elif any(w in q for w in ('ping','status','alive')):
            return "🏓 Pong! Bot is alive and well."
        elif any(w in q for w in ('time','date')):
            return f"📅 Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        elif any(w in q for w in ('who are you','what are you')):
            return "🤖 I am a Script Hosting Bot that runs Python/JS scripts on the same server. I also provide AI chat and system stats."
        else:
            return f"🤖 *AI Assistant*\n\nAsk me about: debugging, running, uploading, logs, stopping, time, ping.\nExample: `/chat How to fix syntax error?`"
ai = AIAssistant()

# ==================== SCRIPT MANAGER ====================
@dataclass
class ScriptInfo:
    filename: str
    script_type: str
    uploaded_at: str
    is_running: bool
    process_id: Optional[int]
    started_at: Optional[str]
    insights: Dict

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
            return False, f"❌ Max files limit ({MAX_FILES}) reached. Delete some first."
        path = self.user_dir / filename
        if path.exists():
            return False, f"❌ '{filename}' already exists."
        path.write_text(content)
        lines = len(content.split('\n'))
        insights = {
            "type": script_type,
            "lines": lines,
            "complexity": "high" if lines > 200 else ("medium" if lines > 50 else "low"),
            "dependencies": [],
            "suggestions": []
        }
        if script_type == 'py':
            imports = re.findall(r'^(?:from|import)\s+(\w+)', content, re.MULTILINE)
            insights["dependencies"] = list(set(imports[:5]))
        else:
            requires = re.findall(r'require\([\'"]([^\'"]+)[\'"]\)', content)
            insights["dependencies"] = list(set(requires[:5]))
        self.scripts.append(ScriptInfo(
            filename, script_type, datetime.now().isoformat(),
            False, None, None, insights
        ))
        self.save()
        msg = f"✅ *Uploaded:* `{filename}`\n📊 {lines} lines | Complexity: {insights['complexity']}"
        if insights['dependencies']:
            msg += f"\n📦 Deps: {', '.join(insights['dependencies'][:3])}"
        return True, msg
    
    def delete_script(self, filename: str) -> str:
        path = self.user_dir / filename
        path.unlink(missing_ok=True)
        (self.user_dir / f"{filename}.log").unlink(missing_ok=True)
        self.scripts = [s for s in self.scripts if s.filename != filename]
        self.save()
        return f"🗑️ Deleted `{filename}`"
    
    def list_scripts(self) -> List[ScriptInfo]:
        return self.scripts
    
    async def run_script(self, filename: str) -> tuple:
        global running_processes
        script = next((s for s in self.scripts if s.filename == filename), None)
        if not script:
            return False, "❌ Script not found. Use `/list` to see your scripts."
        if script.is_running:
            return False, f"⚠️ `{filename}` is already running."
        path = self.user_dir / filename
        if not path.exists():
            return False, "❌ File missing. Re-upload."
        async with process_lock:
            if running_processes >= MAX_CONCURRENT_SCRIPTS:
                return False, f"❌ Too many concurrent scripts (max {MAX_CONCURRENT_SCRIPTS}). Stop some first."
            running_processes += 1
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
            asyncio.create_task(self._monitor_process(proc, filename, script))
            return True, f"🚀 *Running* `{filename}` (PID {proc.pid})\nUse `/logs {filename}` to see output."
        except Exception as e:
            async with process_lock:
                running_processes -= 1
            return False, f"❌ Failed to start: {str(e)}"
    
    async def _monitor_process(self, proc: asyncio.subprocess.Process, filename: str, script: ScriptInfo):
        global running_processes
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
            log_file = self.user_dir / f"{filename}.log"
            with open(log_file, 'a') as f:
                f.write(f"\n{'='*60}\nExecution at: {datetime.now()}\nPID: {proc.pid} | Exit: {proc.returncode}\n{'='*60}\n")
                if stdout:
                    f.write(f"STDOUT:\n{stdout.decode()}\n")
                if stderr:
                    f.write(f"STDERR:\n{stderr.decode()}\n")
        except asyncio.TimeoutError:
            proc.kill()
            log_file = self.user_dir / f"{filename}.log"
            with open(log_file, 'a') as f:
                f.write(f"\n⚠️ Script timed out after {SCRIPT_TIMEOUT} seconds and was killed.\n")
        finally:
            script.is_running = False
            script.process_id = None
            self.save()
            async with process_lock:
                running_processes -= 1
    
    def stop_script(self, filename: str) -> tuple:
        script = next((s for s in self.scripts if s.filename == filename), None)
        if script and script.is_running and script.process_id:
            try:
                os.kill(script.process_id, 9)
                script.is_running = False
                script.process_id = None
                self.save()
                return True, f"🛑 Stopped `{filename}`"
            except Exception:
                return False, "❌ Could not stop process."
        return False, f"⚠️ `{filename}` is not running."
    
    def get_logs(self, filename: str) -> str:
        log_file = self.user_dir / f"{filename}.log"
        if log_file.exists():
            content = log_file.read_text()
            if len(content) > 3900:
                return "...(truncated)\n\n" + content[-3900:]
            return content
        return "📭 No logs yet. Run the script first with `/run`"
    
    def get_insights(self, filename: str) -> Optional[Dict]:
        script = next((s for s in self.scripts if s.filename == filename), None)
        return script.insights if script else None

# ==================== ADDITIONAL HELPER FUNCTIONS ====================
def get_system_stats() -> str:
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime_seconds = (datetime.now() - START_TIME).total_seconds()
    uptime = str(timedelta(seconds=int(uptime_seconds)))
    return (f"🖥️ *System Stats*\n"
            f"• CPU: {cpu}%\n"
            f"• RAM: {mem.percent}% ({mem.used//1024//1024}MB/{mem.total//1024//1024}MB)\n"
            f"• Disk: {disk.percent}% ({disk.used//1024//1024}MB/{disk.total//1024//1024}MB)\n"
            f"• Uptime: {uptime}\n"
            f"• Processes: {len(psutil.pids())}")

# ==================== TELEGRAM COMMANDS ====================
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 UPLOAD", callback_data="upload"), InlineKeyboardButton("📋 SCRIPTS", callback_data="list")],
        [InlineKeyboardButton("🤖 AI CHAT", callback_data="ai_chat"), InlineKeyboardButton("📊 STATS", callback_data="stats")],
        [InlineKeyboardButton("🖥️ SYSTEM", callback_data="system"), InlineKeyboardButton("❓ HELP", callback_data="help")],
        [InlineKeyboardButton("👤 OWNER", url="https://t.me/ethicalhacking13")]
    ])

# ---- Basic commands ----
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    mgr = ScriptManager(uid)
    text = f"🤖 *Script Hosting Bot*\n\n👤 @{update.effective_user.username or 'User'}\n📁 Scripts: {len(mgr.list_scripts())}/{MAX_FILES}\n⚙️ Concurrent limit: {MAX_CONCURRENT_SCRIPTS}\n\nUse buttons below or /help."
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    help_text = f"""
*📚 All Commands*

*Script Hosting*
/upload – upload .py/.js/.zip
/list – show your scripts
/run <file> – execute script
/stop <file> – stop running script
/logs <file> – view output
/delete <file> – remove script
/ai – analyze all scripts
/chat <q> – AI assistant

*System & Info*
/stats – your usage statistics
/system – server CPU/RAM/disk
/ping – check bot response
/time – current server time
/uptime – bot uptime
/about – about this bot

*Admin Only* (for {ADMIN_IDS})
/restart_bot – restart the bot process
/ps – list running processes

*Limits*
• {MAX_FILES} files per user
• {MAX_CONCURRENT_SCRIPTS} concurrent scripts
• {SCRIPT_TIMEOUT}s max runtime

Use the buttons below for quick actions.
"""
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=main_keyboard())

async def ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    start = time.time()
    msg = await update.message.reply_text("🏓 Pinging...")
    end = time.time()
    await msg.edit_text(f"🏓 Pong! Latency: {round((end-start)*1000)}ms")

async def time_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🕐 Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

async def uptime_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uptime_seconds = (datetime.now() - START_TIME).total_seconds()
    uptime = str(timedelta(seconds=int(uptime_seconds)))
    await update.message.reply_text(f"⏱️ Bot uptime: {uptime}")

async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Script Hosting Bot*\nVersion 3.0\n"
        "Hosts Python and JavaScript scripts on the same server.\n"
        "Developer: @ethicalhacking13\n"
        "Built with python-telegram-bot v20.7"
    )

async def system_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = get_system_stats()
    await update.message.reply_text(stats, parse_mode="Markdown")

async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    mgr = ScriptManager(uid)
    scripts = mgr.list_scripts()
    running = sum(1 for s in scripts if s.is_running)
    text = f"📊 *Your Stats*\n\n📁 Scripts: {len(scripts)}/{MAX_FILES}\n▶️ Running: {running}\n⚙️ Max concurrent: {MAX_CONCURRENT_SCRIPTS}\n🐍 Python: {sum(1 for s in scripts if s.script_type=='py')}\n🟨 JS: {sum(1 for s in scripts if s.script_type=='js')}"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

# ---- Admin commands ----
async def restart_bot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.reply_text("🔄 Restarting bot...")
    os._exit(0)  # Force restart - Render will restart the process

async def ps_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    proc_list = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
        try:
            proc_list.append(f"{proc.info['pid']}: {proc.info['name']} ({proc.info['cpu_percent']}%)")
        except:
            pass
    text = "📋 *Processes*\n" + "\n".join(proc_list[:30])
    await update.message.reply_text(text[:4000], parse_mode="Markdown")

# ---- Script hosting commands (as before, but included) ----
async def upload_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not update.message.document:
        await update.message.reply_text("Send a `.py`, `.js`, or `.zip` file.", reply_markup=main_keyboard())
        return
    doc = update.message.document
    fname = doc.file_name
    if not any(fname.endswith(ext) for ext in ('.py','.js','.zip')):
        await update.message.reply_text("Only `.py`, `.js`, `.zip` allowed.", reply_markup=main_keyboard())
        return
    status = await update.message.reply_text(f"📥 Downloading `{fname}`...", parse_mode="Markdown")
    file_obj = await doc.get_file()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(fname).suffix)
    await file_obj.download_to_drive(tmp.name)
    mgr = ScriptManager(uid)
    try:
        if fname.endswith('.zip'):
            await status.edit_text("📦 Extracting ZIP...")
            with zipfile.ZipFile(tmp.name, 'r') as zf:
                extract_dir = tempfile.mkdtemp()
                zf.extractall(extract_dir)
                count = 0
                for root, _, files in os.walk(extract_dir):
                    for fn in files:
                        if fn.endswith(('.py','.js')):
                            path = Path(root) / fn
                            content = path.read_text(encoding='utf-8', errors='ignore')
                            typ = 'py' if fn.endswith('.py') else 'js'
                            ok, msg = mgr.add_script(fn, content, typ)
                            if ok:
                                count += 1
                shutil.rmtree(extract_dir)
                await status.edit_text(f"✅ Uploaded {count} scripts from ZIP.", reply_markup=main_keyboard())
        else:
            content = Path(tmp.name).read_text(encoding='utf-8', errors='ignore')
            typ = 'py' if fname.endswith('.py') else 'js'
            ok, msg = mgr.add_script(fname, content, typ)
            await status.edit_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}", reply_markup=main_keyboard())
    finally:
        os.unlink(tmp.name)

async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    mgr = ScriptManager(update.effective_user.id)
    scripts = mgr.list_scripts()
    if not scripts:
        await update.message.reply_text("No scripts. Use `/upload`.", reply_markup=main_keyboard())
        return
    text = "*Your scripts:*\n\n"
    kb = []
    for s in scripts:
        icon = "🟢" if s.is_running else "⚪"
        text += f"{icon} `{s.filename}`\n"
        kb.append([InlineKeyboardButton(f"{icon} {s.filename[:25]}", callback_data=f"script_{s.filename}")])
    kb.append([InlineKeyboardButton("🔙 MAIN", callback_data="main_menu")])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def run_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/run filename.py`", parse_mode="Markdown")
        return
    mgr = ScriptManager(update.effective_user.id)
    ok, msg = await mgr.run_script(" ".join(ctx.args))
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def stop_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/stop filename.py`", parse_mode="Markdown")
        return
    mgr = ScriptManager(update.effective_user.id)
    ok, msg = mgr.stop_script(" ".join(ctx.args))
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def logs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/logs filename.py`", parse_mode="Markdown")
        return
    mgr = ScriptManager(update.effective_user.id)
    out = mgr.get_logs(" ".join(ctx.args))
    await update.message.reply_text(f"📄 *Logs:*\n```\n{out}\n```", parse_mode="Markdown", reply_markup=main_keyboard())

async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/delete filename.py`", parse_mode="Markdown")
        return
    mgr = ScriptManager(update.effective_user.id)
    msg = mgr.delete_script(" ".join(ctx.args))
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def ai_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Ask me: `/chat your question`", parse_mode="Markdown", reply_markup=main_keyboard())
        return
    q = " ".join(ctx.args)
    resp = await ai.chat(q)
    await update.message.reply_text(resp, parse_mode="Markdown", reply_markup=main_keyboard())

async def analyze_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    mgr = ScriptManager(update.effective_user.id)
    scripts = mgr.list_scripts()
    if not scripts:
        await update.message.reply_text("No scripts to analyze.", reply_markup=main_keyboard())
        return
    text = "*🤖 AI Analysis*\n\n"
    for s in scripts[:7]:
        ins = s.insights
        text += f"📄 `{s.filename}`\n• Lines: {ins['lines']} | Complexity: {ins['complexity']}\n"
        if ins['dependencies']:
            text += f"• Deps: {', '.join(ins['dependencies'][:3])}\n"
        text += "\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

# ---- Callback handler for inline buttons ----
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id
    mgr = ScriptManager(uid)

    if data == "upload":
        await q.message.reply_text("Send a `.py`, `.js`, or `.zip` file.", reply_markup=main_keyboard())
    elif data == "list":
        scripts = mgr.list_scripts()
        if not scripts:
            await q.message.reply_text("No scripts.", reply_markup=main_keyboard())
        else:
            txt = "*Scripts:*\n"
            for s in scripts:
                icon = "🟢" if s.is_running else "⚪"
                txt += f"{icon} `{s.filename}`\n"
            await q.message.reply_text(txt, parse_mode="Markdown")
    elif data == "ai_chat":
        await q.message.reply_text("Ask: `/chat your question`", parse_mode="Markdown", reply_markup=main_keyboard())
    elif data == "stats":
        await stats_cmd(update, ctx)
    elif data == "system":
        await system_cmd(update, ctx)
    elif data == "help":
        await help_cmd(update, ctx)
    elif data == "main_menu":
        await q.message.reply_text("Main menu", reply_markup=main_keyboard())
    elif data.startswith("script_"):
        fn = data[7:]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ RUN", callback_data=f"run_{fn}"), InlineKeyboardButton("⏹️ STOP", callback_data=f"stop_{fn}")],
            [InlineKeyboardButton("📄 LOGS", callback_data=f"logs_{fn}"), InlineKeyboardButton("🔍 ANALYZE", callback_data=f"analyze_{fn}")],
            [InlineKeyboardButton("🗑️ DELETE", callback_data=f"delete_{fn}"), InlineKeyboardButton("◀️ BACK", callback_data="list")]
        ])
        await q.edit_message_text(f"Options for `{fn}`", parse_mode="Markdown", reply_markup=kb)
    elif data.startswith("run_"):
        fn = data[4:]
        ok, msg = await mgr.run_script(fn)
        await q.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
    elif data.startswith("stop_"):
        fn = data[5:]
        ok, msg = mgr.stop_script(fn)
        await q.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
    elif data.startswith("logs_"):
        fn = data[5:]
        out = mgr.get_logs(fn)
        await q.message.reply_text(f"```\n{out}\n```", parse_mode="Markdown", reply_markup=main_keyboard())
    elif data.startswith("delete_"):
        fn = data[7:]
        msg = mgr.delete_script(fn)
        await q.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
    elif data.startswith("analyze_"):
        fn = data[8:]
        ins = mgr.get_insights(fn)
        if ins:
            txt = f"*Analysis of `{fn}`*\nLines: {ins['lines']}\nComplexity: {ins['complexity']}\n"
            if ins['dependencies']:
                txt += f"Deps: {', '.join(ins['dependencies'])}\n"
            await q.message.reply_text(txt, parse_mode="Markdown", reply_markup=main_keyboard())
        else:
            await q.message.reply_text("No analysis data.", reply_markup=main_keyboard())

# ==================== MAIN ====================
async def main():
    print("🚀 Starting bot with web server on 0.0.0.0:8000")
    app = Application.builder().token(BOT_TOKEN).build()
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("upload", upload_handler))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("run", run_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("logs", logs_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("ai", analyze_cmd))
    app.add_handler(CommandHandler("chat", ai_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("system", system_cmd))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("time", time_cmd))
    app.add_handler(CommandHandler("uptime", uptime_cmd))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("restart_bot", restart_bot))
    app.add_handler(CommandHandler("ps", ps_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())