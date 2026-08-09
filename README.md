# TyraDev — Telegram Bot Hosting

Dark neon UI · OTP login · bot process manager · admin panel

## Local run
```bash
pip install -r requirements.txt
# edit data/config.json → hosting_bot_token + admin_telegram_ids
python app/main.py
# optional OTP bot:
python hosting_bot.py
```
Open http://127.0.0.1:5000

## Deploy on Render (tutorial)

### 1. Push to GitHub
1. Create a new GitHub repo
2. Upload the `tyradev` folder contents (or push this project)
3. Make sure these files are at the **repo root**:
   - `wsgi.py`
   - `Procfile`
   - `requirements.txt`
   - `app/`
   - `data/config.json`
   - `hosting_bot.py`

### 2. Create a Render Web Service
1. Go to https://render.com → **New +** → **Web Service**
2. Connect your GitHub repo
3. Settings:
   - **Name:** tyradev-hosting
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120`
   - **Instance type:** Free

### 3. Environment (optional)
You can leave config in `data/config.json`.  
On free Render, the filesystem is ephemeral — after redeploy, data may reset.  
For real use, put tokens in Render **Environment** and we can wire them later.

### 4. Deploy
Click **Create Web Service**. Wait for the build (1–3 min).  
Open the `.onrender.com` URL.

### 5. OTP bot on Render
Free web services sleep + only one process. Options:
- **A.** Run OTP bot on your phone/pc: `python hosting_bot.py`
- **B.** Create a second Render **Background Worker** with start command:
  `python hosting_bot.py`
  (Background workers are paid on Render)

### 6. First login
1. Open the site
2. Sign in with your Telegram ID
3. Get OTP from the hosting bot
4. Admin id in `data/config.json` sees the Admin panel

## Notes
- User bots need `os.environ["BOT_TOKEN"]` (starters already do)
- Free Render sleeps after idle — first request may be slow
- For always-on bots, a small VPS is more reliable than free Render
