import asyncio
import logging
import os
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from db import init_db
from handlers import router

logging.basicConfig(level=logging.INFO)


async def handle_health(request):
    return web.Response(text="PivDoner Production Bot is running OK", content_type="text/plain")


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
    """Запуск легковесного HTTP-сервера для облачных проверок доступности (Render/Koyeb/Railway)."""
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("Healthcheck web server running on port %s", port)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан — создай файл .env с BOT_TOKEN=...")
    await init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    # Запуск фонового веб-сервера для совместимости с бесплатными облаками
    await start_web_server()
    asyncio.create_task(keep_alive_task())

    logging.info("Бот запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
