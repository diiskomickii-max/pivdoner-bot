import asyncio
import logging
import os
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import BOT_TOKEN, FALLBACK_BOT_TOKEN
from db import init_db
from handlers import router

logging.basicConfig(level=logging.INFO)


GLOBAL_BOT: Bot = None


async def get_working_bot() -> Bot:
    """Проверяет доступность основного токена, при сбое автоматически переключается на запасной."""
    global GLOBAL_BOT
    tokens = [t for t in [BOT_TOKEN, FALLBACK_BOT_TOKEN] if t]
    for token in tokens:
        try:
            bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            me = await bot.get_me()
            logging.info("✅ Успешно запущен бот: @%s (ID: %s)", me.username, me.id)
            GLOBAL_BOT = bot
            return bot
        except Exception as e:
            logging.error("⚠️ Токен %s... не отвечает: %s. Пробуем резервный токен...", token[:12], e)
    raise RuntimeError("Ни один из токенов Telegram бота не отвечает!")


async def handle_health(request):
    return web.Response(text="PivDoner Production Bot is running OK", content_type="text/plain")


async def handle_yandex_webhook(request):
    """Принимает вебхук от платёжной системы / сервиса Яндекс Доставка."""
    try:
        data = await request.json()
        try:
            order_id = int(data.get("order_id", 0))
        except (TypeError, ValueError):
            return web.json_response({"error": "invalid order_id"}, status=400)
        status = str(data.get("status", "")).strip().lower()
        from db import set_order_payment, get_order
        import keyboards as kb
        from handlers import _send_order_to_group

        order = await get_order(order_id)
        if not order:
            return web.json_response({"error": "order not found"}, status=404)

        user_id = order["user_id"]
        if status == "success":
            await set_order_payment(order_id, "paid")
            if GLOBAL_BOT:
                await GLOBAL_BOT.send_message(
                    user_id,
                    f"✅ <b>Оплата заказа №{order_id} через сервис Яндекс успешно получена!</b> (Оплачено)\n\n"
                    f"Заказ поступил на кухню «ПивДонер». Скоро повара начнут приготовление!",
                )
                await _send_order_to_group(GLOBAL_BOT, order_id, "paid", user_id)
            return web.json_response({"status": "ok", "action": "paid"})
        elif status == "failed":
            eda_url = os.getenv("YANDEX_EDA_URL", "https://eda.yandex.by/")
            if GLOBAL_BOT:
                await GLOBAL_BOT.send_message(
                    user_id,
                    f"⚠️ <b>Оплата заказа №{order_id} в сервисе Яндекс не прошла или была отклонена банком.</b>\n\n"
                    f"Заказ пока не передан поварам.\n\n"
                    f"Вы можете попробовать оплатить повторно или переключить заказ на <b>Самовывоз</b>.",
                    reply_markup=kb.yandex_payment_failed_kb(order_id, eda_url),
                )
            return web.json_response({"status": "ok", "action": "failed_notified"})
        return web.json_response({"status": "ignored"})
    except Exception as e:
        logging.exception("Webhook error: %s", e)
        return web.json_response({"error": str(e)}, status=500)


async def handle_webapp(request):
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="Web App not found", status=404)


async def keep_alive_task():
    """Фоновый пинг для бесплатных облачных платформ (Render/Railway и др.),
    чтобы сервис не засыпал. URL берётся из RENDER_EXTERNAL_URL или SELF_URL."""
    url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SELF_URL")
    if not url:
        logging.info("Keep-alive disabled: RENDER_EXTERNAL_URL/SELF_URL is not set.")
        return
    url = url.rstrip("/")
    await asyncio.sleep(60)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    logging.info("Keep-alive ping to %s -> %s", url, resp.status)
            except Exception as e:
                logging.warning("Keep-alive ping failed: %s", e)
            await asyncio.sleep(600)  # каждые 10 минут


async def start_web_server():
    """Запуск легковесного HTTP-сервера для веб-приложения и проверок доступности."""
    port = int(os.getenv("PORT", "8082"))
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/webapp", handle_webapp)
    app.router.add_post("/api/yandex_webhook", handle_yandex_webhook)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.router.add_static("/static", static_dir)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("Web App & Healthcheck server running on port %s", port)


async def main():
    await init_db()
    bot = await get_working_bot()
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    # Запуск фонового веб-сервера для совместимости с бесплатными облаками
    try:
        await start_web_server()
        asyncio.create_task(keep_alive_task())
    except Exception as e:
        logging.warning("Web server start failed (non-critical): %s", e)

    # Панель быстрых команд в Telegram (кнопка «Меню»)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="🏠 Главное меню / Регистрация"),
            BotCommand(command="help", description="📌 Инструкция ко всем кнопкам"),
            BotCommand(command="guide", description="📖 Руководство покупателя"),
            BotCommand(command="menu", description="🍔 Меню кафе «ПивДонер»"),
            BotCommand(command="order", description="🛒 Оформить заказ"),
            BotCommand(command="cart", description="🧺 Корзина"),
            BotCommand(command="profile", description="👤 Личный кабинет"),
            BotCommand(command="history", description="📜 Мои заказы"),
            BotCommand(command="info", description="📍 Адрес и инфо"),
            BotCommand(command="complaint", description="🚨 Подать жалобу"),
            BotCommand(command="find", description="🔍 Поиск заказов по номеру"),
            BotCommand(command="cancel", description="❌ Отмена действия"),
        ])
    except Exception as e:
        logging.warning("Failed to set bot commands: %s", e)

    logging.info("Бот запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


async def run_with_restart():
    """Перезапускает бота при сетевых сбоях — бесконечный цикл для работы 24/7."""
    retry = 0
    while True:
        try:
            await main()
            break  # корректная остановка
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception as e:
            retry += 1
            wait = min(60, 5 * retry)
            logging.exception("Бот упал с ошибкой (%s). Перезапуск #%s через %s сек...", e, retry, wait)
            await asyncio.sleep(wait)


if __name__ == "__main__":
    try:
        asyncio.run(run_with_restart())
    except KeyboardInterrupt:
        pass
