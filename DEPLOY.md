# Деплой бота 24/7

Бот должен работать круглосуточно — для этого его надо поднять на сервере, а не на твоём ПК.

> ⚠️ **Не используй GitHub Actions для запуска бота.** Job живёт максимум ~6 часов, SQLite-файл не сохраняется между запусками, а параллельный polling конфликтует с основным ботом. Workflow в `.github/workflows/` служит только для keep-alive пинга.

---

## Вариант 1 — Railway (проще всего, есть бесплатный триал)

1. Запушь код на GitHub (ниже).
2. Зайди на [railway.app](https://railway.app) → Login через GitHub.
3. New Project → Deploy from GitHub repo → выбери `pivdoner-bot`.
4. В Settings → Variables добавь:
   - `BOT_TOKEN`
   - `FALLBACK_BOT_TOKEN`
   - `MANAGER_CHAT_ID`
   - `ADMIN_IDS`
   - `PAYMENT_URL`
   - `PAYMENT_ENABLED=1`
   - `DEMO_MODE=0`
   - `SELLER_CONTACT=@xxlkkl`
5. Deploy. Бот работает 24/7. Логи видны в Dashboard.

⚠️ Бесплатный план Railway даёт ~$5 кредитов/мес — для такого бота хватает.

---

## Вариант 2 — Render (бесплатный, с auto-wake)

1. Пуш на GitHub.
2. [render.com](https://render.com) → New → **Web Service** (не Background Worker — нужен порт для keep-alive).
3. Подключи репозиторий, runtime **Python 3**.
4. Build Command: `pip install -r requirements.txt`
   Start Command: `python bot.py`
5. В Environment добавь переменные из `.env` + **`RENDER_EXTERNAL_URL`** = твой публичный URL сервиса, например:
   ```
   RENDER_EXTERNAL_URL=https://pivdoner-bot.onrender.com
   ```
   Бот сам будет пинговать себя каждые 10 минут (`/health`) и не заснёт.
6. (Опционально) Добавь тот же URL в GitHub Secret `BOT_HEALTH_URL` — workflow будет стучаться каждые 10 минут как резервный будильник.

⚠️ На бесплатном Render сервис «засыпает» после ~15 минут без HTTP-трафика — keep-alive в `bot.py` решает это. Telegram-поллиинг при этом работает и без HTTP, но health-check нужен Render'у, чтобы не гасить сервис.

---

## Вариант 3 — VPS (надёжнее всего, ~$3–5/мес)

Timeweb / Selectel / AEZA — самый дешёвый тариф.

```bash
git clone https://github.com/diiskomickii-max/pivdoner-bot
cd pivdoner-bot
pip install -r requirements.txt
nano .env   # вставь значения

# Автозапуск и авто-перезапуск при падении — через systemd:
sudo tee /etc/systemd/system/pivdoner-bot.service > /dev/null <<'EOF'
[Unit]
Description=PivDoner Telegram Bot
After=network.target

[Service]
WorkingDirectory=/root/pivdoner-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pivdoner-bot
sudo journalctl -u pivdoner-bot -f   # логи
```

---

## Команды для заливки на GitHub

```bash
git init
git add .
git commit -m "PivDoner preorder bot"
gh repo create pivdoner-bot --public --source=. --push
```

Перед пушем убедись, что `.env` в `.gitignore` — токен нельзя выкладывать.

---

## Авто-перезапуск при сбоях (уже встроено)

`bot.py` обёрнут в `run_with_restart()` — при сетевом сбое или падении поллинга бот сам перезапустится с экспоненциальной задержкой (5, 10, 15… макс 60 сек). В связке с `Restart=always` в systemd или авто-рестартом Railway/Render бот получается полностью самовосстанавливающимся.
