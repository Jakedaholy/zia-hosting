#!/usr/bin/env python3
"""Ziaa — Telegram Bot Hosting Platform"""

import os
import sys
import json
import time
import uuid
import shutil
import secrets
import zipfile
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, abort, send_file
)
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BOTS_DIR = BASE_DIR / "bots"
for d in (DATA_DIR, BOTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
BOTS_FILE = DATA_DIR / "bots.json"
OTP_FILE = DATA_DIR / "otps.json"
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "admin_usernames": ["maisanyvokei"],
    "admin_telegram_ids": [],
    "hosting_bot_token": "YOUR_HOSTING_BOT_TOKEN",
    "secret_key": secrets.token_hex(24),
    "site_name": "Ziaa",
    "site_tagline": "Deploy Telegram bots. Stay online.",
    "plans": {
        "free":    {"bots": 1,  "days": 2,  "price": 0},
        "basic":   {"bots": 3,  "days": 5,  "price": 50},
        "elite":   {"bots": 10, "days": 7,  "price": 90},
        "premium": {"bots": 30, "days": 21, "price": 120},
    },
}

def load_json(path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default.copy() if isinstance(default, dict) else list(default) if isinstance(default, list) else default

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

def save_users(u):
    save_json(USERS_FILE, u)

def get_bots_db():
    return load_json(BOTS_FILE, {})

def save_bots_db(b):
    save_json(BOTS_FILE, b)

def get_otps():
    return load_json(OTP_FILE, {})

def save_otps(o):
    save_json(OTP_FILE, o)

app = Flask(__name__)
cfg0 = get_config()
app.secret_key = cfg0["secret_key"]
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
app.permanent_session_lifetime = timedelta(days=30)

# ── process manager ──────────────────────────────────────────────────────────
running_procs = {}
proc_lock = threading.Lock()

def bot_workdir(user_id, bot_id):
    return BOTS_DIR / str(user_id) / bot_id

def start_bot_process(user_id, bot_id, token, entry_file="main.py"):
    work = bot_workdir(user_id, bot_id)
    entry = work / entry_file
    if not entry.exists():
        # try common names
        for c in ("main.py", "bot.py", "app.py", "run.py"):
            if (work / c).exists():
                entry = work / c
                entry_file = c
                break
        else:
            return False, "Entry file not found"
    log_path = work / "bot.log"
    env = os.environ.copy()
    env["BOT_TOKEN"] = token
    env["PYTHONUNBUFFERED"] = "1"
    with proc_lock:
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
                cwd=str(work), env=env,
                stdout=log_f, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            running_procs[bot_id] = p
            return True, entry_file
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

# ── telegram helpers ─────────────────────────────────────────────────────────
def tg_send(chat_id, text):
    cfg = get_config()
    token = cfg.get("hosting_bot_token", "")
    if not token or token == "YOUR_HOSTING_BOT_TOKEN":
        print(f"[TG] {chat_id}: {text}")
        return False
    try:
        import telebot
        bot = telebot.TeleBot(token)
        bot.send_message(chat_id, text, parse_mode="HTML")
        return True
    except Exception as e:
        print(f"[TG ERR] {e}")
        return False

def send_otp(telegram_id, code):
    return tg_send(
        telegram_id,
        f"<b>Ziaa Login Code</b>\n\n<code>{code}</code>\n\nValid 5 minutes. Do not share.",
    )

def notify_plan(telegram_id, plan, days, price):
    return tg_send(
        telegram_id,
        f"<b>Ziaa Plan Update</b>\n\n"
        f"Plan: <b>{plan.upper()}</b>\n"
        f"Duration: <b>{days} days</b>\n"
        f"Price: <b>${price}</b>\n\n"
        f"Your workspace limits were refreshed. Open the dashboard to deploy.",
    )

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
    if datetime.utcnow() > datetime.fromisoformat(entry["expires"]):
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

# ── user / plan ──────────────────────────────────────────────────────────────
def plan_info(name):
    plans = get_config().get("plans", DEFAULT_CONFIG["plans"])
    return plans.get(name, plans["free"])

def ensure_user(telegram_id, username=""):
    users = get_users()
    key = str(telegram_id)
    now = datetime.utcnow()
    if key not in users:
        p = plan_info("free")
        users[key] = {
            "telegram_id": int(telegram_id),
            "username": (username or "").lstrip("@").lower(),
            "plan": "free",
            "plan_expires": (now + timedelta(days=p["days"])).isoformat(),
            "created_at": now.isoformat(),
            "bots": [],
        }
        save_users(users)
    else:
        if username and not users[key].get("username"):
            users[key]["username"] = username.lstrip("@").lower()
            save_users(users)
    return users[key]

def user_plan_active(user):
    exp = user.get("plan_expires")
    if not exp:
        return False
    try:
        return datetime.utcnow() <= datetime.fromisoformat(exp)
    except Exception:
        return False

def user_bot_limit(user):
    if not user_plan_active(user):
        return 0
    return plan_info(user.get("plan", "free"))["bots"]

def days_left(user):
    exp = user.get("plan_expires")
    if not exp:
        return 0
    try:
        delta = datetime.fromisoformat(exp) - datetime.utcnow()
        return max(0, delta.days)
    except Exception:
        return 0

def set_plan(user_key, plan, notify=True):
    users = get_users()
    if user_key not in users:
        return False
    p = plan_info(plan)
    users[user_key]["plan"] = plan
    users[user_key]["plan_expires"] = (datetime.utcnow() + timedelta(days=p["days"])).isoformat()
    save_users(users)
    if notify:
        notify_plan(users[user_key]["telegram_id"], plan, p["days"], p["price"])
    return True

def is_admin(user):
    cfg = get_config()
    uname = (user.get("username") or "").lower()
    tid = int(user.get("telegram_id", 0))
    if uname and uname in [x.lower() for x in cfg.get("admin_usernames", [])]:
        return True
    if tid and tid in [int(x) for x in cfg.get("admin_telegram_ids", [])]:
        return True
    return False

# ── auth ─────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrap(*a, **k):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*a, **k)
    return wrap

def admin_required(f):
    @wraps(f)
    def wrap(*a, **k):
        if "user_id" not in session:
            return redirect(url_for("login"))
        user = current_user()
        if not user or not is_admin(user):
            abort(403)
        return f(*a, **k)
    return wrap

def current_user():
    users = get_users()
    return users.get(str(session.get("user_id", "")))

# ── starters ─────────────────────────────────────────────────────────────────
STARTERS = {
    "pyTelegramBotAPI": '''#!/usr/bin/env python3
import os, telebot
TOKEN = os.environ.get("BOT_TOKEN", "")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(m):
    bot.reply_to(m, "Online via Ziaa hosting.")

@bot.message_handler(commands=["ping"])
def ping(m):
    bot.reply_to(m, "Pong")

@bot.message_handler(func=lambda m: True)
def echo(m):
    bot.reply_to(m, m.text or "")

if __name__ == "__main__":
    print("Ziaa bot starting...")
    bot.infinity_polling()
''',
}

# ── routes: public ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", site=get_config(), plans=get_config()["plans"])

@app.route("/pricing")
def pricing():
    return render_template("pricing.html", site=get_config(), plans=get_config()["plans"])

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    site = get_config()
    if request.method == "GET":
        return render_template("login.html", site=site)

    action = request.form.get("action")
    telegram_id = request.form.get("telegram_id", "").strip()
    if not telegram_id.isdigit():
        flash("Telegram ID must be numbers only.", "error")
        return render_template("login.html", site=site)

    if action == "send_otp":
        code = create_otp(telegram_id)
        ok = send_otp(int(telegram_id), code)
        flash("OTP sent to your Telegram." if ok else "OTP created (check hosting bot token / console).", "success" if ok else "error")
        return render_template("login.html", site=site, telegram_id=telegram_id, step="otp")

    if action == "verify_otp":
        code = request.form.get("code", "").strip()
        ok, msg = verify_otp(telegram_id, code)
        if not ok:
            flash(msg, "error")
            return render_template("login.html", site=site, telegram_id=telegram_id, step="otp")
        username = request.form.get("username", "").strip()
        ensure_user(telegram_id, username)
        session.permanent = True
        session["user_id"] = int(telegram_id)
        return redirect(url_for("dashboard"))

    flash("Invalid action.", "error")
    return render_template("login.html", site=site)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ── dashboard ────────────────────────────────────────────────────────────────
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
    limit = user_bot_limit(user)
    active = sum(1 for b in user_bots if b.get("running"))
    return render_template(
        "dashboard.html",
        site=get_config(),
        user=user,
        bots=user_bots,
        limit=limit,
        active=active,
        stopped=len(user_bots) - active,
        days=days_left(user),
        plan_active=user_plan_active(user),
        is_admin=is_admin(user),
    )

@app.route("/bots/new", methods=["GET", "POST"])
@login_required
def new_bot():
    user = current_user()
    site = get_config()
    limit = user_bot_limit(user)
    if not user_plan_active(user):
        flash("Plan expired. Upgrade to deploy bots.", "error")
        return redirect(url_for("pricing"))
    if len(user.get("bots", [])) >= limit:
        flash(f"Bot limit reached ({limit}). Upgrade plan.", "error")
        return redirect(url_for("pricing"))

    if request.method == "GET":
        return render_template("new_bot.html", site=site)

    name = (request.form.get("name") or "My Bot").strip()
    token = (request.form.get("token") or "").strip()
    entry_file = (request.form.get("entry_file") or "main.py").strip() or "main.py"
    if not entry_file.endswith(".py"):
        entry_file += ".py"
    upload = request.files.get("bot_file")

    if not token:
        flash("Bot token required.", "error")
        return render_template("new_bot.html", site=site)

    bot_id = uuid.uuid4().hex[:12]
    uid = str(session["user_id"])
    work = bot_workdir(uid, bot_id)
    work.mkdir(parents=True, exist_ok=True)

    if upload and upload.filename:
        filename = secure_filename(upload.filename)
        if filename.lower().endswith(".zip"):
            zpath = work / filename
            upload.save(zpath)
            try:
                with zipfile.ZipFile(zpath, "r") as zf:
                    zf.extractall(work)
            except Exception as e:
                shutil.rmtree(work, ignore_errors=True)
                flash(f"Zip extract failed: {e}", "error")
                return render_template("new_bot.html", site=site)
            zpath.unlink(missing_ok=True)
            # auto-detect entry if chosen file missing
            if not (work / entry_file).exists():
                for c in ("main.py", "bot.py", "app.py", "run.py"):
                    if (work / c).exists():
                        entry_file = c
                        break
                else:
                    pys = list(work.rglob("*.py"))
                    if pys:
                        entry_file = str(pys[0].relative_to(work))
        elif filename.lower().endswith(".py"):
            dest = work / entry_file
            upload.save(dest)
        else:
            shutil.rmtree(work, ignore_errors=True)
            flash("Upload a .py or .zip file.", "error")
            return render_template("new_bot.html", site=site)
    else:
        (work / entry_file).write_text(STARTERS["pyTelegramBotAPI"], encoding="utf-8")

    req = work / "requirements.txt"
    if not req.exists():
        req.write_text("pyTelegramBotAPI==4.22.1\nrequests==2.32.3\n", encoding="utf-8")

    bots_db = get_bots_db()
    bots_db[bot_id] = {
        "id": bot_id,
        "name": name,
        "token": token,
        "entry": entry_file,
        "owner": int(uid),
        "created_at": datetime.utcnow().isoformat(),
        "status": "stopped",
        "library": "custom",
    }
    save_bots_db(bots_db)
    users = get_users()
    users[uid].setdefault("bots", []).append(bot_id)
    save_users(users)
    flash(f"Bot '{name}' created.", "success")
    return redirect(url_for("dashboard"))

@app.route("/bots/<bot_id>/start", methods=["POST"])
@login_required
def bot_start(bot_id):
    user = current_user()
    if bot_id not in user.get("bots", []):
        abort(403)
    if not user_plan_active(user):
        flash("Plan expired.", "error")
        return redirect(url_for("dashboard"))
    bots_db = get_bots_db()
    b = bots_db.get(bot_id)
    if not b:
        abort(404)
    ok, msg = start_bot_process(str(session["user_id"]), bot_id, b["token"], b.get("entry", "main.py"))
    if ok:
        b["status"] = "running"
        b["entry"] = msg if isinstance(msg, str) and msg.endswith(".py") else b.get("entry", "main.py")
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
    content = log_path.read_text(encoding="utf-8", errors="ignore")[-12000:] if log_path.exists() else ""
    return render_template("logs.html", site=get_config(), bot_id=bot_id, logs=content)

# ── file manager ─────────────────────────────────────────────────────────────
@app.route("/files")
@login_required
def files():
    uid = str(session["user_id"])
    root = BOTS_DIR / uid
    root.mkdir(parents=True, exist_ok=True)
    rel = request.args.get("path", "").replace("..", "")
    cur = (root / rel).resolve()
    if not str(cur).startswith(str(root.resolve())):
        abort(403)
    if not cur.exists():
        cur = root
        rel = ""
    items = []
    if cur.is_dir():
        for p in sorted(cur.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            items.append({
                "name": p.name,
                "path": str((Path(rel) / p.name).as_posix()) if rel else p.name,
                "is_dir": p.is_dir(),
                "size": p.stat().st_size if p.is_file() else 0,
            })
    total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    return render_template(
        "files.html", site=get_config(), items=items, rel=rel,
        total=total, parent="/".join(rel.split("/")[:-1]) if rel else None,
    )

@app.route("/files/upload", methods=["POST"])
@login_required
def files_upload():
    uid = str(session["user_id"])
    root = BOTS_DIR / uid
    rel = request.form.get("path", "").replace("..", "")
    cur = (root / rel).resolve()
    if not str(cur).startswith(str(root.resolve())):
        abort(403)
    cur.mkdir(parents=True, exist_ok=True)
    f = request.files.get("file")
    if not f or not f.filename:
        flash("No file.", "error")
        return redirect(url_for("files", path=rel))
    name = secure_filename(f.filename)
    dest = cur / name
    f.save(dest)
    if name.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(dest, "r") as zf:
                zf.extractall(cur)
            dest.unlink(missing_ok=True)
            flash("Zip uploaded and extracted.", "success")
        except Exception as e:
            flash(f"Uploaded but extract failed: {e}", "error")
    else:
        flash("File uploaded.", "success")
    return redirect(url_for("files", path=rel))

@app.route("/files/delete", methods=["POST"])
@login_required
def files_delete():
    uid = str(session["user_id"])
    root = BOTS_DIR / uid
    target = request.form.get("target", "").replace("..", "")
    path = (root / target).resolve()
    if not str(path).startswith(str(root.resolve())):
        abort(403)
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        flash("Deleted.", "success")
    parent = "/".join(target.split("/")[:-1])
    return redirect(url_for("files", path=parent))

@app.route("/files/edit", methods=["GET", "POST"])
@login_required
def files_edit():
    uid = str(session["user_id"])
    root = BOTS_DIR / uid
    target = (request.args.get("path") or request.form.get("path") or "").replace("..", "")
    path = (root / target).resolve()
    if not str(path).startswith(str(root.resolve())):
        abort(403)
    if request.method == "POST":
        content = request.form.get("content", "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        flash("Saved.", "success")
        parent = "/".join(target.split("/")[:-1])
        return redirect(url_for("files", path=parent))
    if not path.exists() or not path.is_file():
        flash("File not found.", "error")
        return redirect(url_for("files"))
    # only edit text-ish
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        flash("Cannot edit binary file.", "error")
        return redirect(url_for("files"))
    return render_template("edit_file.html", site=get_config(), path=target, content=content)

# ── settings / upgrade ───────────────────────────────────────────────────────
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()
    if request.method == "POST":
        uname = request.form.get("username", "").strip().lstrip("@").lower()
        users = get_users()
        users[str(session["user_id"])]["username"] = uname
        save_users(users)
        flash("Profile updated.", "success")
        return redirect(url_for("settings"))
    return render_template(
        "settings.html", site=get_config(), user=user,
        days=days_left(user), plan_active=user_plan_active(user),
        plans=get_config()["plans"],
    )

@app.route("/upgrade", methods=["POST"])
@login_required
def upgrade():
    plan = request.form.get("plan", "free")
    if plan not in get_config()["plans"]:
        flash("Invalid plan.", "error")
        return redirect(url_for("pricing"))
    # self-serve activate (payment can be manual / admin)
    set_plan(str(session["user_id"]), plan, notify=True)
    flash(f"Plan set to {plan.upper()}. Check Telegram for confirmation.", "success")
    return redirect(url_for("dashboard"))

# ── admin ────────────────────────────────────────────────────────────────────
@app.route("/admin")
@admin_required
def admin_panel():
    return render_template(
        "admin.html",
        site=get_config(),
        users=get_users(),
        bots=get_bots_db(),
        running=sum(1 for bid in get_bots_db() if is_bot_running(bid)),
        plans=get_config()["plans"],
    )

@app.route("/admin/config", methods=["POST"])
@admin_required
def admin_config():
    cfg = get_config()
    token = request.form.get("hosting_bot_token", "").strip()
    admins = request.form.get("admin_usernames", "").strip()
    if token:
        cfg["hosting_bot_token"] = token
    if admins:
        cfg["admin_usernames"] = [a.strip().lstrip("@").lower() for a in admins.replace(",", " ").split() if a.strip()]
    save_json(CONFIG_FILE, cfg)
    flash("Config saved.", "success")
    return redirect(url_for("admin_panel"))

@app.route("/admin/user/<uid>/plan", methods=["POST"])
@admin_required
def admin_set_plan(uid):
    plan = request.form.get("plan", "free")
    if set_plan(uid, plan, notify=True):
        flash(f"User {uid} → {plan}", "success")
    return redirect(url_for("admin_panel"))

@app.route("/admin/bot/<bot_id>/stop", methods=["POST"])
@admin_required
def admin_stop_bot(bot_id):
    stop_bot_process(bot_id)
    bots_db = get_bots_db()
    if bot_id in bots_db:
        bots_db[bot_id]["status"] = "stopped"
        save_bots_db(bots_db)
    flash("Force stopped.", "success")
    return redirect(url_for("admin_panel"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"Ziaa starting on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
