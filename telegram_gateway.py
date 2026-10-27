"""
telegram_gateway.py - Mobile Remote Command Bridge for BERU AI AGENT.
Allows controlling the desktop from Telegram anywhere in the world.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from agent import run_agent
from config import GROQ_API_KEY, TELEGRAM_TOKEN, TELEGRAM_USER_ID
from proactive_daemon import generate_system_health_briefing
from tools_registry import take_desktop_screenshot


def _is_authorized(update: Update) -> bool:
    # Fail closed: if no admin ID is configured, NO ONE is authorized.
    if not TELEGRAM_USER_ID:
        return False
    user_id = str(update.effective_user.id)
    return user_id == str(TELEGRAM_USER_ID)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await update.message.reply_text("⛔ Access Denied.")
        return
    welcome = (
        "🤖 **BERU AI AGENT Command Center**\n\n"
        "Available Directives:\n"
        "• Just send any prompt to run in **General Mode**\n"
        "• `/dev <task>` — Developer Mode (Code, Test, Git)\n"
        "• `/hack <target>` — Hacker Mode (Recon & Vulnerability Scan)\n"
        "• `/test <path>` — Tester Mode (QA & Security Audit)\n"
        "• `/health` — System Telemetry Briefing\n"
        "• `/screenshot` — Capture Desktop Screen\n"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    briefing = generate_system_health_briefing()
    await update.message.reply_text(briefing, parse_mode="Markdown")


async def screenshot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text("📸 Capturing desktop...")
    from config import WORKSPACE_DIR
    shot_path = WORKSPACE_DIR / "telegram_shot.png"
    take_desktop_screenshot(str(shot_path))
    if shot_path.exists():
        with open(shot_path, "rb") as f:
            await update.message.reply_photo(photo=f, caption="🖥️ Current Desktop Screen")
    else:
        await update.message.reply_text("Failed to capture screenshot.")


async def dev_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    task = " ".join(context.args)
    if not task:
        await update.message.reply_text("Provide a task: `/dev build a rest api`", parse_mode="Markdown")
        return
    await update.message.reply_text(f"⚙️ Running Developer Mode: `{task}`...", parse_mode="Markdown")
    resp = run_agent(task, mode="Developer")
    await update.message.reply_text(resp[:4000])


async def hack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    target = " ".join(context.args)
    if not target:
        await update.message.reply_text("Provide a target: `/hack example.com`", parse_mode="Markdown")
        return
    await update.message.reply_text(f"🕵️ Running Hacker Mode on `{target}`...", parse_mode="Markdown")
    resp = run_agent(f"Perform complete security audit on {target}", mode="Hacker")
    await update.message.reply_text(resp[:4000])


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    text = update.message.text
    await update.message.reply_text("🧠 Thinking...")
    reply = run_agent(text, mode="General")
    await update.message.reply_text(reply[:4000])


def start_telegram_bot():
    if not TELEGRAM_TOKEN:
        print("⚠️ No TELEGRAM_TOKEN found in config. Bot disabled.")
        return
    print("🤖 Starting BERU AI AGENT Telegram Bot...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("screenshot", screenshot_cmd))
    app.add_handler(CommandHandler("dev", dev_cmd))
    app.add_handler(CommandHandler("hack", hack_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()


if __name__ == "__main__":
    start_telegram_bot()
