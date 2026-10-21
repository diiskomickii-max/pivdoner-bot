import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# Чат заведения, куда падают заказы (id группы/лички менеджера)
MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "0"))

# Оплата онлайн: ссылка на платёжную страницу банка/сервиса кафе.
# Для ЕРИП — сюда вставляется URL оплаты инвойса (WebPay/bepaid и т.п.).
# {amount} и {order_id} подставятся в ссылку, если шаблон их содержит.
PAYMENT_URL = os.getenv(
    "PAYMENT_URL",
    "https://pay.example.com/pay?order={order_id}&sum={amount}",  # заглушка
)
PAYMENT_ENABLED = os.getenv("PAYMENT_ENABLED", "1") == "1"

DB_PATH = BASE_DIR / "bot.db"
