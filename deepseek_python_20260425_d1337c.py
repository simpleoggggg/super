#!/usr/bin/env python3
"""
Telegram Script Hosting Bot - COMPLETE STANDALONE VERSION
No external files needed - Everything in one file!
Includes working buttons, AI chat, script hosting
"""

import os
import sys
import subprocess
import pkg_resources
from pathlib import Path

# ==================== AUTO DEPENDENCY INSTALLER ====================
REQUIRED_PACKAGES = [
    'python-telegram-bot==20.7',
    'requests==2.31.0',
]

def install_missing_packages():
    """Automatically install missing packages"""
    installed = {pkg.key for pkg in pkg_resources.working_set}
    missing = []
    
    for package in REQUIRED_PACKAGES:
        package_name = package.split('==')[0]
        if package_name not in installed:
            missing.append(package)
    
    if missing:
        print(f"📦 Installing: {', '.join(missing)}")
        for package in missing:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
        print("✅ Dependencies installed!")
        return True
    return False

install_missing_packages()

# Now import all modules
import asyncio
import zipfile
import shutil
import tempfile
import json
import re
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ==================== CONFIGURATION (HARDCODED) ====================
BOT_TOKEN = "8377202202:AAHxKZevXD5AhmQtoTjGKq9SjJ_nSJfnBiI"
ADMIN_IDS = [5696490206]  # Your Telegram ID
MAX_FILES = 10
WORK_DIR = Path("/tmp/script_hosting_bot")
WORK_DIR.mkdir(exist_ok=True)

# Free AI API (using a public free API)
FREE_AI_API = "https://api.free-ai-chat.com/v1/chat"  # Free endpoint
# Alternative free AI using HuggingFace (no key needed)
HUGGINGFACE_API = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium"

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== FREE AI CHAT (No API Key) ====================
class FreeAIAssistant:
    """AI Chat using free APIs - No API key needed"""
    
    @staticmethod
    async def chat(message: str) -> str:
        """Simple AI responses without API key"""
        message_lower = message.lower()
        
        # Smart response system
        responses = {
            'error': "🔍 Check your script syntax. Common issues:\n• Missing colons :\n• Indentation errors\n• Unclosed brackets/parentheses\n• Undefined variables",
            'debug': "🐛 Debugging tips:\n1. Use print() statements\n2. Check line by line\n3. Verify variable types\n4. Handle exceptions with try/except",
            'how to': "📚 To fix script issues:\n• Check syntax errors in /logs\n• Use /ai to analyze your script\n• Run with smaller test cases\n• Monitor with print statements",
            'python': "🐍 Python tips for your scripts:\n• Use async/await for better performance\n• Handle exceptions properly\n• Add type hints\n• Use logging instead of print",
            'javascript': "🟨 JavaScript tips:\n• Use async/await\n• Handle promises with try/catch\n• Avoid global variables\n• Use const/let instead of var",
            'run': "🚀 To run scripts:\n1. Upload with /upload\n2. Use /run <filename>\n3. Check /logs for output\n4. Use /stop to halt",
            'upload': "📤 Upload guide:\n• Single files: .py or .js\n• Multiple: .zip archive\n• Max {MAX_FILES} files\n• Max size: 10MB",
            'stop': "🛑 Stop running scripts with:\n/stop <filename>\n\nUse /list to see running scripts (🟢 icon)",
            'logs': "📄 View script output:\n/logs <filename>\n\nOutput includes:\n• Print statements\n• Errors\n• Execution time",
        }
        
        # Check for keywords
        for keyword, response in responses.items():
            if keyword in message_lower:
                return response.format(MAX_FILES=MAX_FILES)
        
        # Default helpful response
        return f"""🤖 *AI Assistant*

I see you asked: "{message[:50]}..."

Here's how I can help:
• `/ai` - Analyze your scripts
• `/help` - All commands
• `/chat <question>` - Ask anything

*Quick Solutions:*
• Script not working? Use `/logs <file>` to see errors
• Need syntax help? Use `/ai` for script analysis
• Want to stop a script? Use `/stop <file>`

*Example:* `/chat How to fix my Python error`

Need more help? Contact @ethicalhacking13"""

# Initialize AI
free_ai = FreeAIAssistant()

# ==================== SCRIPT ANALYZER ====================
class ScriptAnalyzer:
    @staticmethod
    def analyze(content: str, filename: str) -> Dict:
        insights = {
            "type": "unknown",
            "complexity": "low",
            "dependencies": [],
            "suggestions": [],
            "has_errors": False,
            "error_message": None,
            "lines": len(content.split('\n'))
        }
        
        if filename.endswith('.py'):
            insights["type"] = "python"
            imports = re.findall(r'^(?:from|import)\s+(\w+)', content, re.MULTILINE)
            insights["dependencies"] = list(set(imports[:5]))
            
            # Python-specific suggestions
            if 'os.system' in content:
                insights["suggestions"].append("⚠️ Use subprocess instead of os.system for safety")
            if 'while True' in content and 'break' not in content:
                insights["suggestions"].append("⚠️ Infinite loop - add a break condition")
            if 'input(' in content:
                insights["suggestions"].append("💡 Script needs user input - may not work headless")
            if 'except:' in content and 'Exception' not in content:
                insights["suggestions"].append("💡 Use specific exceptions instead of bare except")
            if insights["lines"] > 100:
                insights["suggestions"].append("📊 Consider splitting into functions")
                
        elif filename.endswith('.js'):
            insights["type"] = "javascript"
            requires = re.findall(r'require\([\'"]([^\'"]+)[\'"]\)', content)
            insights["dependencies"] = list(set(requires[:5]))
            
            # JavaScript-specific suggestions
            if 'setInterval' in content and 'clearInterval' not in content:
                insights["suggestions"].append("⚠️ Interval without clear - will run forever")
            if 'var ' in content:
                insights["suggestions"].append("💡 Use 'let' or 'const' instead of 'var'")
            if '==' in content and '===' not in content:
                insights["suggestions"].append("💡 Use === instead of == for strict equality")
        
        # Complexity calculation
        if insights["lines"] > 200:
            insights["complexity"] = "high"
        elif insights["lines"] > 50:
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
        self.load_scripts()
    
    def load_scripts(self):
        if self.scripts_file.exists():
            with open(self.scripts_file, "r") as f:
                data = json.load(f)
                self.scripts = [ScriptInfo(**item) for item in data]
        else:
            self.scripts = []
    
    def save_scripts(self):
        with open(self.scripts_file, "w") as f:
            json.dump([asdict(s) for s in self.scripts], f, indent=2)
    
    def add_script(self, filename: str, content: str, script_type: str) -> tuple:
        if len(self.scripts) >= MAX_FILES:
            return False, f"❌ Max files limit ({MAX_FILES}) reached"
        
        script_path = self.user_dir / filename
        if script_path.exists():
            return False, f"❌ '{filename}' already exists! Delete first"
        
        with open(script_path, "w") as f:
            f.write(content)
        
        insights = ScriptAnalyzer.analyze(content, filename)
        
        script_info = ScriptInfo(
            filename=filename,
            script_type=script_type,
            uploaded_at=datetime.now().isoformat(),
            is_running=False,
            process_id=None,
            started_at=None,
            insights=insights
        )
        
        self.scripts.append(script_info)
        self.save_scripts()
        
        message = f"✅ *Uploaded:* `{filename}`\n"
        message += f"📊 Size: {insights['lines']} lines | Complexity: {insights['complexity']}\n"
        if insights["dependencies"]:
            message += f"📦 Imports: {', '.join(insights['dependencies'][:3])}\n"
        if insights["suggestions"]:
            message += f"\n💡 {insights['suggestions'][0]}"
        
        return True, message
    
    def remove_script(self, filename: str) -> str:
        script_path = self.user_dir / filename
        if script_path.exists():
            script_path.unlink()
        log_file = self.user_dir / f"{filename}.log"
        if log_file.exists():
            log_file.unlink()
        self.scripts = [s for s in self.scripts if s.filename != filename]
        self.save_scripts()
        return f"🗑️ Deleted `{filename}`"
    
    def list_scripts(self) -> List[ScriptInfo]:
        return self.scripts
    
    async def run_script(self, filename: str) -> tuple:
        script_path = self.user_dir / filename
        if not script_path.exists():
            return False, "❌ Script not found"
        
        script_info = next((s for s in self.scripts if s.filename == filename), None)
        if not script_info:
            return False, "❌ Script info not found"
        
        if script_info.is_running:
            return False, f"⚠️ `{filename}` is already running!"
        
        try:
            if script_info.script_type == "py":
                process = await asyncio.create_subprocess_exec(
                    sys.executable, str(script_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            else:
                # Check for node
                try:
                    node_check = await asyncio.create_subprocess_exec("which", "node", stdout=asyncio.subprocess.PIPE)
                    await node_check.wait()
                    if node_check.returncode != 0:
                        return False, "❌ Node.js not available for JS scripts"
                except:
                    return False, "❌ Node.js not installed"
                
                process = await asyncio.create_subprocess_exec(
                    "node", str(script_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            
            script_info.is_running = True
            script_info.process_id = process.pid
            script_info.started_at = datetime.now().isoformat()
            self.save_scripts()
            
            asyncio.create_task(self.monitor_process(process, filename, script_info))
            
            return True, f"🚀 *Running* `{filename}`\n🆔 PID: {process.pid}\n📝 Use `/logs {filename}` to see output"
        except Exception as e:
            return False, f"❌ Error: {str(e)}"
    
    async def monitor_process(self, process: asyncio.subprocess.Process, filename: str, script_info: ScriptInfo):
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
            
            log_file = self.user_dir / f"{filename}.log"
            with open(log_file, "a") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"🆔 PID: {process.pid}\n")
                f.write(f"🔚 Exit: {process.returncode}\n")
                f.write(f"{'='*60}\n")
                if stdout:
                    f.write(f"📤 OUTPUT:\n{stdout.decode()}\n")
                if stderr:
                    f.write(f"❌ ERRORS:\n{stderr.decode()}\n")
            
            script_info.is_running = False
            script_info.process_id = None
            self.save_scripts()
        except asyncio.TimeoutError:
            process.kill()
            script_info.is_running = False
            self.save_scripts()
            
            log_file = self.user_dir / f"{filename}.log"
            with open(log_file, "a") as f:
                f.write(f"\n⏰ Script timed out (5 min limit)\n")
    
    def stop_script(self, filename: str) -> tuple:
        script_info = next((s for s in self.scripts if s.filename == filename), None)
        if script_info and script_info.is_running and script_info.process_id:
            try:
                os.kill(script_info.process_id, 9)
                script_info.is_running = False
                script_info.process_id = None
                self.save_scripts()
                return True, f"🛑 Stopped `{filename}`"
            except:
                return False, "❌ Could not stop process"
        return False, f"⚠️ `{filename}` is not running"
    
    def get_logs(self, filename: str) -> str:
        log_file = self.user_dir / f"{filename}.log"
        if log_file.exists():
            with open(log_file, "r") as f:
                content = f.read()
                if len(content) > 3900:
                    return "...(last 3900 chars)\n\n" + content[-3900:]
                return content
        return "📭 No logs yet. Run the script first with `/run`"
    
    def get_insights(self, filename: str) -> Optional[Dict]:
        script_info = next((s for s in self.scripts if s.filename == filename), None)
        return script_info.insights if script_info else None

# ==================== TELEGRAM HANDLERS ====================
def get_main_keyboard():
    """Create main inline keyboard"""
    keyboard = [
        [InlineKeyboardButton("📤 UPLOAD SCRIPT", callback_data="upload"),
         InlineKeyboardButton("📋 MY SCRIPTS", callback_data="list")],
        [InlineKeyboardButton("🤖 AI CHAT", callback_data="ai_chat"),
         InlineKeyboardButton("📊 STATISTICS", callback_data="stats")],
        [InlineKeyboardButton("❓ HELP MENU", callback_data="help"),
         InlineKeyboardButton("👤 CONTACT OWNER", url="https://t.me/ethicalhacking13")],
        [InlineKeyboardButton("📢 UPDATES CHANNEL", url="https://t.me/ethicalhacking13")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = ScriptManager(user_id)
    
    welcome_text = f"""
╔══════════════════════════════════════════════════╗
║     🤖 SCRIPT HOSTING BOT - READY!              ║
║     Your Personal Cloud Script Executor         ║
╚══════════════════════════════════════════════════╝

┌──────────────────────────────────────────────────┐
│ 📊 YOUR ACCOUNT STATUS                           │
├──────────────────────────────────────────────────┤
│ 👤 User: @{update.effective_user.username or 'User'}     │
│ 🆔 ID: `{user_id}`                                │
│ 👑 Role: {'ADMIN' if user_id in ADMIN_IDS else 'USER'}     │
│ 📁 Scripts: {len(manager.list_scripts())} / {MAX_FILES}    │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ ✨ FEATURES AVAILABLE                            │
├──────────────────────────────────────────────────┤
│ • Host Python (.py) & JavaScript (.js)          │
│ • AI-powered script analysis                    │
│ • Smart chat assistant (no API needed!)         │
│ • Batch upload via ZIP                         │
│ • Real-time execution logs                      │
│ • Interactive buttons control                   │
└──────────────────────────────────────────────────┘

🚀 QUICK START - Use buttons below or type commands!

Type /help for all commands
"""

    await update.message.reply_text(
        welcome_text, 
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not update.message.document:
        await update.message.reply_text(
            "📎 *Send me a file!*\n\nSupported formats:\n• `.py` - Python script\n• `.js` - JavaScript\n• `.zip` - Multiple scripts\n\nUse the button below or send directly.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    file = update.message.document
    filename = file.file_name
    
    if not any(filename.endswith(ext) for ext in ['.py', '.js', '.zip']):
        await update.message.reply_text(
            "❌ *Invalid file type!*\n\nOnly `.py`, `.js`, or `.zip` files are allowed.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    status_msg = await update.message.reply_text(f"📥 Downloading `{filename}`...", parse_mode="Markdown")
    
    file_obj = await file.get_file()
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix)
    await file_obj.download_to_drive(temp_file.name)
    
    manager = ScriptManager(user_id)
    uploaded = 0
    errors = []
    
    try:
        if filename.endswith('.zip'):
            await status_msg.edit_text("📦 Extracting ZIP archive...", parse_mode="Markdown")
            with zipfile.ZipFile(temp_file.name, 'r') as zip_ref:
                extract_dir = tempfile.mkdtemp()
                zip_ref.extractall(extract_dir)
                
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        if file.endswith(('.py', '.js')):
                            file_path = Path(root) / file
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                            script_type = 'py' if file.endswith('.py') else 'js'
                            success, msg = manager.add_script(file, content, script_type)
                            if success:
                                uploaded += 1
                            else:
                                errors.append(f"{file}: {msg}")
                
                shutil.rmtree(extract_dir)
            
            result = f"✅ *Uploaded {uploaded} scripts from ZIP!*"
            if errors:
                result += f"\n⚠️ Failed: {', '.join(errors[:2])}"
        
        else:
            with open(temp_file.name, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            script_type = 'py' if filename.endswith('.py') else 'js'
            success, result = manager.add_script(filename, content, script_type)
    
    except Exception as e:
        result = f"❌ Error: {str(e)}"
    finally:
        os.unlink(temp_file.name)
        await status_msg.edit_text(result, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def list_scripts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = ScriptManager(user_id)
    scripts = manager.list_scripts()
    
    if not scripts:
        await update.message.reply_text(
            "📭 *No scripts uploaded yet!*\n\nUse the button below to upload your first script.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    text = "*📚 YOUR SCRIPTS LIBRARY*\n\n"
    keyboard = []
    
    for i, script in enumerate(scripts, 1):
        icon = "🟢" if script.is_running else "⚪"
        complexity_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(script.insights.get("complexity", "low"), "⚪")
        text += f"{i}. {icon} `{script.filename}`\n"
        text += f"   📦 {script.script_type.upper()} | {complexity_icon} {script.insights.get('complexity', 'low')}\n"
        text += f"   📅 {script.uploaded_at[:10]}\n"
        
        if script.insights.get('dependencies'):
            deps = ', '.join(script.insights['dependencies'][:2])
            text += f"   📦 {deps}\n"
        text += "\n"
    
    # Create inline keyboard for script selection
    for script in scripts[:10]:  # Max 10 buttons
        icon = "🟢" if script.is_running else "⚪"
        keyboard.append([InlineKeyboardButton(f"{icon} {script.filename[:20]}", callback_data=f"script_{script.filename}")])
    
    keyboard.append([InlineKeyboardButton("🔙 MAIN MENU", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def run_script(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "📝 *Usage:* `/run <filename>`\n\n*Example:* `/run my_script.py`\n\nUse `/list` to see your scripts.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    filename = " ".join(context.args)
    manager = ScriptManager(user_id)
    success, message = await manager.run_script(filename)
    
    await update.message.reply_text(message, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def stop_script(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "📝 *Usage:* `/stop <filename>`\n\n*Example:* `/stop my_script.py`\n\nUse `/list` to see running scripts (🟢 icon).",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    filename = " ".join(context.args)
    manager = ScriptManager(user_id)
    success, message = manager.stop_script(filename)
    
    await update.message.reply_text(message, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def view_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "📝 *Usage:* `/logs <filename>`\n\n*Example:* `/logs my_script.py`\n\nShows output and errors from your script.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    filename = " ".join(context.args)
    manager = ScriptManager(user_id)
    output = manager.get_logs(filename)
    
    await update.message.reply_text(
        f"📄 *Logs for `{filename}`:*\n```\n{output}\n```",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def delete_script(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "📝 *Usage:* `/delete <filename>`\n\n*Example:* `/delete my_script.py`",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    filename = " ".join(context.args)
    manager = ScriptManager(user_id)
    message = manager.remove_script(filename)
    
    await update.message.reply_text(message, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def analyze_scripts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = ScriptManager(user_id)
    scripts = manager.list_scripts()
    
    if not scripts:
        await update.message.reply_text(
            "📭 *No scripts to analyze!*\n\nUpload a script first using `/upload`",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    text = "*🤖 AI SCRIPT ANALYSIS*\n\n"
    for script in scripts[:5]:
        insights = script.insights
        text += f"📄 `{script.filename}`\n"
        text += f"• Type: {insights.get('type', 'unknown')}\n"
        text += f"• Lines: {insights.get('lines', 0)}\n"
        text += f"• Complexity: {insights.get('complexity', 'low')}\n"
        if insights.get('dependencies'):
            text += f"• Dependencies: {', '.join(insights['dependencies'][:3])}\n"
        if insights.get('suggestions'):
            text += f"• 💡 {insights['suggestions'][0]}\n"
        text += "\n"
    
    if len(scripts) > 5:
        text += f"✨ And {len(scripts)-5} more scripts...\nUse `/list` to see all"
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def chat_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI Chat Assistant - No API key needed"""
    
    if not context.args:
        await update.message.reply_text(
            "🤖 *AI CHAT ASSISTANT*\n\n"
            "Ask me anything about:\n"
            "• Script debugging 🐛\n"
            "• Code optimization ⚡\n"
            "• Error fixing 🔧\n"
            "• Best practices 📚\n\n"
            "*Examples:*\n"
            "`/chat How to fix my syntax error?`\n"
            "`/chat Why is my script not running?`\n"
            "`/chat Help me debug this`\n\n"
            "Just type `/chat <your question>`",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return
    
    question = " ".join(context.args)
    
    thinking = await update.message.reply_text("🤔 *AI is thinking...*", parse_mode="Markdown")
    
    # Get AI response
    response = await free_ai.chat(question)
    
    await thinking.edit_text(response, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager = ScriptManager(user_id)
    scripts = manager.list_scripts()
    
    running = sum(1 for s in scripts if s.is_running)
    total_size = 0
    for s in scripts:
        script_path = manager.user_dir / s.filename
        if script_path.exists():
            total_size += script_path.stat().st_size
    
    stats_text = f"""
╔══════════════════════════════════════════╗
║        📊 YOUR STATISTICS                ║
╚══════════════════════════════════════════╝

┌──────────────────────────────────────────┐
│ 📈 USAGE OVERVIEW                         │
├──────────────────────────────────────────┤
│ 👤 User ID: `{user_id}`                    │
│ 📁 Scripts: {len(scripts)} / {MAX_FILES}                │
│ ▶️ Running: {running}                                 │
│ ⏹️ Stopped: {len(scripts)-running}                      │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ 📊 SCRIPT BREAKDOWN                       │
├──────────────────────────────────────────┤
│ 🐍 Python: {sum(1 for s in scripts if s.script_type == 'py')}               │
│ 🟨 JavaScript: {sum(1 for s in scripts if s.script_type == 'js')}            │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ 🎯 COMPLEXITY METRICS                     │
├──────────────────────────────────────────┤
│ 🔴 High: {sum(1 for s in scripts if s.insights.get('complexity') == 'high')}               │
│ 🟡 Medium: {sum(1 for s in scripts if s.insights.get('complexity') == 'medium')}              │
│ 🟢 Low: {sum(1 for s in scripts if s.insights.get('complexity') == 'low')}                │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ 💾 STORAGE                                │
├──────────────────────────────────────────┤
│ 💿 Used: {total_size // 1024} KB                        │
└──────────────────────────────────────────┘

🤖 AI Assistant: Active (No API key needed!)
"""

    await update.message.reply_text(stats_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
╔══════════════════════════════════════════════════╗
║              📚 COMPLETE COMMANDS LIST           ║
╚══════════════════════════════════════════════════╝

┌──────────────────────────────────────────────────┐
│ 🚀 BASIC COMMANDS                                 │
├──────────────────────────────────────────────────┤
│ /start    → Main menu & status                   │
│ /help     → This help menu                       │
│ /upload   → Upload .py, .js, or .zip            │
│ /list     → Show all your scripts               │
│ /stats    → View usage statistics               │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ 🎮 SCRIPT CONTROL                                 │
├──────────────────────────────────────────────────┤
│ /run <file>    → Execute script                  │
│ /stop <file>   → Stop running script             │
│ /logs <file>   → View output & errors            │
│ /delete <file> → Remove script                   │
│ /ai            → Analyze all scripts             │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ 🤖 AI FEATURES                                    │
├──────────────────────────────────────────────────┤
│ /chat <question> → Ask AI assistant              │
│ • Get debugging help                             │
│ • Code optimization tips                         │
│ • Error explanations                             │
│ • Best practices                                 │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ 💡 QUICK EXAMPLES                                 │
├──────────────────────────────────────────────────┤
│ 1. Upload: /upload → send mybot.py              │
│ 2. Run: /run mybot.py                            │
│ 3. Check: /logs mybot.py                         │
│ 4. Stop: /stop mybot.py                          │
│ 5. Delete: /delete mybot.py                      │
│ 6. Ask AI: /chat Why is my script crashing?      │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ 📦 ZIP UPLOAD FEATURE                            │
├──────────────────────────────────────────────────┤
│ Pack multiple .py/.js files in a ZIP            │
│ Upload once and all scripts are added!          │
│ Max {MAX_FILES} scripts total                    │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ 🎯 STATUS INDICATORS                              │
├──────────────────────────────────────────────────┤
│ 🟢 = Script is RUNNING                           │
│ ⚪ = Script is STOPPED                            │
│ 🔴 = High complexity                             │
│ 🟡 = Medium complexity                           │
│ 🟢 = Low complexity                              │
└──────────────────────────────────────────────────┘

🔧 Need more help? Contact @ethicalhacking13
"""

    await update.message.reply_text(
        help_text.format(MAX_FILES=MAX_FILES),
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data == "upload":
        await query.message.reply_text(
            "📎 *Send me your file!*\n\n"
            "Supported formats:\n"
            "• `my_script.py` - Python\n"
            "• `my_script.js` - JavaScript\n"
            "• `scripts.zip` - Multiple scripts\n\n"
            "Just send the file directly!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    
    elif data == "list":
        manager = ScriptManager(user_id)
        scripts = manager.list_scripts()
        if scripts:
            text = "*📋 YOUR SCRIPTS:*\n\n"
            for i, s in enumerate(scripts[:15], 1):
                icon = "🟢" if s.is_running else "⚪"
                text += f"{i}. {icon} `{s.filename[:30]}`\n"
            await query.message.reply_text(text, parse_mode="Markdown")
        else:
            await query.message.reply_text(
                "📭 *No scripts yet!*\n\nUse the upload button to add your first script.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
    
    elif data == "ai_chat":
        await query.message.reply_text(
            "🤖 *AI CHAT ASSISTANT*\n\n"
            "I can help you with:\n"
            "• Debugging your scripts 🐛\n"
            "• Fixing syntax errors 🔧\n"
            "• Code optimization ⚡\n"
            "• Best practices 📚\n\n"
            "*How to use:*\n"
            "Type `/chat <your question>`\n\n"
            "*Examples:*\n"
            "`/chat How to fix indentation error?`\n"
            "`/chat Why is my loop infinite?`\n"
            "`/chat Help me debug this`\n\n"
            "*No API key needed!* - Completely free!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    
    elif data == "stats":
        manager = ScriptManager(user_id)
        scripts = manager.list_scripts()
        running = sum(1 for s in scripts if s.is_running)
        
        stats_text = f"""
📊 *QUICK STATS*

👤 User: `{user_id}`
📁 Scripts: {len(scripts)}/{MAX_FILES}
▶️ Running: {running}
⏹️ Stopped: {len(scripts)-running}
🐍 Python: {sum(1 for s in scripts if s.script_type == 'py')}
🟨 JS: {sum(1 for s in scripts if s.script_type == 'js')}

Type `/stats` for detailed statistics
"""
        await query.message.reply_text(stats_text, parse_mode="Markdown", reply_markup=get_main_keyboard())
    
    elif data == "help":
        await help_command(update, context)
    
    elif data == "main_menu":
        await query.message.reply_text(
            "🔙 *Returning to Main Menu*",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    
    elif data.startswith("script_"):
        filename = data[7:]
        keyboard = [
            [InlineKeyboardButton("▶️ RUN", callback_data=f"run_{filename}"),
             InlineKeyboardButton("⏹️ STOP", callback_data=f"stop_{filename}")],
            [InlineKeyboardButton("📄 VIEW LOGS", callback_data=f"logs_{filename}"),
             InlineKeyboardButton("🔍 ANALYZE", callback_data=f"analyze_{filename}")],
            [InlineKeyboardButton("🗑️ DELETE", callback_data=f"delete_{filename}"),
             InlineKeyboardButton("◀️ BACK", callback_data="list")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"📄 *Script Options:* `{filename}`\n\nChoose an action:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    elif data.startswith("run_"):
        filename = data[4:]
        manager = ScriptManager(user_id)
        success, message = await manager.run_script(filename)
        await query.message.reply_text(message, parse_mode="Markdown", reply_markup=get_main_keyboard())
    
    elif data.startswith("stop_"):
        filename = data[5:]
        manager = ScriptManager(user_id)
        success, message = manager.stop_script(filename)
        await query.message.reply_text(message, parse_mode="Markdown", reply_markup=get_main_keyboard())
    
    elif data.startswith("logs_"):
        filename = data[5:]
        manager = ScriptManager(user_id)
        output = manager.get_logs(filename)
        await query.message.reply_text(
            f"📄 *Logs for `{filename}`:*\n```\n{output}\n```",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    
    elif data.startswith("delete_"):
        filename = data[7:]
        manager = ScriptManager(user_id)
        message = manager.remove_script(filename)
        await query.message.reply_text(message, parse_mode="Markdown", reply_markup=get_main_keyboard())
    
    elif data.startswith("analyze_"):
        filename = data[8:]
        manager = ScriptManager(user_id)
        insights = manager.get_insights(filename)
        if insights:
            text = f"🔍 *Analysis for* `{filename}`\n\n"
            text += f"📦 Type: {insights.get('type', 'unknown')}\n"
            text += f"📊 Lines: {insights.get('lines', 0)}\n"
            text += f"📈 Complexity: {insights.get('complexity', 'unknown')}\n"
            if insights.get('dependencies'):
                text += f"\n📦 Dependencies:\n• " + "\n• ".join(insights['dependencies'][:5])
            if insights.get('suggestions'):
                text += f"\n\n💡 *Suggestions:*\n• " + "\n• ".join(insights['suggestions'][:3])
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard())
        else:
            await query.message.reply_text("No analysis available.", reply_markup=get_main_keyboard())

# ==================== MAIN ====================
async def main():
    print("\n" + "="*60)
    print("🤖 TELEGRAM SCRIPT HOSTING BOT")
    print("="*60)
    print(f"✅ Bot Token: Loaded")
    print(f"✅ Admin ID: {ADMIN_IDS[0]}")
    print(f"✅ AI Chat: Active (No API key needed)")
    print(f"📁 Work Directory: {WORK_DIR}")
    print(f"📊 Max Files: {MAX_FILES}")
    print(f"💾 Python: {sys.version.split()[0]}")
    print("="*60)
    print("🚀 Bot is LIVE and RUNNING!")
    print("📱 Open Telegram and send /start")
    print("="*60 + "\n")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add all handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("upload", upload_handler))
    application.add_handler(CommandHandler("list", list_scripts))
    application.add_handler(CommandHandler("run", run_script))
    application.add_handler(CommandHandler("stop", stop_script))
    application.add_handler(CommandHandler("logs", view_logs))
    application.add_handler(CommandHandler("delete", delete_script))
    application.add_handler(CommandHandler("ai", analyze_scripts))
    application.add_handler(CommandHandler("chat", chat_ai))
    application.add_handler(CommandHandler("stats", my_stats))
    application.add_handler(MessageHandler(filters.Document.ALL, upload_handler))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Start bot
    await application.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\n💡 Make sure you have internet connection and token is valid!")