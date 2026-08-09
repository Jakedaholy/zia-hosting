#!/usr/bin/env python3
"""Ziaa Hosting Bot — OTP delivery + identity"""
import json, sys
from pathlib import Path
import telebot

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "data" / "config.json"

def load_token():
    if not CONFIG.exists():
        print("Missing data/config.json")
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
        "<b>Ziaa Hosting</b>\n\n"
        "I deliver login codes for the panel.\n"
        "1. Open the website\n"
        "2. Enter your Telegram ID\n"
        "3. Come here for the OTP\n\n"
        "Here Is The Website https://zia-hosting.onrender.com/dashboard\n\n"
        f"Your ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML",
    )

@bot.message_handler(commands=["id"])
def myid(message):
    bot.reply_to(message, f"<code>{message.from_user.id}</code>", parse_mode="HTML")

if __name__ == "__main__":
    print("Ziaa hosting bot running...")
    bot.infinity_polling()
