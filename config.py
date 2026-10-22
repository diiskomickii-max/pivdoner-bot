import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
FALLBACK_BOT_TOKEN = os.getenv("FALLBACK_BOT_TOKEN", "8757155774:AAFLoVePmUcJFYhq6xhb-Fw7eQeSVFXiF5E")
# Чат заведения, куда падают заказы (id группы/лички менеджера)
MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "0"))

# Демо-режим: 0 = боевой (заказы в группу), 1 = демо (заказы клиенту в этот же чат)
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"
SELLER_CONTACT = os.getenv("SELLER_CONTACT", "@xxlkkl")

# Оплата онлайн
PAYMENT_URL = os.getenv(
    "PAYMENT_URL",
    "https://pay.example.com/pay?order={order_id}&sum={amount}",
)
PAYMENT_ENABLED = os.getenv("PAYMENT_ENABLED", "1") == "1"

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://diiskomickii-max.github.io/pivdoner-bot/")

DB_PATH = BASE_DIR / "bot.db"
