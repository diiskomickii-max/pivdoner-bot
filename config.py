import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# Чат заведения, куда падают заказы (id группы/лички менеджера)
MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "0"))

# Демо-режим: 0 = боевой (заказы в группу), 1 = демо (заказы клиенту)
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
SELLER_CONTACT = os.getenv("SELLER_CONTACT", "@xxlkkl")

# Оплата онлайн
PAYMENT_URL = os.getenv(
    "PAYMENT_URL",
    "https://pay.example.com/pay?order={order_id}&sum={amount}",
)
PAYMENT_ENABLED = os.getenv("PAYMENT_ENABLED", "1") == "1"

DB_PATH = BASE_DIR / "bot.db"
