# Деплой бота 24/7

Бот должен работать круглосуточно — для этого его надо поднять на сервере, а не на твоём ПК.

## Вариант 1 — Railway (проще всего, бесплатный план есть)

1. Запушь код на GitHub (ниже).
2. Зайди на [railway.app](https://railway.app) → Login через GitHub.
3. New Project → Deploy from GitHub repo → выбери `pivdoner-bot`.
4. В Settings → Variables добавь:
   - `BOT_TOKEN`
   - `MANAGER_CHAT_ID`
   - `PAYMENT_URL`
   - `PAYMENT_ENABLED=1`
5. Deploy. Бот работает 24/7. Логи видны в Dashboard.

⚠️ Бесплатный план Railway даёт ~$5 кредитов/мес — для такого бота хватает.

## Вариант 2 — Render (бесплатный)

1. Пуш на GitHub.
2. [render.com](https://render.com) → New → Background Worker.
3. Подключи репозиторий, runtime Python.
4. Build: `pip install -r requirements.txt`, Start: `python bot.py`.
5. В Environment добавь переменные из .env.

⚠️ На бесплатном Render сервис «засыпает» без активности — для бота это ок, он просыпается на сообщение, но первое сообщение может идти ~30 сек.

## Вариант 3 — VPS (надёжнее всего, ~$3–5/мес)

Timeweb / Selectel / AEZA — самый дешёвый тариф.

```bash
git clone https://github.com/ТВОЙ_ЛОГИН/pivdoner-bot
cd pivdoner-bot
pip install -r requirements.txt
nano .env   # вставь значения
# автозапуск:
sudo apt install supervisor
# или просто:
nohup python bot.py &
```

## Команды для заливки на GitHub

```bash
git init
git add .
git commit -m "PivDoner preorder bot"
gh repo create pivdoner-bot --public --source=. --push
```

Перед пушем убедись, что `.env` в `.gitignore` — токен нельзя выкладывать.
