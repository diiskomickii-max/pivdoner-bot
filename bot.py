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


async def get_working_bot() -> Bot:
    """Проверяет доступность основного токена, при сбое автоматически переключается на запасной."""
    tokens = [t for t in [BOT_TOKEN, FALLBACK_BOT_TOKEN] if t]
    for token in tokens:
        try:
            bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            me = await bot.get_me()
            logging.info("✅ Успешно запущен бот: @%s (ID: %s)", me.username, me.id)
            return bot
        except Exception as e:
            logging.error("⚠️ Токен %s... не отвечает: %s. Пробуем резервный токен...", token[:12], e)
    raise RuntimeError("Ни один из токенов Telegram бота не отвечает!")


async def handle_health(request):
    return web.Response(text="PivDoner Production Bot is running OK", content_type="text/plain")


async def handle_webapp(request):
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="Web App not found", status=404)


async def keep_alive_task():
    """Фоновый пинг для бесплатных облачных платформ (Render и др.), чтобы сервис не засыпал."""
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    await asyncio.sleep(60)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await session.get(f"{url}/health")
                logging.info("Keep-alive ping sent to %s", url)
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
            BotCommand(command="webapp", description="🚀 Меню в Mini App"),
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


if __name__ == "__main__":
    asyncio.run(main())
