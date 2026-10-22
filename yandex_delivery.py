"""Модуль интеграции и симуляции Яндекс Доставки (Yandex Go Delivery) для кафе «ПивДонер».

Имитирует:
1. Расчёт стоимости и времени доставки Яндекс Go по Минску.
2. Жизненный цикл доставки:
   - Поиск курьера
   - Назначение курьера (автомобиль, госномер, имя)
   - Прибытие в кафе за заказом
   - Доставка по маршруту (в пути с термосумкой)
   - Прибытие к подъезду клиента
   - Завершение доставки
"""

import asyncio
import logging
import random
from typing import Dict, Any, Tuple
from aiogram import Bot
from db import get_order, set_order_status

COURIERS = [
    {"name": "Александр", "car": "Белый Hyundai Solaris", "plate": "7788-7", "rating": "4.98"},
    {"name": "Дмитрий", "car": "Серый Skoda Rapid", "plate": "1234-7", "rating": "4.95"},
    {"name": "Максим", "car": "Чёрный Volkswagen Polo", "plate": "9941-7", "rating": "4.99"},
    {"name": "Артём", "car": "Серебристый Kia Rio", "plate": "3456-7", "rating": "4.92"},
]


def calculate_yandex_delivery(address: str, cart_total: float) -> Dict[str, Any]:
    """Расчёт тарифа Яндекс Доставки."""
    # Бесплатная доставка от 35 Br, иначе фиксированный удобный тариф 5.00 Br
    if cart_total >= 35.0:
        cost = 0.0
        is_free = True
    else:
        cost = 5.00
        is_free = False

    eta_minutes = random.randint(30, 45)
    return {
        "cost": cost,
        "is_free": is_free,
        "eta_minutes": eta_minutes,
        "courier_eta_to_cafe": random.randint(5, 8),
    }


def get_random_courier() -> Dict[str, str]:
    return random.choice(COURIERS)


async def run_yandex_delivery_simulation(
    bot: Bot,
    order_id: int,
    user_id: int,
    address: str,
    admin_chat_id: int = 0,
    admin_msg_id: int = 0,
):
    """
    Асинхронный симулятор жизненного цикла Яндекс Доставки в реальном времени.
    Отправляет клиенту пуши с реалистичными задержками и обновляет статус заказа.
    """
    courier = get_random_courier()

    async def _simulation_process():
        try:
            # 1. Поиск курьера через 6 секунд
            await asyncio.sleep(6)
            try:
                await bot.send_message(
                    user_id,
                    f"🚕 <b>Яндекс Доставка (Заказ №{order_id}):</b>\n"
                    f"Ищем ближайшего свободного курьера Яндекс Go рядом с кафе «ПивДонер»..."
                )
            except Exception:
                pass

            # 2. Курьер назначен через 12 секунд
            await asyncio.sleep(12)
            courier_info = f"{courier['name']} ({courier['car']}, {courier['plate']})"
            try:
                await bot.send_message(
                    user_id,
                    f"🚕 <b>Курьер Яндекс Доставки назначен!</b>\n\n"
                    f"👤 Водитель: <b>{courier['name']}</b> (Рейтинг ⭐ {courier['rating']})\n"
                    f"🚗 Автомобиль: <b>{courier['car']}</b>\n"
                    f"🔢 Госномер: <code>{courier['plate']}</code>\n"
                    f"⏱ Подъедет в кафе за заказом через <b>6–8 минут</b>."
                )
            except Exception:
                pass

            if admin_chat_id:
                try:
                    await bot.send_message(
                        admin_chat_id,
                        f"🚕 <b>Заказ №{order_id} (Яндекс Доставка):</b>\n"
                        f"Курьер назначен: <b>{courier['name']}</b> ({courier['car']}, <code>{courier['plate']}</code>).\n"
                        f"Подъедет на кухню за заказом через 6–8 минут."
                    )
                except Exception:
                    pass

            # 2.5. Курьер ПРИБЫЛ В КАФЕ за заказом через 18 секунд
            await asyncio.sleep(18)
            try:
                await bot.send_message(
                    user_id,
                    f"🚕 <b>Заказ №{order_id}:</b> Курьер {courier['name']} прибыл в кафе «ПивДонер» и забирает ваш заказ горячим с кухни!"
                )
            except Exception:
                pass

            if admin_chat_id:
                try:
                    await bot.send_message(
                        admin_chat_id,
                        f"🔔 <b>Внимание кухне / кассе!</b>\n\n"
                        f"🚕 Курьер Яндекс Go прибыл за <b>Заказом №{order_id}</b>!\n"
                        f"👤 Водитель: <b>{courier['name']}</b>\n"
                        f"🚗 Автомобиль: <b>{courier['car']}</b> (<code>{courier['plate']}</code>)\n"
                        f"👉 Выдайте пакет с заказом <b>№{order_id}</b> курьеру."
                    )
                except Exception:
                    pass

            # 3. Курьер забрал заказ из кафе и везёт клиенту через 15 секунд
            await asyncio.sleep(15)
            try:
                await bot.send_message(
                    user_id,
                    f"📦 <b>Курьер забрал ваш заказ из кафе «ПивДонер»!</b>\n\n"
                    f"🚗 {courier['name']} выехал на автомобиле <b>{courier['plate']}</b>.\n"
                    f"📍 Адрес доставки: <b>{address}</b>\n"
                    f"⏱ Расчётное время в пути: <b>~20 минут</b>\n\n"
                    f"🌡 <i>Еда упакована в термосумку горячей прямо с гриля.</i>"
                )
            except Exception:
                pass

            if admin_chat_id:
                try:
                    await bot.send_message(
                        admin_chat_id,
                        f"✅ <b>Заказ №{order_id} ПЕРЕДАН курьеру!</b>\nКурьер {courier['name']} забрал термосумку с кухни и выехал к клиенту ({address})."
                    )
                except Exception:
                    pass

            # 4. Курьер подъехал к подъезду через 25 секунд
            await asyncio.sleep(25)
            try:
                await bot.send_message(
                    user_id,
                    f"🔔 <b>Курьер Яндекс Доставки прибыл по адресу!</b>\n\n"
                    f"🚗 {courier['car']} (<code>{courier['plate']}</code>) ожидает у подъезда.\n"
                    f"Пожалуйста, встретьте курьера или ожидайте звонка в домофон."
                )
            except Exception:
                pass

            # 5. Успешно вручено через 15 секунд
            await asyncio.sleep(15)
            # Обновляем статус в базе данных на completed
            await set_order_status(order_id, "completed")

            try:
                await bot.send_message(
                    user_id,
                    f"❤️ <b>Заказ №{order_id} успешно доставлен!</b>\n\n"
                    f"Приятного аппетита! Ждём ваших новых заказов в «ПивДонер»!"
                )
            except Exception:
                pass

            # Уведомление для кухни / администратора об успешной сдаче заказа
            if admin_chat_id:
                try:
                    await bot.send_message(
                        admin_chat_id,
                        f"🏁 <b>Заказ №{order_id} УСПЕШНО ДОСТАВЛЕН!</b>\n\n"
                        f"👤 Курьер {courier['name']} (<code>{courier['plate']}</code>) передал заказ клиенту.\n"
                        f"📍 Адрес: {address}\n"
                        f"📊 Статус заказа в системе автоматически обновлён на: <b>🏁 Выдан / Завершён</b>."
                    )
                except Exception:
                    pass

            # Обновление карточки заказа в чате кухни
            if admin_chat_id and admin_msg_id:
                try:
                    import keyboards as kb
                    from config import DEMO_MODE
                    from handlers import make_order_text
                    updated_order = await get_order(order_id)
                    if updated_order:
                        updated_order = dict(updated_order)
                        updated_order["status"] = "completed"
                        await bot.edit_message_text(
                            chat_id=admin_chat_id,
                            message_id=admin_msg_id,
                            text=make_order_text(updated_order, is_demo=DEMO_MODE),
                            reply_markup=kb.status_kb(order_id, status="completed", payment=updated_order.get("payment", "none")),
                        )
                except Exception:
                    pass

            # Автоматический запуск сбора отзыва (NPS) через 10 секунд
            try:
                from handlers import schedule_order_review
                schedule_order_review(bot, order_id, user_id, delay_sec=10)
            except Exception:
                pass

        except Exception as e:
            logging.exception("Error in yandex delivery simulation: %s", e)

    asyncio.create_task(_simulation_process())
