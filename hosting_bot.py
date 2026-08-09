#!/usr/bin/env python3
"""
TyraDev Hosting Bot — sends OTP codes + basic help
Token is read from data/config.json (hosting_bot_token)
"""

import json
import sys
from pathlib import Path

import telebot

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "data" / "config.json"

def load_token():
    if not CONFIG.exists():
        print("data/config.json missing. Start the web app once first.")
        sys.exit(1)
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    token = cfg.get("hosting_bot_token", "")
    if not token or token == "YOUR_HOSTING_BOT_TOKEN":
        print("Set hosting_bot_token in data/config.json")
        sys.exit(1)
    return token

bot = telebot.TeleBot(load_token())

@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.reply_to(
        message,
        "<b>Ziaa Hosting Bot</b>\n\n"
        "This bot delivers your login OTP codes.\n"
        "1. Open the website\n"
        "2. Enter your Telegram ID\n"
        "3. Press <b>Send Login OTP</b>\n"
        "4. Come back here — the code arrives automatically\n\n"
        f"Your Telegram ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML",
    )

@bot.message_handler(commands=["id"])
def my_id(message):
    bot.reply_to(message, f"Your Telegram ID:\n<code>{message.from_user.id}</code>", parse_mode="HTML")

if __name__ == "__main__":
    print("ZiaaDev Hosting Bot running…")
    bot.infinity_polling()
