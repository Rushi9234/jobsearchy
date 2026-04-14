"""
telegram_notifier.py — Searchy Telegram Notifier
"""

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from telegram import Bot
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed.")


def _get_config():
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        env_path = os.path.join(os.path.dirname(__file__), "..", "searchy.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                    elif line.startswith("TELEGRAM_CHAT_ID="):
                        chat_id = line.split("=", 1)[1].strip()
    return token, chat_id


def _score_bar(score: float) -> str:
    filled = round(score / 10)
    return "🟩" * filled + "⬜" * (10 - filled)


def _format_job_message(job: dict) -> str:
    score    = job.get("match_score", 0)
    stipend  = job.get("stipend") or "Not specified"
    duration = job.get("duration") or "Not specified"
    location = job.get("location") or "Not specified"
    tags     = job.get("tags") or []
    tags_str = "  ".join(f"#{t.replace(' ', '_')}" for t in tags[:6]) if tags else ""

    return "\n".join([
        "New Match Found!",
        "",
        str(job.get("title", "Unknown")),
        "Company: " + str(job.get("company", "Unknown")),
        "Location: " + str(location),
        "Duration: " + str(duration),
        "Stipend: " + str(stipend),
        "",
        "Match Score: " + str(round(score)) + "/100  " + _score_bar(score),
        "",
        tags_str,
        "",
        "Link: " + str(job.get("url", "")),
    ])


def _format_digest_message(jobs: list) -> str:
    if not jobs:
        return "Daily Digest — No new matches today. Keep going!"
    lines = ["Daily Job Digest — Top Matches", ""]
    for i, job in enumerate(jobs[:10], 1):
        score = job.get("match_score", 0)
        lines.append(f"{i}. {job.get('title', '?')} — {round(score)}/100")
        lines.append(f"   {job.get('company', '?')}  |  {job.get('location', '?')}")
        lines.append(f"   {job.get('url', '')}")
        lines.append("")
    lines.append(f"Total new listings: {len(jobs)}")
    return "\n".join(lines)


async def _send_async(token: str, chat_id: str, text: str) -> bool:
    try:
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except TelegramError as e:
        logger.error("[Telegram] Send error: %s", e)
        return False


async def _send_many_async(token: str, chat_id: str, messages: list) -> int:
    sent = 0
    for msg in messages:
        ok = await _send_async(token, chat_id, msg)
        if ok:
            sent += 1
        await asyncio.sleep(1.0)
    return sent


def send_job_alert(job: dict) -> bool:
    if not TELEGRAM_AVAILABLE:
        return False
    token, chat_id = _get_config()
    if not token or not chat_id:
        logger.error("[Telegram] BOT_TOKEN or CHAT_ID not configured.")
        return False
    return asyncio.run(_send_async(token, chat_id, _format_job_message(job)))


def send_job_alerts(jobs: list) -> int:
    if not TELEGRAM_AVAILABLE:
        return 0
    token, chat_id = _get_config()
    if not token or not chat_id:
        return 0
    messages = [_format_job_message(j) for j in jobs]
    return asyncio.run(_send_many_async(token, chat_id, messages))


def send_daily_digest(jobs: list) -> bool:
    if not TELEGRAM_AVAILABLE:
        return False
    token, chat_id = _get_config()
    if not token or not chat_id:
        return False
    return asyncio.run(_send_async(token, chat_id, _format_digest_message(jobs)))


def send_text(text: str) -> bool:
    if not TELEGRAM_AVAILABLE:
        return False
    token, chat_id = _get_config()
    if not token or not chat_id:
        return False
    return asyncio.run(_send_async(token, chat_id, text))


if __name__ == "__main__":
    token, chat_id = _get_config()
    print(f"Token: {'YES' if token else 'NO'}")
    print(f"Chat ID: {chat_id if chat_id else 'NO'}")

    test_job = {
        "title":       "Python ML Intern",
        "company":     "Tech Corp",
        "location":    "Remote",
        "duration":    "3 months",
        "stipend":     "Rs.10,000/month",
        "url":         "https://internshala.com/example",
        "tags":        ["python", "machine learning"],
        "match_score": 82.5,
    }
    print("\nSending test alert...")
    ok = send_job_alert(test_job)
    print("Sent! Check your Telegram." if ok else "Failed.")