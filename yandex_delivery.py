"""
Интеграция с Яндекс Доставкой (Yandex Go Delivery) для кафе «ПивДонер».
Реализует расчёт тарифов, симуляцию курьера и отслеживание статуса доставки.
"""
import asyncio
import logging
import random
from typing import Dict, Any
from aiogram import Bot

from db import set_order_status, get_order

COURIERS = [
    {"name": "Артём", "phone": "+375 29 332-11-22", "car": "Серебристый Kia Rio", "plate": "3456-7", "rating": "4.95"},
    {"name": "Максим", "phone": "+375 33 665-44-33", "car": "Белый Volkswagen Polo", "plate": "7712-7", "rating": "4.98"},
    {"name": "Дмитрий", "phone": "+375 44 554-33-22", "car": "Серый Hyundai Accent", "plate": "5501-7", "rating": "4.92"},
    {"name": "Александр", "phone": "+375 29 881-22-33", "car": "Синий Renault Logan", "plate": "9934-7", "rating": "4.89"},
]

ACTIVE_DELIVERY_TASKS: Dict[int, asyncio.Task] = {}


def cancel_delivery_simulation(order_id: int):
    """Немедленно останавливает симуляцию доставки при отмене заказа."""
    task = ACTIVE_DELIVERY_TASKS.pop(order_id, None)
    if task and not task.done():
        task.cancel()
        logging.info("Симуляция доставки для заказа #%s успешно отменена.", order_id)


def calculate_yandex_delivery(address: str, cart_total: float) -> Dict[str, Any]:
    """Расчёт тарифа доставки."""
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
    Строго проверяет статус заказа перед каждым шагом — если заказ отменён, симуляция мгновенно прекращается.
    """
    courier = get_random_courier()

    async def _is_cancelled() -> bool:
        ord_info = await get_order(order_id)
        if not ord_info or ord_info["status"] == "cancelled":
            return True
        return False

    async def _simulation_process():
        try:
            # 1. Поиск курьера через 6 секунд
            await asyncio.sleep(6)
            if await _is_cancelled():
                return

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
            if await _is_cancelled():
                return

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
            if await _is_cancelled():
                return

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
            if await _is_cancelled():
                return

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
            if await _is_cancelled():
                return

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
            if await _is_cancelled():
                return

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
                            reply_markup=kb.status_kb(
                                order_id,
                                status="completed",
                                payment=updated_order.get("payment", "none"),
                                delivery_type=updated_order.get("delivery_type", "yandex"),
                            ),
                        )
                except Exception:
                    pass

            # Запрос отзыва (NPS) спустя 20 минут (1200 секунд)
            try:
                from handlers import schedule_order_review
                schedule_order_review(bot, order_id, user_id, delay_sec=1200)
            except Exception:
                pass

        except asyncio.CancelledError:
            logging.info("Симуляция доставки заказа #%s была отменена.", order_id)
        except Exception as e:
            logging.exception("Ошибка в симуляции Яндекс Доставки: %s", e)
        finally:
            ACTIVE_DELIVERY_TASKS.pop(order_id, None)

    task = asyncio.create_task(_simulation_process())
    ACTIVE_DELIVERY_TASKS[order_id] = task
