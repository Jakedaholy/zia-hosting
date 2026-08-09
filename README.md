# Ziaa — Telegram Bot Hosting

Dark panel · OTP login (30-day session) · zip deploy · file manager · plans with duration

## Plans
| Plan | Bots | Days | Price |
|------|------|------|-------|
| Free | 1 | 2 | $0 |
| Basic | 3 | 5 | $50 |
| Elite | 10 | 7 | $90 |
| Premium | 30 | 21 | $120 |

Admin username: **maisanyvokei**

## Local
```bash
pip install -r requirements.txt
# edit data/config.json → hosting_bot_token
python app/main.py
python hosting_bot.py
```

## Render
Build: `pip install -r requirements.txt`  
Start: `gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120`
