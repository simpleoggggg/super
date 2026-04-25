#!/usr/bin/env python3
"""
Telegram Script Hosting Bot - FULL VERSION
All features included, no pkg_resources needed
"""

import os
import sys
import subprocess

# ==================== AUTO INSTALL DEPENDENCIES ====================
def install_package(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet", "--no-cache-dir"])

try:
    import telegram
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
except ImportError:
    print("📦 Installing python-telegram-bot...")
    install_package("python-telegram-bot==20.7")
    import telegram
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Standard library imports
import asyncio
import zipfile
import shutil
import tempfile
import json
import re
import logging
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8377202202:AAHxKZevXD5AhmQtoTjGKq9SjJ_nSJfnBiI"
ADMIN_IDS = [5696490206]
MAX_FILES = 10
WORK_DIR = Path("/tmp/script_hosting_bot")
WORK_DIR.mkdir(exist_ok=True)

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== AI ASSISTANT (NO API KEY) ====================
class AIAssistant:
    @staticmethod
    async def chat(question: str) -> str:
        q = question.lower()
        if any(w in q for w in ['error', 'syntax', 'bug', 'fix']):
            return "🔍 *Debugging Help*\n\n• Use `/logs <file>` to see exact error\n• Check colons, brackets, indentation\n• Verify variable names\n• Add print() statements to trace\n\nShare the error message with me!"
        elif any(w in q for w in ['run', 'execute', 'start']):
            return "🚀 *Run a Script*\n\n`/run filename.py`\n\n1. Upload with `/upload`\n2. Check `/list` for uploaded files\n3. Run with `/run`\n4. See output with `/logs`"
        elif any(w in q for w in ['upload', 'add', 'send']):
            return "📤 *Uploading Scripts*\n\n• Single file: send `.py` or `.js`\n• Multiple files: pack into `.zip`\n• Max 10 files total\n• Use `/list` to see uploaded files"
        elif any(w in q for w in ['stop', 'kill', 'terminate']):
            return "🛑 *Stop a Script*\n\n`/stop filename.py`\n\nStops a running script. Use `/list` to see which are running (🟢)."
        elif any(w in q for w in ['log', 'output', 'see']):
            return "📄 *View Logs/Output*\n\n`/logs filename.py`\n\nShows all print statements, errors, and execution details from your script."
        elif any(w in q for w in ['delete', 'remove']):
            return "🗑️ *Delete a Script*\n\n`/delete filename.py`\n\nPermanently removes the script and its logs."
        elif any(w in q for w in ['list', 'show', 'scripts']):
            return "📋 *List Scripts*\n\n`/list`\n\nShows all your uploaded scripts with running status (🟢 = running, ⚪ = stopped)."
        elif any(w in q for w in ['analyze', 'check', 'inspect']):
            return "🔍 *Script Analysis*\n\n`/ai`\n\nGet insights about your scripts: lines, complexity, dependencies, suggestions."
        else:
            return f"🤖 *AI Assistant*\n\nI can help with:\n• Debugging errors 🐛\n• Running scripts 🚀\n• Uploading files 📤\n• Viewing logs 📄\n• Stopping scripts 🛑\n\n*Try:* `/chat How to fix syntax error?`\n\nAsk me anything about script hosting!"

# ==================== SCRIPT ANALYZER ====================
class ScriptAnalyzer:
    @staticmethod
    def analyze(content: str, filename: str) -> Dict:
        lines = len(content.split('\n'))
        insights = {
            "type": "python" if filename.endswith('.py') else "javascript",
            "lines": lines,
            "complexity": "low",
            "dependencies": [],
            "suggestions": [],
            "has_errors": False,
            "error_msg": None
        }
        if filename.endswith('.py'):
            imports = re.findall(r'^(?:from|import)\s+(\w+)', content, re.MULTILINE)
            insights["dependencies"] = list(set(imports[:5]))
            if 'while True' in content and 'break' not in content:
                insights["suggestions"].append("⚠️ Infinite loop without break")
            if 'input(' in content:
                insights["suggestions"].append("💡 Script requires user input – may not work headless")
            if 'os.system' in content:
                insights["suggestions"].append("⚠️ Uses os.system – consider subprocess for safety")
            try:
                compile(content, filename, 'exec')
            except SyntaxError as e:
                insights["has_errors"] = True
                insights["error_msg"] = str(e)
                insights["suggestions"].append(f"❌ Syntax error: {e}")
        else:  # JavaScript
            requires = re.findall(r'require\([\'"]([^\'"]+)[\'"]\)', content)
            insights["dependencies"] = list(set(requires[:5]))
            if 'setInterval' in content and 'clearInterval' not in content:
                insights["suggestions"].append("⚠️ Interval without clear – may run forever")
            if 'var ' in content:
                insights["suggestions"].append("💡 Use 'let' or 'const' instead of 'var'")
        if lines > 200:
            insights["complexity"] = "high"
        elif lines > 50:
            insights["complexity"] = "medium"
        return insights

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
            with open(self.scripts_file, 'r') as f:
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
            return False, f"❌ '{filename}' already exists. Delete it first or rename."
        with open(path, 'w') as f:
            f.write(content)
        insights = ScriptAnalyzer.analyze(content, filename)
        self.scripts.append(ScriptInfo(
            filename=filename,
            script_type=script_type,
            uploaded_at=datetime.now().isoformat(),
            is_running=False,
            process_id=None,
            started_at=None,
            insights=insights
        ))
        self.save()
        msg = f"✅ *Uploaded:* `{filename}`\n📊 {insights['lines']} lines | Complexity: {insights['complexity']}"
        if insights['dependencies']:
            msg += f"\n📦 Imports: {', '.join(insights['dependencies'][:3])}"
        if insights['suggestions']:
            msg += f"\n💡 {insights['suggestions'][0]}"
        return True, msg
    
    def delete_script(self, filename: str) -> str:
        path = self.user_dir / filename
        path.unlink(missing_ok=True)
        log = self.user_dir / f"{filename}.log"
        log.unlink(missing_ok=True)
        self.scripts = [s for s in self.scripts if s.filename != filename]
        self.save()
        return f"🗑️ Deleted `{filename}`"
    
    def list_scripts(self) -> List[ScriptInfo]:
        return self.scripts
    
    async def run_script(self, filename: str) -> tuple:
        script = next((s for s in self.scripts if s.filename == filename), None)
        if not script:
            return False, "❌ Script not found. Use `/list` to see your scripts."
        if script.is_running:
            return False, f"⚠️ `{filename}` is already running. Stop it first with `/stop {filename}`"
        path = self.user_dir / filename
        if not path.exists():
            return False, "❌ File missing. Please re-upload."
        try:
            if script.script_type == 'py':
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, str(path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            else:  # js
                # Quick check if node is available
                try:
                    await asyncio.create_subprocess_exec("node", "--version")
                except:
                    return False, "❌ Node.js is not installed on this server. JavaScript scripts cannot run."
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
            return True, f"🚀 *Running* `{filename}`\n🆔 PID: {proc.pid}\n📝 Use `/logs {filename}` to see output."
        except Exception as e:
            return False, f"❌ Failed to run: {str(e)}"
    
    async def _monitor(self, proc: asyncio.subprocess.Process, filename: str, script: ScriptInfo):
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            log_file = self.user_dir / f"{filename}.log"
            with open(log_file, 'a') as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"Execution at: {datetime.now()}\n")
                f.write(f"PID: {proc.pid} | Exit code: {proc.returncode}\n")
                f.write(f"{'='*60}\n")
                if stdout:
                    f.write(f"STDOUT:\n{stdout.decode()}\n")
                if stderr:
                    f.write(f"STDERR:\n{stderr.decode()}\n")
        except asyncio.TimeoutError:
            proc.kill()
            log_file = self.user_dir / f"{filename}.log"
            with open(log_file, 'a') as f:
                f.write(f"\n⚠️ Script timed out after 5 minutes and was killed.\n")
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
            except Exception as e:
                return False, f"❌ Could not stop: {str(e)}"
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

# ==================== TELEGRAM HANDLERS ====================
def main_keyboard():
    """Main inline keyboard with all buttons at bottom"""
    keyboard = [
        [InlineKeyboardButton("📤 UPLOAD FILE", callback_data="upload"),
         InlineKeyboardButton("📋 MY SCRIPTS", callback_data="list")],
        [InlineKeyboardButton("🤖 AI CHAT", callback_data="ai_chat"),
         InlineKeyboardButton("📊 STATISTICS", callback_data="stats")],
        [InlineKeyboardButton("❓ HELP MENU", callback_data="help"),
         InlineKeyboardButton("👤 CONTACT OWNER", url="https://t.me/ethicalhacking13")],
        [InlineKeyboardButton("📢 UPDATES CHANNEL", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def script_options_keyboard(filename: str):
    """Keyboard for individual script actions"""
    keyboard = [
        [InlineKeyboardButton("▶️ RUN", callback_data=f"run_{filename}"),
         InlineKeyboardButton("⏹️ STOP", callback_data=f"stop_{filename}")],
        [InlineKeyboardButton("📄 VIEW LOGS", callback_data=f"logs_{filename}"),
         InlineKeyboardButton("🔍 ANALYZE", callback_data=f"analyze_{filename}")],
        [InlineKeyboardButton("🗑️ DELETE", callback_data=f"delete_{filename}"),
         InlineKeyboardButton("◀️ BACK", callback_data="list")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    mgr = ScriptManager(user.id)
    text = f"""╔══════════════════════════════════════════╗
║     🤖 SCRIPT HOSTING BOT - READY!      ║
╚══════════════════════════════════════════╝

📊 *YOUR STATUS*
• User: @{user.username or 'User'}
• ID: `{user.id}`
• Scripts: {len(mgr.list_scripts())}/{MAX_FILES}

✨ *FEATURES*
• Host Python (.py) & JavaScript (.js)
• AI script analysis
• Smart chat assistant (no API key)
• ZIP batch upload
• Real-time execution logs

🚀 *QUICK START*
Use buttons below or type commands.

Type `/help` for all commands.
"""
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_txt = f"""╔══════════════════════════════════════════╗
║           📚 COMPLETE COMMANDS           ║
╚══════════════════════════════════════════╝

*BASIC COMMANDS*
/start – Main menu & status
/help – This help message
/upload – Upload .py, .js, or .zip
/list – Show all your scripts
/stats – Your usage statistics

*SCRIPT CONTROL*
/run <file> – Execute a script
/stop <file> – Stop a running script
/logs <file> – View output & errors
/delete <file> – Permanently remove script
/ai – Analyze all scripts (AI insights)

*AI FEATURES*
/chat <question> – Ask AI assistant anything

*EXAMPLES*
1. Upload: `/upload` (then send file)
2. Run: `/run mybot.py`
3. Check output: `/logs mybot.py`
4. Stop: `/stop mybot.py`
5. Delete: `/delete mybot.py`
6. Ask AI: `/chat How to fix syntax error?`

*ZIP UPLOAD*
Pack multiple .py/.js files in a ZIP and upload once.

*LIMITS*
• Max {MAX_FILES} files per user
• 5 minutes max execution time
• 10MB max file size

💡 *TIP*: Use the buttons below for quick actions!
"""
    await update.message.reply_text(help_txt, parse_mode="Markdown", reply_markup=main_keyboard())

async def upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message.document:
        await update.message.reply_text(
            "📎 *Send me a file!*\n\nSupported:\n• `.py` – Python script\n• `.js` – JavaScript\n• `.zip` – multiple scripts\n\nJust send the file directly.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return
    
    doc = update.message.document
    filename = doc.file_name
    if not any(filename.endswith(ext) for ext in ('.py', '.js', '.zip')):
        await update.message.reply_text(
            f"❌ *Invalid file type:* `{filename}`\n\nOnly `.py`, `.js`, or `.zip` allowed.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return
    
    status_msg = await update.message.reply_text(f"📥 Downloading `{filename}`...", parse_mode="Markdown")
    file_obj = await doc.get_file()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix)
    await file_obj.download_to_drive(tmp.name)
    
    mgr = ScriptManager(user_id)
    try:
        if filename.endswith('.zip'):
            await status_msg.edit_text("📦 Extracting ZIP archive...", parse_mode="Markdown")
            with zipfile.ZipFile(tmp.name, 'r') as zipf:
                extract_dir = tempfile.mkdtemp()
                zipf.extractall(extract_dir)
                uploaded = 0
                errors = []
                for root, _, files in os.walk(extract_dir):
                    for f in files:
                        if f.endswith(('.py', '.js')):
                            path = Path(root) / f
                            with open(path, 'r', encoding='utf-8', errors='ignore') as code:
                                content = code.read()
                            st = 'py' if f.endswith('.py') else 'js'
                            ok, msg = mgr.add_script(f, content, st)
                            if ok:
                                uploaded += 1
                            else:
                                errors.append(msg)
                shutil.rmtree(extract_dir)
                result = f"✅ Uploaded {uploaded} scripts from ZIP."
                if errors:
                    result += f"\n⚠️ Some issues: {errors[0]}"
            await status_msg.edit_text(result, parse_mode="Markdown", reply_markup=main_keyboard())
        else:
            with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as code:
                content = code.read()
            st = 'py' if filename.endswith('.py') else 'js'
            ok, msg = mgr.add_script(filename, content, st)
            await status_msg.edit_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}", reply_markup=main_keyboard())
    finally:
        os.unlink(tmp.name)

async def list_scripts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    scripts = mgr.list_scripts()
    if not scripts:
        await update.message.reply_text(
            "📭 *No scripts yet!*\n\nUse `/upload` to add your first script.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return
    
    text = "*📚 YOUR SCRIPTS*\n\n"
    for i, s in enumerate(scripts[:10], 1):
        icon = "🟢" if s.is_running else "⚪"
        complexity_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(s.insights.get("complexity","low"), "⚪")
        text += f"{i}. {icon} `{s.filename}`\n"
        text += f"   📦 {s.script_type.upper()} | {complexity_icon} Complexity: {s.insights.get('complexity','low')}\n"
        text += f"   📅 Uploaded: {s.uploaded_at[:10]}\n\n"
    
    # Build inline keyboard with script buttons
    keyboard = []
    for s in scripts[:10]:
        icon = "🟢" if s.is_running else "⚪"
        keyboard.append([InlineKeyboardButton(f"{icon} {s.filename[:30]}", callback_data=f"script_{s.filename}")])
    keyboard.append([InlineKeyboardButton("🔙 MAIN MENU", callback_data="main_menu")])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📝 *Usage:* `/run <filename>`\n\nExample: `/run my_script.py`\nUse `/list` to see your scripts.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return
    filename = " ".join(context.args)
    mgr = ScriptManager(update.effective_user.id)
    ok, msg = await mgr.run_script(filename)
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📝 *Usage:* `/stop <filename>`\n\nExample: `/stop my_script.py`",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return
    filename = " ".join(context.args)
    mgr = ScriptManager(update.effective_user.id)
    ok, msg = mgr.stop_script(filename)
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📝 *Usage:* `/logs <filename>`\n\nExample: `/logs my_script.py`",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return
    filename = " ".join(context.args)
    mgr = ScriptManager(update.effective_user.id)
    logs = mgr.get_logs(filename)
    await update.message.reply_text(
        f"📄 *Logs for `{filename}`:*\n```\n{logs}\n```",
        parse_mode="Markdown", reply_markup=main_keyboard()
    )

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📝 *Usage:* `/delete <filename>`\n\nExample: `/delete my_script.py`",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return
    filename = " ".join(context.args)
    mgr = ScriptManager(update.effective_user.id)
    msg = mgr.delete_script(filename)
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())

async def ai_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    scripts = mgr.list_scripts()
    if not scripts:
        await update.message.reply_text(
            "📭 *No scripts to analyze.*\n\nUpload a script first with `/upload`.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return
    text = "*🤖 AI SCRIPT ANALYSIS*\n\n"
    for s in scripts[:5]:
        i = s.insights
        text += f"📄 `{s.filename}`\n"
        text += f"• Type: {i.get('type','unknown')}\n"
        text += f"• Lines: {i.get('lines',0)}\n"
        text += f"• Complexity: {i.get('complexity','low')}\n"
        if i.get('dependencies'):
            text += f"• Dependencies: {', '.join(i['dependencies'][:3])}\n"
        if i.get('suggestions'):
            text += f"• 💡 {i['suggestions'][0]}\n"
        text += "\n"
    if len(scripts) > 5:
        text += f"✨ And {len(scripts)-5} more scripts... Use `/list` to see all."
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def chat_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🤖 *AI CHAT ASSISTANT*\n\nAsk me anything about:\n• Script debugging 🐛\n• Code optimization ⚡\n• Error fixing 🔧\n• Best practices 📚\n\n*Examples:*\n`/chat How to fix syntax error?`\n`/chat Why is my script crashing?`\n\nType `/chat <your question>`",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return
    question = " ".join(context.args)
    thinking = await update.message.reply_text("🤔 *Thinking...*", parse_mode="Markdown")
    response = await AIAssistant.chat(question)
    await thinking.edit_text(response, parse_mode="Markdown", reply_markup=main_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    scripts = mgr.list_scripts()
    running = sum(1 for s in scripts if s.is_running)
    total_size = 0
    for s in scripts:
        p = mgr.user_dir / s.filename
        if p.exists():
            total_size += p.stat().st_size
    text = f"""╔══════════════════════════════════════════╗
║           📊 YOUR STATISTICS           ║
╚══════════════════════════════════════════╝

👤 *User ID:* `{user_id}`
📁 *Total scripts:* {len(scripts)} / {MAX_FILES}
▶️ *Running:* {running}
⏹️ *Stopped:* {len(scripts)-running}

📈 *BREAKDOWN*
• Python: {sum(1 for s in scripts if s.script_type == 'py')}
• JavaScript: {sum(1 for s in scripts if s.script_type == 'js')}

🎯 *COMPLEXITY*
• High: {sum(1 for s in scripts if s.insights.get('complexity') == 'high')}
• Medium: {sum(1 for s in scripts if s.insights.get('complexity') == 'medium')}
• Low: {sum(1 for s in scripts if s.insights.get('complexity') == 'low')}

💾 *Storage used:* {total_size // 1024} KB

🤖 *AI Assistant:* Active (no API key needed)"""
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    mgr = ScriptManager(user_id)
    
    if data == "upload":
        await query.message.reply_text(
            "📎 *Send me your file!*\n\nSupported: `.py`, `.js`, `.zip`\nJust send the file directly.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
    elif data == "list":
        scripts = mgr.list_scripts()
        if not scripts:
            await query.message.reply_text("📭 No scripts yet. Use /upload.", reply_markup=main_keyboard())
        else:
            txt = "*Your scripts:*\n"
            for s in scripts[:15]:
                icon = "🟢" if s.is_running else "⚪"
                txt += f"{icon} `{s.filename}`\n"
            await query.message.reply_text(txt, parse_mode="Markdown")
    elif data == "ai_chat":
        await query.message.reply_text(
            "🤖 *AI Chat*\n\nType: `/chat your question`\nExample: `/chat How to fix my code?`",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
    elif data == "stats":
        await stats_command(update, context)
    elif data == "help":
        await help_command(update, context)
    elif data == "main_menu":
        await query.message.reply_text("🔙 *Main Menu*", parse_mode="Markdown", reply_markup=main_keyboard())
    elif data.startswith("script_"):
        filename = data[7:]
        await query.edit_message_text(
            f"📄 *Options for* `{filename}`",
            parse_mode="Markdown", reply_markup=script_options_keyboard(filename)
        )
    elif data.startswith("run_"):
        filename = data[4:]
        ok, msg = await mgr.run_script(filename)
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
    elif data.startswith("stop_"):
        filename = data[5:]
        ok, msg = mgr.stop_script(filename)
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
    elif data.startswith("logs_"):
        filename = data[5:]
        logs = mgr.get_logs(filename)
        await query.message.reply_text(
            f"📄 *Logs for `{filename}`:*\n```\n{logs}\n```",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
    elif data.startswith("delete_"):
        filename = data[7:]
        msg = mgr.delete_script(filename)
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
    elif data.startswith("analyze_"):
        filename = data[8:]
        insights = mgr.get_insights(filename)
        if insights:
            txt = f"🔍 *Analysis for* `{filename}`\n\n"
            txt += f"Type: {insights.get('type','unknown')}\n"
            txt += f"Lines: {insights.get('lines',0)}\n"
            txt += f"Complexity: {insights.get('complexity','unknown')}\n"
            if insights.get('dependencies'):
                txt += f"Dependencies: {', '.join(insights['dependencies'][:4])}\n"
            if insights.get('suggestions'):
                txt += f"\n💡 *Suggestions:*\n• " + "\n• ".join(insights['suggestions'][:3])
            await query.message.reply_text(txt, parse_mode="Markdown", reply_markup=main_keyboard())
        else:
            await query.message.reply_text("No analysis data.", reply_markup=main_keyboard())

# ==================== MAIN ====================
async def main():
    print("\n" + "="*60)
    print("🤖 TELEGRAM SCRIPT HOSTING BOT - FULL VERSION")
    print("="*60)
    print(f"✅ Bot Token: Loaded")
    print(f"✅ Admin ID: {ADMIN_IDS[0]}")
    print(f"✅ Max files per user: {MAX_FILES}")
    print(f"✅ AI Chat: Active (no API key)")
    print(f"📁 Work directory: {WORK_DIR}")
    print("="*60)
    print("🚀 Bot is starting... Press Ctrl+C to stop.")
    print("="*60 + "\n")
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("upload", upload_handler))
    app.add_handler(CommandHandler("list", list_scripts))
    app.add_handler(CommandHandler("run", run_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("ai", ai_analyze))
    app.add_handler(CommandHandler("chat", chat_ai))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped.")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
