#!/usr/bin/env python3
"""
ZiaDev — Telegram Bot Hosting Platform
Dashboard + OTP login + bot deploy + process manager
"""

import os
import sys
import json
import time
import uuid
import shutil
import signal
import secrets
import hashlib
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, send_from_directory, abort
)
from werkzeug.utils import secure_filename

# ─── PATHS ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BOTS_DIR = BASE_DIR / "bots"
UPLOAD_DIR = BASE_DIR / "uploads"
for d in (DATA_DIR, BOTS_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
BOTS_FILE = DATA_DIR / "bots.json"
OTP_FILE = DATA_DIR / "otps.json"
CONFIG_FILE = DATA_DIR / "config.json"

# ─── DEFAULT CONFIG ──────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "admin_telegram_ids": [8632939616],          # your telegram id
    "hosting_bot_token": "YOUR_HOSTING_BOT_TOKEN",  # @ZiaaahHosting_Bot token
    "secret_key": secrets.token_hex(32),
    "max_bots_free": 3,
    "max_bots_premium": 15,
    "site_name": "Ziaaahosting",
    "site_tagline": "Host your Python bots in one click.",
}

def load_json(path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default.copy() if isinstance(default, dict) else default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

def get_config():
    cfg = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
    if not CONFIG_FILE.exists():
        save_json(CONFIG_FILE, cfg)
    return cfg

def get_users():
    return load_json(USERS_FILE, {})

def save_users(users):
    save_json(USERS_FILE, users)

def get_bots_db():
    return load_json(BOTS_FILE, {})

def save_bots_db(bots):
    save_json(BOTS_FILE, bots)

def get_otps():
    return load_json(OTP_FILE, {})

def save_otps(otps):
    save_json(OTP_FILE, otps)

# ─── FLASK APP ───────────────────────────────────────────────────────────────
app = Flask(__name__)
cfg = get_config()
app.secret_key = cfg["secret_key"]
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# ─── PROCESS MANAGER ─────────────────────────────────────────────────────────
running_procs = {}  # bot_id -> subprocess.Popen
proc_lock = threading.Lock()

def bot_workdir(user_id, bot_id):
    return BOTS_DIR / str(user_id) / bot_id

def start_bot_process(user_id, bot_id, token, entry_file="main.py"):
    work = bot_workdir(user_id, bot_id)
    entry = work / entry_file
    if not entry.exists():
        return False, "Entry file not found"

    log_path = work / "bot.log"
    env = os.environ.copy()
    env["BOT_TOKEN"] = token
    env["PYTHONUNBUFFERED"] = "1"

    with proc_lock:
        # stop old if any
        if bot_id in running_procs:
            try:
                running_procs[bot_id].terminate()
                running_procs[bot_id].wait(timeout=3)
            except Exception:
                try:
                    running_procs[bot_id].kill()
                except Exception:
                    pass
            running_procs.pop(bot_id, None)

        try:
            log_f = open(log_path, "a", encoding="utf-8")
            p = subprocess.Popen(
                [sys.executable, str(entry)],
                cwd=str(work),
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            running_procs[bot_id] = p
            return True, "started"
        except Exception as e:
            return False, str(e)

def stop_bot_process(bot_id):
    with proc_lock:
        p = running_procs.get(bot_id)
        if not p:
            return True
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        running_procs.pop(bot_id, None)
    return True

def is_bot_running(bot_id):
    with proc_lock:
        p = running_procs.get(bot_id)
        if not p:
            return False
        if p.poll() is not None:
            running_procs.pop(bot_id, None)
            return False
        return True

# ─── OTP + TELEGRAM ──────────────────────────────────────────────────────────
def send_telegram_otp(telegram_id, code):
    cfg = get_config()
    token = cfg.get("hosting_bot_token", "")
    if not token or token == "YOUR_HOSTING_BOT_TOKEN":
        # fallback: print to console for local testing
        print(f"[OTP] telegram_id={telegram_id} code={code}")
        return True
    try:
        import telebot
        bot = telebot.TeleBot(token)
        bot.send_message(
            telegram_id,
            f"<b>Ziahosting Login Code</b>\n\n"
            f"Your verification code is:\n"
            f"<code>{code}</code>\n\n"
            f"Valid for 5 minutes. Do not share it.",
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        print(f"[OTP ERROR] {e}")
        return False

def create_otp(telegram_id):
    code = f"{secrets.randbelow(1000000):06d}"
    otps = get_otps()
    otps[str(telegram_id)] = {
        "code": code,
        "expires": (datetime.utcnow() + timedelta(minutes=5)).isoformat(),
        "attempts": 0,
    }
    save_otps(otps)
    return code

def verify_otp(telegram_id, code):
    otps = get_otps()
    key = str(telegram_id)
    entry = otps.get(key)
    if not entry:
        return False, "No OTP requested"
    if entry.get("attempts", 0) >= 5:
        otps.pop(key, None)
        save_otps(otps)
        return False, "Too many attempts"
    expires = datetime.fromisoformat(entry["expires"])
    if datetime.utcnow() > expires:
        otps.pop(key, None)
        save_otps(otps)
        return False, "OTP expired"
    entry["attempts"] = entry.get("attempts", 0) + 1
    if entry["code"] != code.strip():
        save_otps(otps)
        return False, "Wrong code"
    otps.pop(key, None)
    save_otps(otps)
    return True, "ok"

# ─── AUTH HELPERS ────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        cfg = get_config()
        if int(session["user_id"]) not in [int(x) for x in cfg.get("admin_telegram_ids", [])]:
            abort(403)
        return f(*args, **kwargs)
    return decorated

def current_user():
    users = get_users()
    uid = str(session.get("user_id", ""))
    return users.get(uid)

def ensure_user(telegram_id):
    users = get_users()
    key = str(telegram_id)
    if key not in users:
        users[key] = {
            "telegram_id": int(telegram_id),
            "plan": "standard",
            "created_at": datetime.utcnow().isoformat(),
            "bots": [],
        }
        save_users(users)
    return users[key]

# ─── ROUTES: PUBLIC ──────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", site=get_config())

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", site=get_config())

    action = request.form.get("action")
    telegram_id = request.form.get("telegram_id", "").strip()

    if not telegram_id.isdigit():
        flash("Enter a valid Telegram ID (numbers only).", "error")
        return render_template("login.html", site=get_config())

    if action == "send_otp":
        code = create_otp(telegram_id)
        ok = send_telegram_otp(int(telegram_id), code)
        if ok:
            flash("OTP sent. Open the hosting bot and check your messages.", "success")
        else:
            flash("Could not send OTP. Check hosting bot token in config.", "error")
        return render_template("login.html", site=get_config(), telegram_id=telegram_id, step="otp")

    if action == "verify_otp":
        code = request.form.get("code", "").strip()
        ok, msg = verify_otp(telegram_id, code)
        if not ok:
            flash(msg, "error")
            return render_template("login.html", site=get_config(), telegram_id=telegram_id, step="otp")
        ensure_user(telegram_id)
        session["user_id"] = int(telegram_id)
        session.permanent = True
        return redirect(url_for("dashboard"))

    flash("Invalid action.", "error")
    return render_template("login.html", site=get_config())

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ─── ROUTES: DASHBOARD ───────────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    bots_db = get_bots_db()
    user_bots = []
    for bid in user.get("bots", []):
        b = bots_db.get(bid)
        if b:
            b = dict(b)
            b["running"] = is_bot_running(bid)
            user_bots.append(b)

    cfg = get_config()
    limit = cfg["max_bots_premium"] if user.get("plan") == "premium" else cfg["max_bots_free"]
    active = sum(1 for b in user_bots if b.get("running"))
    stopped = len(user_bots) - active

    return render_template(
        "dashboard.html",
        site=cfg,
        user=user,
        bots=user_bots,
        limit=limit,
        active=active,
        stopped=stopped,
    )

@app.route("/bots/new", methods=["GET", "POST"])
@login_required
def new_bot():
    user = current_user()
    cfg = get_config()
    limit = cfg["max_bots_premium"] if user.get("plan") == "premium" else cfg["max_bots_free"]
    if len(user.get("bots", [])) >= limit:
        flash(f"Bot limit reached ({limit}). Upgrade for more slots.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "GET":
        return render_template("new_bot.html", site=cfg)

    name = request.form.get("name", "").strip() or "My Bot"
    token = request.form.get("token", "").strip()
    library = request.form.get("library", "pyTelegramBotAPI")
    upload = request.files.get("bot_file")

    if not token:
        flash("Bot token is required.", "error")
        return render_template("new_bot.html", site=cfg)

    bot_id = uuid.uuid4().hex[:12]
    uid = str(session["user_id"])
    work = bot_workdir(uid, bot_id)
    work.mkdir(parents=True, exist_ok=True)

    entry_file = "main.py"
    if upload and upload.filename:
        filename = secure_filename(upload.filename)
        if filename.endswith(".zip"):
            zip_path = work / filename
            upload.save(zip_path)
            shutil.unpack_archive(str(zip_path), str(work))
            zip_path.unlink(missing_ok=True)
            # find a main entry
            for candidate in ("main.py", "bot.py", "app.py", "run.py"):
                if (work / candidate).exists():
                    entry_file = candidate
                    break
            else:
                pys = list(work.glob("*.py"))
                if pys:
                    entry_file = pys[0].name
        elif filename.endswith(".py"):
            upload.save(work / "main.py")
            entry_file = "main.py"
        else:
            flash("Upload a .py or .zip file.", "error")
            shutil.rmtree(work, ignore_errors=True)
            return render_template("new_bot.html", site=cfg)
    else:
        # generate starter based on library
        starter = STARTER_TEMPLATES.get(library, STARTER_TEMPLATES["pyTelegramBotAPI"])
        (work / "main.py").write_text(starter.replace("{{TOKEN}}", token), encoding="utf-8")

    # requirements if missing
    req = work / "requirements.txt"
    if not req.exists():
        req.write_text("pyTelegramBotAPI==4.22.1\nrequests==2.32.3\n", encoding="utf-8")

    bots_db = get_bots_db()
    bots_db[bot_id] = {
        "id": bot_id,
        "name": name,
        "token": token,
        "library": library,
        "entry": entry_file,
        "owner": int(uid),
        "created_at": datetime.utcnow().isoformat(),
        "status": "stopped",
    }
    save_bots_db(bots_db)

    users = get_users()
    users[uid].setdefault("bots", []).append(bot_id)
    save_users(users)

    flash(f"Bot '{name}' created. Start it from the dashboard.", "success")
    return redirect(url_for("dashboard"))

@app.route("/bots/<bot_id>/start", methods=["POST"])
@login_required
def bot_start(bot_id):
    user = current_user()
    if bot_id not in user.get("bots", []):
        abort(403)
    bots_db = get_bots_db()
    b = bots_db.get(bot_id)
    if not b:
        abort(404)
    ok, msg = start_bot_process(str(session["user_id"]), bot_id, b["token"], b.get("entry", "main.py"))
    if ok:
        b["status"] = "running"
        save_bots_db(bots_db)
        flash("Bot started.", "success")
    else:
        flash(f"Start failed: {msg}", "error")
    return redirect(url_for("dashboard"))

@app.route("/bots/<bot_id>/stop", methods=["POST"])
@login_required
def bot_stop(bot_id):
    user = current_user()
    if bot_id not in user.get("bots", []):
        abort(403)
    stop_bot_process(bot_id)
    bots_db = get_bots_db()
    if bot_id in bots_db:
        bots_db[bot_id]["status"] = "stopped"
        save_bots_db(bots_db)
    flash("Bot stopped.", "success")
    return redirect(url_for("dashboard"))

@app.route("/bots/<bot_id>/delete", methods=["POST"])
@login_required
def bot_delete(bot_id):
    user = current_user()
    uid = str(session["user_id"])
    if bot_id not in user.get("bots", []):
        abort(403)
    stop_bot_process(bot_id)
    bots_db = get_bots_db()
    bots_db.pop(bot_id, None)
    save_bots_db(bots_db)
    users = get_users()
    users[uid]["bots"] = [x for x in users[uid].get("bots", []) if x != bot_id]
    save_users(users)
    shutil.rmtree(bot_workdir(uid, bot_id), ignore_errors=True)
    flash("Bot deleted.", "success")
    return redirect(url_for("dashboard"))

@app.route("/bots/<bot_id>/logs")
@login_required
def bot_logs(bot_id):
    user = current_user()
    if bot_id not in user.get("bots", []):
        abort(403)
    log_path = bot_workdir(str(session["user_id"]), bot_id) / "bot.log"
    content = ""
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8", errors="ignore")[-8000:]
    return render_template("logs.html", site=get_config(), bot_id=bot_id, logs=content)

@app.route("/files")
@login_required
def files():
    uid = str(session["user_id"])
    root = BOTS_DIR / uid
    root.mkdir(parents=True, exist_ok=True)
    items = []
    total = 0
    for p in root.rglob("*"):
        if p.is_file():
            size = p.stat().st_size
            total += size
            items.append({"path": str(p.relative_to(root)), "size": size})
    return render_template(
        "files.html",
        site=get_config(),
        items=items,
        total=total,
        limit=2.5 * 1024 * 1024 * 1024,
    )

# ─── ADMIN PANEL ─────────────────────────────────────────────────────────────
@app.route("/admin")
@admin_required
def admin_panel():
    users = get_users()
    bots_db = get_bots_db()
    cfg = get_config()
    running = sum(1 for bid in bots_db if is_bot_running(bid))
    return render_template(
        "admin.html",
        site=cfg,
        users=users,
        bots=bots_db,
        running=running,
        total_bots=len(bots_db),
        total_users=len(users),
    )

@app.route("/admin/config", methods=["POST"])
@admin_required
def admin_config():
    cfg = get_config()
    token = request.form.get("hosting_bot_token", "").strip()
    admins = request.form.get("admin_ids", "").strip()
    if token:
        cfg["hosting_bot_token"] = token
    if admins:
        ids = []
        for part in admins.replace(",", " ").split():
            if part.strip().isdigit():
                ids.append(int(part.strip()))
        if ids:
            cfg["admin_telegram_ids"] = ids
    save_json(CONFIG_FILE, cfg)
    flash("Config saved.", "success")
    return redirect(url_for("admin_panel"))

@app.route("/admin/user/<uid>/plan", methods=["POST"])
@admin_required
def admin_set_plan(uid):
    plan = request.form.get("plan", "standard")
    users = get_users()
    if uid in users:
        users[uid]["plan"] = plan if plan in ("standard", "premium") else "standard"
        save_users(users)
        flash(f"User {uid} plan set to {users[uid]['plan']}.", "success")
    return redirect(url_for("admin_panel"))

@app.route("/admin/bot/<bot_id>/stop", methods=["POST"])
@admin_required
def admin_stop_bot(bot_id):
    stop_bot_process(bot_id)
    bots_db = get_bots_db()
    if bot_id in bots_db:
        bots_db[bot_id]["status"] = "stopped"
        save_bots_db(bots_db)
    flash("Bot force-stopped.", "success")
    return redirect(url_for("admin_panel"))

# ─── STARTER TEMPLATES ───────────────────────────────────────────────────────
STARTER_TEMPLATES = {
    "pyTelegramBotAPI": '''#!/usr/bin/env python3
import os
import telebot

TOKEN = os.environ.get("BOT_TOKEN", "{{TOKEN}}")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Hello from Zia hosting!")

@bot.message_handler(commands=["ping"])
def ping(message):
    bot.reply_to(message, "Pong!")

@bot.message_handler(func=lambda m: True)
def echo(message):
    bot.reply_to(message, f"You said: {message.text}")

if __name__ == "__main__":
    print("Bot starting...")
    bot.infinity_polling()
''',
    "python-telegram-bot": '''#!/usr/bin/env python3
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN", "{{TOKEN}}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello from Zia hosting!")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong!")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"You said: {update.message.text}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    print("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
''',
}

# ─── RUN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "5000"))
    print(f"ZiaDev Hosting starting on http://0.0.0.0:{port}")
    print("Edit data/config.json for bot token + admin ids")
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
