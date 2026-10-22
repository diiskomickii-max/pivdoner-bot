import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message

import keyboards as kb
from config import (
    DEMO_MODE,
    MANAGER_CHAT_ID,
    PAYMENT_ENABLED,
    PAYMENT_URL,
    SELLER_CONTACT,
)
from db import (
    add_bonus,
    create_complaint,
    create_order,
    create_review,
    get_active_orders,
    get_all_orders_for_export,
    get_all_users,
    get_order,
    get_order_status,
    get_overall_reviews_stats,
    get_today_stats,
    get_user,
    get_user_average_rating,
    get_user_orders,
    get_user_referral_stats,
    get_user_stats,
    search_orders_by_phone,
    set_last_bonus_game,
    set_order_payment,
    set_order_status,
    set_referrer,
    update_user_name,
    update_user_phone,
    upsert_user,
)
from excel_report import generate_excel_report
from menu import CAFE, ITEMS, MENU, cart_text, fmt_price, pickup_ready_text
from states import (
    AdminSearchForm,
    BroadcastForm,
    ComplaintForm,
    OrderForm,
    ProfileEditForm,
    RegistrationForm,
    ReviewForm,
)
from thermal_printer import format_receipt_text, generate_esc_pos_bytes
from yandex_delivery import calculate_yandex_delivery, run_yandex_delivery_simulation

router = Router()

STATUS_TEXT = {
    "new": "🆕 Новый",
    "accepted": "✅ Принят",
    "cooking": "🔥 Готовится",
    "ready": "🛍 Готов к выдаче",
    "completed": "🏁 Выдан гостю",
    "cancelled": "❌ Отменён",
}

PAYMENT_TEXT = {
    "none": "не выбрана",
    "cash": "💵 на месте",
    "online_marked": "💳 онлайн (ждёт подтверждения)",
    "paid": "✅ оплачен онлайн",
}


def make_order_text(order: dict, is_demo: bool = False) -> str:
    """Формирует актуальный текст заказа для админ-чата без дублирования статусов."""
    pay_str = PAYMENT_TEXT.get(order.get("payment", "none"), order.get("payment", "none"))
    st_str = STATUS_TEXT.get(order.get("status", "new"), order.get("status", "new"))
    deliv_type = order.get("delivery_type", "pickup")

    if deliv_type == "yandex":
        addr = order.get("delivery_address") or "Не указан"
        d_cost = order.get("delivery_cost") or 0.0
        deliv_block = (
            f"🚕 Доставка: <b>Яндекс Доставка (курьер Yandex Go)</b>\n"
            f"📍 Адрес доставки: <b>{addr}</b>\n"
            f"🛵 Стоимость доставки: <b>{d_cost:.2f} Br</b>\n"
            f"⏱ Время: <b>{order.get('pickup_time', 'В ближайшее время')}</b>"
        )
    else:
        deliv_block = (
            f"🏃 Способ: <b>Самовывоз</b> ({CAFE['address']})\n"
            f"🕐 Придёт за заказом: <b>{order.get('pickup_time', 'Скоро')}</b>\n"
            f"🍽 {pickup_ready_text(order.get('pickup_time', ''))}"
        )

    text = (
        f"🆕 <b>Предзаказ №{order['id']}</b>\n\n"
        f"{order['items']}\n\n"
        f"💰 <b>{order['total']:.2f} Br</b>\n\n"
        f"👤 {order['name']}\n"
        f"📱 {order['phone']}\n"
        f"{deliv_block}\n"
        f"💳 Оплата: <b>{pay_str}</b>\n"
        f"📊 Статус: <b>{st_str}</b>"
    )
    if order.get("comment"):
        text += f"\n💬 {order['comment']}"
    if order.get("username"):
        text += f"\n🔗 @{order['username']}"
    if is_demo:
        text = "🧪 <b>Уведомление заведения (вы как админ/повар видите заказ):</b>\n\n" + text
    return text


# ---------- Валидация телефона (Задача 3) ----------

def validate_phone(raw: str) -> tuple[bool, str, str]:
    """
    Строгая валидация и нормализация номера телефона.
    Возвращает (is_valid, formatted_phone, error_message).
    Запрещает ввод букв и произвольного мусора.
    """
    if not raw or not isinstance(raw, str):
        return False, "", "Номер телефона не может быть пустым."

    text = raw.strip()

    # Проверка на наличие букв
    if re.search(r"[a-zA-Zа-яА-ЯёЁ]", text):
        return False, "", "В номере телефона не должно быть букв! Введите корректный номер цифрами."

    # Разрешены только +, пробелы, дефисы, скобки и цифры
    if re.search(r"[^\d+\s\(\)\-]", text):
        return False, "", "Номер содержит недопустимые символы. Используйте только цифры и знак «+»."

    digits = re.sub(r"\D", "", text)

    if len(digits) < 9:
        return False, "", "Слишком короткий номер телефона (в номере должно быть не менее 9 цифр)."

    if len(digits) > 15:
        return False, "", "Слишком длинный номер телефона (не более 15 цифр)."

    # Беларусь: 80 (11 цифр) -> +375
    if digits.startswith("80") and len(digits) == 11:
        return True, "+375" + digits[2:], ""

    # Беларусь: локальный мобильный 9 цифр (29XXXXXXX, 44, 33, 25, 17) -> +375
    if len(digits) == 9 and digits[:2] in ("25", "29", "33", "44", "17"):
        return True, "+375" + digits, ""

    # Беларусь: 12 цифр с 375
    if digits.startswith("375") and len(digits) == 12:
        return True, "+" + digits, ""

    # Россия: 89... (11 цифр) -> +7...
    if digits.startswith("8") and len(digits) == 11 and digits[1] == "9":
        return True, "+7" + digits[1:], ""

    # 11 цифр с 7
    if digits.startswith("7") and len(digits) == 11:
        return True, "+" + digits, ""

    # Международный номер с плюсом
    if text.startswith("+") and 10 <= len(digits) <= 15:
        return True, "+" + digits, ""

    if 10 <= len(digits) <= 15:
        return True, "+" + digits, ""

    return False, "", "Неверный формат номера. Введите номер (например, +375 29 123-45-67) или нажмите «📱 Подтвердить номер через Telegram»."


# ---------- Хелперы для чистого чата (Задача 1) ----------

async def delete(msg: Message):
    """Безопасное удаление сообщения."""
    try:
        await msg.delete()
    except Exception:
        pass


async def cleanup_step_msg(state: FSMContext, bot: Bot, chat_id: int):
    """Удаляет предыдущее окно/вопрос бота, чтобы сообщения не копились."""
    data = await state.get_data()
    msg_id = data.get("current_step_msg_id")
    if msg_id:
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass
    await state.update_data(current_step_msg_id=None)


async def send_step_msg(state: FSMContext, bot: Bot, chat_id: int, text: str, reply_markup=None):
    """Удаляет предыдущее окно и отправляет новое, сохраняя его id для очистки."""
    await cleanup_step_msg(state, bot, chat_id)
    msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    await state.update_data(current_step_msg_id=msg.message_id)
    return msg


async def get_cart(state: FSMContext) -> dict:
    data = await state.get_data()
    return dict(data.get("cart", {}))


async def save_cart(state: FSMContext, cart: dict):
    cart = {k: v for k, v in cart.items() if v > 0}
    await state.update_data(cart=cart)


def is_user_verified(user) -> bool:
    """Проверяет, зарегистрирован ли пользователь с подтверждённым телефоном."""
    if not user:
        return False
    return bool(user["phone"] and user["is_verified"] == 1)


# ---------- Старт и Регистрация (Задача 4) ----------

INSTRUCTION_TEXT = (
    "📌 <b>РУКОВОДСТВО И ВОЗМОЖНОСТИ БОТА «ПИВДОНЕР PRO»</b>\n"
    "<i>(Полный комплект функций для покупателя и владельца заведения)</i>\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "🍔 <b>1. ИНТЕРФЕЙС ГОСТЯ (КЛИЕНТА):</b>\n\n"
    "• <b>«🚀 Меню в Mini App»</b> — современная визуальная Web App витрина прямо внутри Telegram с фотографиями блюд, бейджами («Хит», «Острое»), ингредиентами и плавающей корзиной.\n"
    "• <b>«🍔 Меню» / «🛒 Оформить заказ»</b> — классический кнопочный каталог по разделам (Донеры, Хот-доги, Ланчбоксы, Закуски, Напитки) с <b>подробным составом ингредиентов с гриля</b>, весом и кнопками «➕ / ➖».\n"
    "• <b>«🧺 Корзина»</b> — список блюд, подсчёт суммы и чекаут.\n"
    "• <b>«🚕 Яндекс Доставка» / «🏃 Самовывоз»</b>:\n"
    "  - <i>Яндекс Доставка:</i> авто-расчёт тарифа Яндекс Go (бесплатно от 35 Br, иначе 5 Br), ввод адреса или кнопка «📍 Отправить геопозицию», трекинг времени (~35–45 мин).\n"
    "  - <i>Самовывоз:</i> выбор времени готовности.\n"
    "• <b>«👤 Личный кабинет»</b> — верифицированный телефон, баланс бонусов, статистика всех покупок.\n"
    "• <b>«📜 Мои заказы»</b> — история с детализацией (доставка курьером / самовывоз, дата, сумма).\n"
    "• <b>«🚨 Подать жалобу»</b> — быстрая связь с директором (текст и фото проблемы).\n"
    "• <b>«📍 Адрес и инфо»</b> — часы работы, координаты на карте, контакты.\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "👨‍🍳 <b>2. УПРАВЛЕНИЕ КУХНЕЙ И АДМИНИСТРАТОР:</b>\n\n"
    "• <b>Интерактивная карточка заказа:</b> «✅ Принять заказ» → «🔥 Начать готовить» → «🛍 Заказ готов!» → «🏁 Выдан гостю / Завершить».\n"
    "• <b>🖨 Печать чека на термопринтер (58/80 мм):</b> мгновенная генерация макета кухонного чека с реквизитами, составом, суммами и отправкой файла ESC/POS команд.\n"
    "• <b>📑 Выгрузка в Excel (.xlsx):</b> скачивание красивой таблицы со всеми заказами, выручкой, адресами и формулами.\n"
    "• <b>📢 Таргетированная рассылка:</b> отправка акций и спецпредложений с фото и текстом всем гостям.\n"
    "• <b>🔍 Поиск по номеру телефона:</b> полная история заказов любого клиента.\n"
    "• <b>📊 Отчёт за смену:</b> кассовый отчёт по выручке, числу заказов и топ-блюдам.\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "⭐ <b>3. РЕПУТАЦИЯ И ОТЗЫВЫ (NPS):</b>\n"
    "• После выдачи/доставки бот автоматически спрашивает оценку 1–5 ⭐:\n"
    "  - При <b>4-5 ⭐</b> — мотивирует оставить отзыв на <b>Яндекс Картах</b> с начислением <b>+2.00 Br бонусов</b>.\n"
    "  - При <b>1-3 ⭐</b> — перехватывает негатив и моментально пересылает жалобу директору для урегулирования.\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "🚕 <b>4. СИМУЛЯЦИЯ ЯНДЕКС ДОСТАВКИ:</b>\n"
    "Полный цикл: поиск курьера → назначение (авто, госномер, рейтинг) → прибытие в кафе → еда в термосумке → вручение у подъезда.\n\n"
    "👇 <i>Сообщение закреплено вверху чата. Нажмите кнопки ниже для проверки всех функций!</i>"
)


async def send_and_pin_instruction(chat_id: int, bot: Bot, reply_markup=None):
    """Отправляет подробную инструкцию покупателя/администратора и закрепляет её в чате."""
    markup = reply_markup or kb.admin_kb()
    msg = await bot.send_message(chat_id, INSTRUCTION_TEXT, reply_markup=markup)
    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
    except Exception as e:
        logging.warning("Could not pin instruction message in chat %s: %s", chat_id, e)
    return msg


async def send_main_greeting(message: Message, name: str, bot: Bot = None):
    """Главное приветствие для зарегистрированного пользователя."""
    b = bot or message.bot
    demo_note = (
        "\n\n<b>🧪 Включен Демо-режим:</b>\n"
        "Заказ после оформления придёт прямо вам в этот же чат с кнопками повара/администратора для принятия и управления!"
        if DEMO_MODE else ""
    )
    await message.answer(
        f"👋 Привет, {name}!\n\n"
        f"Это <b>{CAFE['name']}</b> — донеры, ланчбоксы и хот-доги без очереди и ожидания.\n\n"
        "🛒 Сделай предзаказ — и к твоему приезду всё будет готово.\n"
        "🕐 Забери к выбранному времени по адресу:\n"
        f"📍 {CAFE['address']}\n"
        f"📞 {CAFE['phone']}"
        + demo_note,
        reply_markup=kb.main_menu(),
    )
    await message.answer("Быстрые действия:", reply_markup=kb.quick_actions_kb())
    if DEMO_MODE:
        await send_and_pin_instruction(message.chat.id, b)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await state.set_state(OrderForm.browsing)

    # Обработка реферальной ссылки: /start ref_123456
    text_parts = (message.text or "").split()
    if len(text_parts) > 1 and text_parts[1].startswith("ref_"):
        try:
            referrer_id = int(text_parts[1].replace("ref_", ""))
            applied = await set_referrer(message.from_user.id, referrer_id)
            if applied:
                await message.answer("🎁 <b>Вам начислен приветственный бонус +2.00 Br по приглашению друга!</b>")
                try:
                    await bot.send_message(
                        referrer_id,
                        "🎉 <b>По вашей ссылке зарегистрировался новый друг!</b>\n"
                        "После его первого заказа вы получите ещё <b>+2.00 Br бонусов</b>!"
                    )
                except Exception:
                    pass
        except Exception:
            pass

    user = await get_user(message.from_user.id)
    if not user:
        await upsert_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            is_verified=0,
        )
        user = await get_user(message.from_user.id)

    name = user["name"] or message.from_user.first_name or "Гость"

    # Проверяем подтверждение телефона гостя
    if not is_user_verified(user):
        await state.set_state(RegistrationForm.waiting_for_phone)
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            f"👋 Привет, {name}!\n\n"
            f"Добро пожаловать в кафе <b>«{CAFE['name']}»</b>.\n\n"
            "🔐 <b>Регистрация гостя:</b>\n"
            "Перед использованием бота и оформлением заказов необходимо подтвердить свой номер телефона.\n"
            "Это подтверждает, что вы реальный человек, и защищает кафе от ложных заказов.\n\n"
            "Нажмите кнопку <b>«📱 Подтвердить номер через Telegram»</b> ниже или введите номер сообщением (например, <code>+375 29 123-45-67</code>):",
            reply_markup=kb.phone_request_kb(),
        )
        return

    await send_main_greeting(message, name)


@router.callback_query(F.data == "start_reg")
async def cb_start_reg(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await delete(cb.message)
    await state.set_state(RegistrationForm.waiting_for_phone)
    await send_step_msg(
        state,
        bot,
        cb.message.chat.id,
        "🔐 <b>Подтверждение номера телефона:</b>\n\n"
        "Нажмите кнопку <b>«📱 Подтвердить номер через Telegram»</b> ниже или введите номер сообщением (например, <code>+375 29 123-45-67</code>):",
        reply_markup=kb.phone_request_kb(),
    )
    await cb.answer()


@router.message(RegistrationForm.waiting_for_phone, F.contact)
async def reg_got_contact(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    contact = message.contact

    if contact.user_id and contact.user_id != message.from_user.id:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "❌ <b>Ошибка:</b> пожалуйста, отправьте собственный номер телефона нажатием кнопки «📱 Подтвердить номер через Telegram» ниже.",
            reply_markup=kb.phone_request_kb(),
        )
        return

    _, phone, _ = validate_phone(contact.phone_number)
    phone = phone or contact.phone_number

    await state.update_data(reg_phone=phone)
    await state.set_state(RegistrationForm.waiting_for_name)

    await send_step_msg(
        state,
        bot,
        message.chat.id,
        f"✅ Номер <b>{phone}</b> успешно подтверждён через Telegram!\n\n"
        "Как к вам обращаться? (Напишите ваше имя для заказов):",
        reply_markup=kb.cancel_reply_kb(),
    )


@router.message(RegistrationForm.waiting_for_phone, F.text)
async def reg_got_phone_text(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cleanup_step_msg(state, bot, message.chat.id)
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await message.answer("Регистрация отменена. Вы можете посмотреть меню:", reply_markup=kb.main_menu())
        return

    valid, phone, err = validate_phone(message.text)
    if not valid:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            f"❌ <b>Некорректный номер телефона!</b>\n\n{err}\n\n"
            "Пожалуйста, введите реальный номер (например, <code>+375 29 123-45-67</code>) или нажмите кнопку <b>«📱 Подтвердить номер через Telegram»</b> ниже:",
            reply_markup=kb.phone_request_kb(),
        )
        return

    # Генерация 4-значного проверочного SMS-кода через Телеграм (Задача 4)
    sms_code = f"{random.randint(1000, 9999)}"
    await state.update_data(reg_phone=phone, reg_sms_code=sms_code)
    await state.set_state(RegistrationForm.waiting_for_sms_code)

    await send_step_msg(
        state,
        bot,
        message.chat.id,
        f"📩 <b>Код подтверждения (SMS в Telegram):</b> <code>{sms_code}</code>\n\n"
        f"Для номера: <b>{phone}</b>\n"
        "Подтвердите, что вы реальный человек — введите этот 4-значный проверочный код в чат:",
        reply_markup=kb.cancel_reply_kb(),
    )


@router.message(RegistrationForm.waiting_for_sms_code, F.text)
async def reg_got_sms_code(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cleanup_step_msg(state, bot, message.chat.id)
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await message.answer("Регистрация отменена.", reply_markup=kb.main_menu())
        return

    data = await state.get_data()
    expected = data.get("reg_sms_code")
    phone = data.get("reg_phone")
    entered = message.text.strip()

    if entered != expected:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            f"❌ <b>Неверный проверочный код!</b>\n\n"
            f"Ожидался код: <code>{expected}</code>\n"
            "Введите правильный код из сообщения выше или отправьте «❌ Отмена»:",
            reply_markup=kb.cancel_reply_kb(),
        )
        return

    # Код подтверждён
    await state.set_state(RegistrationForm.waiting_for_name)
    await send_step_msg(
        state,
        bot,
        message.chat.id,
        f"✅ <b>Код подтверждён!</b> Номер <b>{phone}</b> успешно верифицирован.\n\n"
        "Как к вам обращаться? (Напишите ваше имя для заказов):",
        reply_markup=kb.cancel_reply_kb(),
    )


@router.message(RegistrationForm.waiting_for_name, F.text)
async def reg_got_name(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cleanup_step_msg(state, bot, message.chat.id)
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await message.answer("Регистрация отменена.", reply_markup=kb.main_menu())
        return

    name = message.text.strip()
    if len(name) < 2 or len(name) > 40:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "Имя должно быть длиной от 2 до 40 символов. Напишите ваше имя:",
            reply_markup=kb.cancel_reply_kb(),
        )
        return

    data = await state.get_data()
    phone = data.get("reg_phone")

    await upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        name=name,
        phone=phone,
        is_verified=1,
    )

    await cleanup_step_msg(state, bot, message.chat.id)
    cart = data.get("cart", {})
    await state.clear()
    if cart:
        await state.update_data(cart=cart)
    await state.set_state(OrderForm.browsing)

    await message.answer(
        f"🎉 <b>Регистрация успешно завершена!</b>\n\n"
        f"👤 Гость: <b>{name}</b>\n"
        f"📱 Подтверждённый телефон: <b>{phone}</b> ✅\n\n"
        "Теперь вам доступен полный функционал: оформление предзаказов, бонусы и личный кабинет.",
        reply_markup=kb.main_menu(),
    )
    await message.answer("Быстрые действия:", reply_markup=kb.quick_actions_kb())
    if DEMO_MODE:
        await send_and_pin_instruction(message.chat.id, bot)


# ---------- Личный кабинет гостя (Задача 4) ----------

async def show_profile(chat_id: int, user_id: int, bot: Bot, state: FSMContext = None):
    user = await get_user(user_id)
    if not user:
        user = {"name": "Гость", "phone": None, "bonus": 0, "is_verified": 0}

    orders_cnt, total_spent = await get_user_stats(user_id)
    recent_orders = await get_user_orders(user_id, limit=3)
    ref_cnt, ref_earned = await get_user_referral_stats(user_id)

    verified = is_user_verified(user)
    verified_status = "✅ <b>Подтверждён</b>" if verified else "⚠️ <b>Не подтверждён</b>"
    phone_display = user["phone"] or "Не указан"
    name_display = user["name"] or "Гость"
    bonus_display = f"{user['bonus']:.0f} Br"

    text = (
        f"👤 <b>Личный кабинет гостя</b>\n\n"
        f"👤 Имя: <b>{name_display}</b>\n"
        f"📱 Телефон: <b>{phone_display}</b> ({verified_status})\n"
        f"🎁 Бонусы: <b>{bonus_display}</b>\n"
        f"👥 Приглашено друзей: <b>{ref_cnt}</b> (+{ref_earned:.2f} Br)\n\n"
        f"📦 Оформлено заказов: <b>{orders_cnt}</b>\n"
        f"💰 На сумму: <b>{total_spent:.2f} Br</b>\n"
    )

    if recent_orders:
        text += "\n📋 <b>Последние заказы:</b>\n"
        for o in recent_orders:
            dt = o["created_at"][:16].replace("T", " ")
            st = STATUS_TEXT.get(o["status"], o["status"])
            text += f"• №{o['id']} · {dt} · {o['total']:.2f} Br · {st}\n"

    markup = kb.profile_kb(is_verified=verified)
    if state:
        await send_step_msg(state, bot, chat_id, text, reply_markup=markup)
    else:
        await bot.send_message(chat_id, text, reply_markup=markup)


@router.message(F.text.in_({"👤 Личный кабинет", "👤 Мой профиль", "/profile"}))
async def my_profile_msg(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    await show_profile(message.chat.id, message.from_user.id, bot, state)


@router.callback_query(F.data.in_({"quick_profile", "profile"}))
async def cb_profile(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await delete(cb.message)
    await show_profile(cb.message.chat.id, cb.from_user.id, bot, state)
    await cb.answer()


@router.callback_query(F.data == "profile_edit_name")
async def cb_edit_name(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await delete(cb.message)
    await state.set_state(ProfileEditForm.waiting_for_name)
    await send_step_msg(
        state,
        bot,
        cb.message.chat.id,
        "✏️ Напишите новое имя для заказов:",
        reply_markup=kb.cancel_reply_kb(),
    )
    await cb.answer()


@router.message(ProfileEditForm.waiting_for_name, F.text)
async def profile_got_new_name(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cleanup_step_msg(state, bot, message.chat.id)
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await show_profile(message.chat.id, message.from_user.id, bot, state)
        return

    new_name = message.text.strip()
    if len(new_name) < 2 or len(new_name) > 40:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "Имя должно быть длиной от 2 до 40 символов. Введите имя:",
            reply_markup=kb.cancel_reply_kb(),
        )
        return

    await update_user_name(message.from_user.id, new_name)
    await cleanup_step_msg(state, bot, message.chat.id)
    await state.clear()
    await state.set_state(OrderForm.browsing)
    await message.answer("✅ Имя успешно обновлено!", reply_markup=kb.main_menu())
    await show_profile(message.chat.id, message.from_user.id, bot, state)


@router.callback_query(F.data == "profile_edit_phone")
async def cb_edit_phone(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await delete(cb.message)
    await state.set_state(ProfileEditForm.waiting_for_phone)
    await send_step_msg(
        state,
        bot,
        cb.message.chat.id,
        "📱 <b>Смена номера телефона:</b>\n\n"
        "Для смены номера потребуется подтверждение.\n"
        "Нажмите кнопку ниже или отправьте новый номер сообщением:",
        reply_markup=kb.phone_request_kb(),
    )
    await cb.answer()


@router.message(ProfileEditForm.waiting_for_phone, F.contact)
async def profile_edit_got_contact(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    contact = message.contact
    if contact.user_id and contact.user_id != message.from_user.id:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "❌ Отправьте именно свой номер нажатием кнопки ниже.",
            reply_markup=kb.phone_request_kb(),
        )
        return

    _, phone, _ = validate_phone(contact.phone_number)
    phone = phone or contact.phone_number
    await update_user_phone(message.from_user.id, phone, is_verified=1)

    await cleanup_step_msg(state, bot, message.chat.id)
    await state.clear()
    await state.set_state(OrderForm.browsing)
    await message.answer(f"✅ Номер успешно изменён на <b>{phone}</b>!", reply_markup=kb.main_menu())
    await show_profile(message.chat.id, message.from_user.id, bot, state)


@router.message(ProfileEditForm.waiting_for_phone, F.text)
async def profile_edit_got_phone_text(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cleanup_step_msg(state, bot, message.chat.id)
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await show_profile(message.chat.id, message.from_user.id, bot, state)
        return

    valid, phone, err = validate_phone(message.text)
    if not valid:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            f"❌ <b>Некорректный номер телефона!</b>\n\n{err}\n\nПопробуйте ещё раз или нажмите «📱 Подтвердить номер через Telegram»:",
            reply_markup=kb.phone_request_kb(),
        )
        return

    sms_code = f"{random.randint(1000, 9999)}"
    await state.update_data(edit_phone=phone, edit_sms_code=sms_code)
    await state.set_state(ProfileEditForm.waiting_for_sms_code)

    await send_step_msg(
        state,
        bot,
        message.chat.id,
        f"📩 <b>Код подтверждения (SMS в Telegram):</b> <code>{sms_code}</code>\n\n"
        f"Для подтверждения нового номера <b>{phone}</b> введите этот 4-значный код:",
        reply_markup=kb.cancel_reply_kb(),
    )


@router.message(ProfileEditForm.waiting_for_sms_code, F.text)
async def profile_edit_got_sms_code(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cleanup_step_msg(state, bot, message.chat.id)
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await show_profile(message.chat.id, message.from_user.id, bot, state)
        return

    data = await state.get_data()
    expected = data.get("edit_sms_code")
    phone = data.get("edit_phone")

    if message.text.strip() != expected:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            f"❌ Неверный код! Введите <code>{expected}</code> или отправьте «❌ Отмена»:",
            reply_markup=kb.cancel_reply_kb(),
        )
        return

    await update_user_phone(message.from_user.id, phone, is_verified=1)
    await cleanup_step_msg(state, bot, message.chat.id)
    await state.clear()
    await state.set_state(OrderForm.browsing)
    await message.answer(f"✅ Номер телефона обновлён и подтверждён: <b>{phone}</b>!", reply_markup=kb.main_menu())
    await show_profile(message.chat.id, message.from_user.id, bot, state)


# ---------- Реферальная программа («Пригласи друга») ----------

async def _send_referral_info(chat_id: int, user_id: int, bot: Bot, edit_message=None):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    ref_count, earned = await get_user_referral_stats(user_id)

    text = (
        "🎁 <b>Программа «Пригласи друга» — кафе «ПивДонер»</b>\n\n"
        "Приглашайте друзей и получайте <b>+2.00 Br бонусов</b> на баланс за каждого нового гостя!\n\n"
        f"🔗 <b>Ваша персональная реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "Отправьте эту ссылку друзьям в Telegram или соцсетях.\n\n"
        f"👥 Приглашено друзей: <b>{ref_count}</b>\n"
        f"💰 Начислено бонусов: <b>{earned:.2f} Br</b>\n\n"
        "<i>Бонусы можно списывать для оплаты любых блюд и напитков!</i>"
    )
    if edit_message:
        await edit_message.edit_text(text, reply_markup=kb.profile_kb())
    else:
        await bot.send_message(chat_id, text, reply_markup=kb.profile_kb())


@router.message(F.text.in_({"🎁 Пригласи друга (+2 Br)", "🎁 Реферальная ссылка", "/ref", "/referral"}))
async def msg_referral_link(message: Message, bot: Bot):
    await delete(message)
    await _send_referral_info(message.chat.id, message.from_user.id, bot)


@router.callback_query(F.data == "referral_link")
async def cb_referral_link(cb: CallbackQuery, bot: Bot):
    await _send_referral_info(cb.message.chat.id, cb.from_user.id, bot, edit_message=cb.message)
    await cb.answer()


# ---------- История заказов и Инфо ----------

@router.message(F.text.in_({"📜 Мои заказы", "📜 История заказов", "/history", "/orders"}))
async def order_history_msg(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    await show_history(message.chat.id, message.from_user.id, bot, state)


@router.callback_query(F.data.in_({"quick_history", "history"}))
async def cb_history(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await delete(cb.message)
    await show_history(cb.message.chat.id, cb.from_user.id, bot, state)
    await cb.answer()


async def show_history(chat_id: int, user_id: int, bot: Bot, state: FSMContext = None):
    orders = await get_user_orders(user_id, limit=10)
    if not orders:
        text = "📜 <b>История заказов:</b>\n\nУ вас пока нет заказов. Выберите что-нибудь вкусное в меню!"
    else:
        text = "📜 <b>История ваших заказов:</b>\n\n"
        for o in orders:
            dt = o["created_at"][:16].replace("T", " ")
            st = STATUS_TEXT.get(o["status"], o["status"])
            pay = PAYMENT_TEXT.get(o["payment"], o["payment"])
            deliv = "🚕 Яндекс Доставка" if o.get("delivery_type") == "yandex" else "🏃 Самовывоз"
            text += f"№{o['id']} · {dt} · <b>{o['total']:.2f} Br</b> ({deliv})\n  {o['items']}\n  📊 {st} · {pay}\n\n"

    kb_markup = kb.categories_kb()
    if state:
        await send_step_msg(state, bot, chat_id, text, reply_markup=kb_markup)
    else:
        await bot.send_message(chat_id, text, reply_markup=kb_markup)


@router.message(F.text.in_({"📍 Адрес и инфо", "📍 Адрес и время работы", "/info", "/help"}))
async def cafe_info_msg(message: Message):
    await message.answer(
        f"📍 <b>{CAFE['name']}</b>\n"
        f"Адрес: {CAFE['address']}\n\n"
        f"🕐 Время работы: ежедневно {CAFE['hours']}\n"
        f"📞 Телефон: {CAFE['phone']}\n\n"
        "Сделайте заказ в боте к нужному времени — заберите горячим и без очереди!",
        reply_markup=kb.info_kb(),
    )


# ---------- Подача жалобы администратору ----------

@router.message(F.text.in_({"🚨 Подать жалобу", "🚨 Подать жалобу администратору", "Подать жалобу", "Жалоба", "/complaint"}))
async def start_complaint_msg(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    await start_complaint_flow(message.chat.id, message.from_user.id, state, bot)


@router.callback_query(F.data == "make_complaint")
async def cb_start_complaint(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await delete(cb.message)
    await start_complaint_flow(cb.message.chat.id, cb.from_user.id, state, bot)
    await cb.answer()


async def start_complaint_flow(chat_id: int, user_id: int, state: FSMContext, bot: Bot):
    await state.set_state(ComplaintForm.waiting_for_text)
    await send_step_msg(
        state,
        bot,
        chat_id,
        "🚨 <b>Подача жалобы или обращения администратору</b>\n\n"
        "Пожалуйста, опишите вашу проблему, замечание по блюду/сервису или пожелание.\n"
        "Руководство кафе обязательно прочитает ваше обращение и свяжется с вами.\n\n"
        "✍️ <b>Напишите текст вашей жалобы</b> (можно прикрепить фото или отправить «❌ Отмена»):",
        reply_markup=kb.cancel_reply_kb(),
    )


@router.message(ComplaintForm.waiting_for_text, F.text)
async def got_complaint_text(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cleanup_step_msg(state, bot, message.chat.id)
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await message.answer("Подача жалобы отменена.", reply_markup=kb.main_menu())
        return

    text = message.text.strip()
    if len(text) < 5:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "Текст жалобы слишком короткий. Пожалуйста, опишите подробнее (минимум 5 символов):",
            reply_markup=kb.cancel_reply_kb(),
        )
        return

    await _process_and_send_complaint(message, state, bot, text)


@router.message(ComplaintForm.waiting_for_text, F.photo)
async def got_complaint_photo(message: Message, state: FSMContext, bot: Bot):
    caption = message.caption.strip() if message.caption else "Фото к жалобе без текста"
    photo_id = message.photo[-1].file_id
    await delete(message)
    await _process_and_send_complaint(message, state, bot, caption, photo_id=photo_id)


async def _process_and_send_complaint(message: Message, state: FSMContext, bot: Bot, text: str, photo_id: str = None):
    user = await get_user(message.from_user.id)
    name = user["name"] if user and user["name"] else (message.from_user.first_name or "Гость")
    phone = user["phone"] if user and user["phone"] else "Не указан"
    username_str = f"@{message.from_user.username}" if message.from_user.username else "нет username"

    complaint_id = await create_complaint(
        user_id=message.from_user.id,
        username=message.from_user.username,
        name=name,
        phone=phone,
        text=text,
    )

    await cleanup_step_msg(state, bot, message.chat.id)
    await state.clear()
    await state.set_state(OrderForm.browsing)

    # 1. Подтверждение гостю
    await message.answer(
        f"✅ <b>Жалоба №{complaint_id} успешно передана администратору!</b>\n\n"
        f"Администрация кафе «ПивДонер» обязательно рассмотрит обращение и свяжется с вами по телефону ({phone}) или в Telegram.\n\n"
        "Спасибо за обратную связь — это помогает нам делать наш сервис и кухню лучше!",
        reply_markup=kb.main_menu(),
    )

    # 2. Уведомление администратору (в демо-режиме приходит сюда же)
    admin_chat = message.from_user.id if DEMO_MODE else MANAGER_CHAT_ID
    admin_text = (
        f"🚨 <b>НОВОЕ ОБРАЩЕНИЕ / ЖАЛОБА №{complaint_id}</b>\n\n"
        f"👤 Гость: <b>{name}</b> ({username_str})\n"
        f"📱 Телефон: <b>{phone}</b>\n"
        f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📝 <b>Текст обращения:</b>\n<i>{text}</i>"
    )
    if DEMO_MODE:
        admin_text = "🧪 <b>Уведомление для администратора (ты видишь жалобу):</b>\n\n" + admin_text

    try:
        if photo_id:
            await bot.send_photo(admin_chat, photo=photo_id, caption=admin_text)
        else:
            await bot.send_message(admin_chat, admin_text)
    except Exception as e:
        logging.exception("Failed to send complaint %s to admin chat: %s", complaint_id, e)


# ---------- Мини-игра «Кубик» ----------

@router.message(F.text.in_({"🎲 Игра с бонусами", "🎲 Игра «Кубик»", "🎮 Мини-игра", "/game"}))
async def mini_game_msg(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    user = await get_user(message.from_user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    if user and user["last_bonus_game"] == today:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "Ты уже играл сегодня. Возвращайся завтра — кубик ждёт! 🎲",
        )
        return

    await send_step_msg(
        state,
        bot,
        message.chat.id,
        "🎲 <b>Игра «Кубик»</b>\n\n"
        "Бросай кубик — выиграй бонусы к следующему заказу!\n"
        "1–3 → +1 бонус · 4–5 → +2 · 6 → +5 бонусов\n\n"
        "Одна игра в день.",
        reply_markup=kb.dice_kb(),
    )


@router.callback_query(F.data == "dice_menu")
async def cb_dice_menu(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await delete(cb.message)
    await mini_game_msg(cb.message, state, bot)
    await cb.answer()


@router.callback_query(F.data == "dice")
async def cb_dice(cb: CallbackQuery, bot: Bot):
    user = await get_user(cb.from_user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    if user and user["last_bonus_game"] == today:
        await cb.answer("Сегодня уже играл!", show_alert=True)
        return

    msg = await cb.message.answer_dice(emoji="🎲")
    await asyncio.sleep(4)
    val = msg.dice.value
    bonus = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 5}[val]
    await add_bonus(cb.from_user.id, bonus)
    await set_last_bonus_game(cb.from_user.id, today)

    cur_bonus = (user["bonus"] if user else 0) + bonus
    await cb.message.edit_text(
        f"🎲 Выпало <b>{val}</b> → <b>+{bonus} бонусов!</b>\n\n"
        f"Твой баланс: <b>{cur_bonus:.0f} Br</b>\n"
        "Приходи завтра за новой порцией бонусов!",
        reply_markup=None,
    )
    await cb.answer(f"+{bonus} бонусов!")


# ---------- Меню и Корзина (Задача 5: Состав шаурмы) ----------

@router.message(F.text.in_({"🍔 Меню", "/menu"}))
async def show_menu_msg(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    await send_step_msg(
        state,
        bot,
        message.chat.id,
        "🍔 <b>Меню кафе «ПивДонер»</b>\n\nВыберите категорию для просмотра состава и выбора блюд:",
        reply_markup=kb.categories_kb(),
    )


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery):
    await cb.message.edit_text(
        "🍔 <b>Меню кафе «ПивДонер»</b>\n\nВыберите категорию для просмотра состава и выбора блюд:",
        reply_markup=kb.categories_kb(),
    )
    await cb.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(cb: CallbackQuery, state: FSMContext):
    cat = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    await cb.message.edit_text(
        f"<b>{cat}</b>\n\n"
        "Нажмите на позицию, чтобы посмотреть подробный состав, граммовку и добавить в корзину:",
        reply_markup=kb.items_kb(cat, cart),
    )
    await cb.answer()


def make_item_card_text(item_id: str, qty: int) -> str:
    item = ITEMS[item_id]
    category = item.get("category", "")
    icon = "🌯" if "Донер" in category else ("🍟" if "Ланч" in category else "🌭")

    text = f"{icon} <b>{item['name']}</b> — <b>{fmt_price(item['price'])}</b>\n\n"
    if item.get("desc"):
        text += f"📋 <b>Состав:</b>\n{item['desc']}\n\n"
    if item.get("weight"):
        text += f"⚖️ <b>Вес порции:</b> {item['weight']}\n\n"

    text += f"🛒 В вашей корзине: <b>{qty} шт.</b>\n\nВыберите количество:"
    return text


@router.callback_query(F.data.startswith("item:"))
async def cb_item(cb: CallbackQuery, state: FSMContext):
    item_id = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    qty = cart.get(item_id, 0)
    text = make_item_card_text(item_id, qty)
    await cb.message.edit_text(text, reply_markup=kb.item_kb(item_id, qty))
    await cb.answer()


@router.callback_query(F.data.startswith("inc:"))
async def cb_inc(cb: CallbackQuery, state: FSMContext):
    item_id = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    cart[item_id] = cart.get(item_id, 0) + 1
    await save_cart(state, cart)
    qty = cart[item_id]
    text = make_item_card_text(item_id, qty)
    await cb.message.edit_text(text, reply_markup=kb.item_kb(item_id, qty))
    await cb.answer(f"+1 {ITEMS[item_id]['name']}")


@router.callback_query(F.data.startswith("dec:"))
async def cb_dec(cb: CallbackQuery, state: FSMContext):
    item_id = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    if cart.get(item_id, 0) > 0:
        cart[item_id] -= 1
    await save_cart(state, cart)
    qty = cart.get(item_id, 0)
    text = make_item_card_text(item_id, qty)
    await cb.message.edit_text(text, reply_markup=kb.item_kb(item_id, qty))
    await cb.answer()


async def _render_cart_view(target, state: FSMContext, edit=False, bot: Bot = None, chat_id: int = None):
    cart = await get_cart(state)
    if not cart:
        text = "🧺 <b>Корзина пуста.</b>\n\nЗагляните в меню и выберите блюда!"
        markup = kb.empty_cart_kb()
    else:
        body, _ = cart_text(cart)
        text = f"🧺 <b>Ваш заказ:</b>\n\n{body}"
        markup = kb.cart_kb(cart)

    if edit:
        await target.message.edit_text(text, reply_markup=markup)
    else:
        await send_step_msg(state, bot, chat_id, text, reply_markup=markup)


@router.message(F.text.in_({"🧺 Корзина", "/cart"}))
async def show_cart_msg(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    await _render_cart_view(None, state, edit=False, bot=bot, chat_id=message.chat.id)


@router.callback_query(F.data == "cart")
async def cb_cart(cb: CallbackQuery, state: FSMContext):
    await _render_cart_view(cb, state, edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("cinc:"))
async def cb_cart_inc(cb: CallbackQuery, state: FSMContext):
    iid = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    cart[iid] = cart.get(iid, 0) + 1
    await save_cart(state, cart)
    await _render_cart_view(cb, state, edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("cdec:"))
async def cb_cart_dec(cb: CallbackQuery, state: FSMContext):
    iid = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    if cart.get(iid, 0) > 1:
        cart[iid] -= 1
    else:
        cart.pop(iid, None)
    await save_cart(state, cart)
    await _render_cart_view(cb, state, edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("cdel:"))
async def cb_cart_del(cb: CallbackQuery, state: FSMContext):
    iid = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    cart.pop(iid, None)
    await save_cart(state, cart)
    await _render_cart_view(cb, state, edit=True)
    await cb.answer()


@router.callback_query(F.data == "clear_cart")
async def cb_clear(cb: CallbackQuery, state: FSMContext):
    await save_cart(state, {})
    await _render_cart_view(cb, state, edit=True)
    await cb.answer("Корзина очищена")


# ---------- Оформление заказа (Задачи 1, 2, 3, 4) ----------

@router.message(F.text.in_({"🛒 Оформить заказ", "🛒 Оформить предзаказ", "/order"}))
async def start_order_msg(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    cart = await get_cart(state)
    if not cart:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "🧺 Корзина пуста. Сначала добавьте блюда из меню:",
            reply_markup=kb.categories_kb(),
        )
        return
    await proceed_to_checkout(message.chat.id, message.from_user.id, state, bot)


@router.callback_query(F.data.in_({"checkout", "quick_order"}))
async def cb_checkout(cb: CallbackQuery, state: FSMContext, bot: Bot):
    cart = await get_cart(state)
    if not cart:
        await delete(cb.message)
        await send_step_msg(
            state,
            bot,
            cb.message.chat.id,
            "🧺 В корзине пока ничего нет. Выберите позиции в меню:",
            reply_markup=kb.categories_kb(),
        )
        await cb.answer()
        return

    await delete(cb.message)
    await proceed_to_checkout(cb.message.chat.id, cb.from_user.id, state, bot)
    await cb.answer()


async def proceed_to_checkout(chat_id: int, user_id: int, state: FSMContext, bot: Bot):
    """Начало чистого оформления заказа с проверкой верификации гостя и выбором доставки."""
    user = await get_user(user_id)

    # Задача 4: Проверяем, зарегистрирован ли гость
    if not is_user_verified(user):
        await state.set_state(RegistrationForm.waiting_for_phone)
        await send_step_msg(
            state,
            bot,
            chat_id,
            "🔐 <b>Для оформления заказа необходимо подтвердить номер телефона.</b>\n\n"
            "Это подтверждает, что вы реальный человек, и защищает кафе от ложных заказов.\n\n"
            "Нажмите кнопку <b>«📱 Подтвердить номер через Telegram»</b> ниже или введите номер сообщением:",
            reply_markup=kb.phone_request_kb(),
        )
        return

    # Пользователь подтверждён — используем данные из его профиля
    await state.update_data(name=user["name"], phone=user["phone"])
    await state.set_state(OrderForm.delivery_choice)

    # Задача 1: Чистое окно без лишнего текста + выбор доставки
    await send_step_msg(
        state,
        bot,
        chat_id,
        f"👤 Гость: <b>{user['name']}</b>\n"
        f"📱 Телефон: <b>{user['phone']}</b> ✅\n\n"
        "📦 <b>Выберите способ получения заказа:</b>\n\n"
        "🚕 <b>Яндекс Доставка:</b> курьер Yandex Go доставит заказ горячим прямо к вам по Минску.\n"
        f"🏃 <b>Самовывоз:</b> приготовим к вашему приходу по адресу {CAFE['address']}.",
        reply_markup=kb.delivery_choice_kb(),
    )


@router.callback_query(OrderForm.delivery_choice, F.data.startswith("deliv:"))
async def cb_delivery_choice(cb: CallbackQuery, state: FSMContext, bot: Bot):
    kind = cb.data.split(":", 1)[1]
    await delete(cb.message)

    if kind == "pickup":
        await state.update_data(delivery_type="pickup", delivery_address="", delivery_cost=0.0)
        await state.set_state(OrderForm.pickup_time)
        await send_step_msg(
            state,
            bot,
            cb.message.chat.id,
            "🕐 <b>Когда вы заберёте заказ?</b>\n"
            "Выберите удобное время самовывоза:",
            reply_markup=kb.pickup_time_kb(),
        )
    else:
        await state.update_data(delivery_type="yandex")
        await state.set_state(OrderForm.address)
        await send_step_msg(
            state,
            bot,
            cb.message.chat.id,
            "📍 <b>Укажите адрес доставки в Минске:</b>\n\n"
            "Напишите улицу, номер дома, подъезд и этаж (например: <i>ул. Притыцкого, 83, п. 2, кв. 45</i>)\n"
            "или нажмите кнопку <b>«📍 Отправить геопозицию»</b> ниже:",
            reply_markup=kb.address_request_kb(),
        )
    await cb.answer()


@router.message(OrderForm.address, F.location)
async def got_address_location(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    lat = message.location.latitude
    lon = message.location.longitude
    addr_str = f"Геолокация Минск ({lat:.4f}, {lon:.4f})"
    await _process_delivery_address(message.chat.id, addr_str, state, bot)


@router.message(OrderForm.address, F.text)
async def got_address_text(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cancel_order_flow(message.chat.id, state, bot)
        return
    addr_str = message.text.strip()
    if len(addr_str) < 3:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "⚠️ Адрес слишком короткий. Пожалуйста, напишите улицу и номер дома:",
            reply_markup=kb.address_request_kb(),
        )
        return
    await _process_delivery_address(message.chat.id, addr_str, state, bot)


async def _process_delivery_address(chat_id: int, addr_str: str, state: FSMContext, bot: Bot):
    data = await state.get_data()
    cart = data.get("cart", {})
    _, items_total = cart_text(cart)
    deliv_info = calculate_yandex_delivery(addr_str, items_total)

    deliv_cost = deliv_info["cost"]
    eta = deliv_info["eta_minutes"]
    time_str = f"~{eta} мин (Яндекс Go)"

    await state.update_data(
        delivery_type="yandex",
        delivery_address=addr_str,
        delivery_cost=deliv_cost,
        delivery_eta=eta,
        pickup_time=time_str,
    )
    await state.set_state(OrderForm.comment)

    cost_str = "🎉 <b>Бесплатно</b> (заказ от 35 Br)" if deliv_info["is_free"] else f"<b>{deliv_cost:.2f} Br</b>"

    await send_step_msg(
        state,
        bot,
        chat_id,
        f"🚕 <b>Тариф Яндекс Доставки рассчитан!</b>\n\n"
        f"📍 Адрес доставки: <b>{addr_str}</b>\n"
        f"🛵 Стоимость доставки: {cost_str}\n"
        f"⏱ Время доставки: <b>~{eta} мин</b> (курьер на авто)\n\n"
        "✍️ <b>Комментарий курьеру или кухне?</b>\n"
        "(Например: домофон 42, 3 этаж, без лука или напишите «-» если без пожеланий):",
        reply_markup=kb.cancel_reply_kb(),
    )


@router.callback_query(OrderForm.pickup_time, F.data.startswith("time:"))
async def cb_time(cb: CallbackQuery, state: FSMContext, bot: Bot):
    kind = cb.data.split(":", 1)[1]
    if kind == "asap":
        t = "Как можно скорее"
    elif kind == "custom":
        await delete(cb.message)
        await send_step_msg(
            state,
            bot,
            cb.message.chat.id,
            "✍️ Напишите желаемое время готовности заказа (например, 18:30):",
            reply_markup=kb.cancel_reply_kb(),
        )
        await cb.answer()
        return
    else:
        mins = int(kind)
        t = (datetime.now() + timedelta(minutes=mins)).strftime("%H:%M")

    await delete(cb.message)
    await state.update_data(pickup_time=t)
    await state.set_state(OrderForm.comment)

    # Задача 1: Убираем предыдущее окно, показываем следующее
    await send_step_msg(
        state,
        bot,
        cb.message.chat.id,
        "✍️ <b>Комментарий к заказу?</b>\n(Например: без лука, больше соуса или напишите «-» если без пожеланий):",
        reply_markup=kb.cancel_reply_kb(),
    )
    await cb.answer()


@router.message(OrderForm.pickup_time)
async def got_custom_time(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cancel_order_flow(message.chat.id, state, bot)
        return

    time_str = message.text.strip()
    await state.update_data(pickup_time=time_str)
    await state.set_state(OrderForm.comment)

    await send_step_msg(
        state,
        bot,
        message.chat.id,
        "✍️ <b>Комментарий к заказу?</b>\n(Например: без лука, больше соуса или напишите «-»):",
        reply_markup=kb.cancel_reply_kb(),
    )


@router.message(OrderForm.comment)
async def got_comment(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cancel_order_flow(message.chat.id, state, bot)
        return

    comment = "" if message.text.strip() == "-" else message.text.strip()
    await state.update_data(comment=comment)

    data = await state.get_data()
    cart = data.get("cart", {})
    body, items_total = cart_text(cart)
    deliv_type = data.get("delivery_type", "pickup")
    deliv_cost = float(data.get("delivery_cost", 0.0))
    grand_total = items_total + deliv_cost

    if deliv_type == "yandex":
        deliv_details = (
            f"🚕 Способ: <b>Яндекс Доставка (Yandex Go)</b>\n"
            f"📍 Адрес: <b>{data.get('delivery_address')}</b>\n"
            f"🛵 Стоимость доставки: <b>{deliv_cost:.2f} Br</b>\n"
            f"⏱ Расчётное время: <b>{data.get('delivery_eta', 35)} мин</b>"
        )
    else:
        deliv_details = (
            f"🏃 Способ: <b>Самовывоз</b>\n"
            f"📍 Адрес: <b>{CAFE['address']}</b>\n"
            f"🕐 Время готовности: <b>{data.get('pickup_time')}</b>"
        )

    text = (
        f"🧾 <b>Проверьте детали заказа:</b>\n\n"
        f"{body}\n"
        f"────────────────────\n"
        f"🛒 Блюда: <b>{items_total:.2f} Br</b>\n"
    )
    if deliv_type == "yandex":
        text += f"🛵 Доставка: <b>{deliv_cost:.2f} Br</b>\n"
    text += (
        f"💰 <b>Итого к оплате: {grand_total:.2f} Br</b>\n\n"
        f"👤 Гость: <b>{data.get('name')}</b>\n"
        f"📱 Телефон: <b>{data.get('phone')}</b>\n"
        f"{deliv_details}"
    )
    if comment:
        text += f"\n💬 Пожелания: <i>{comment}</i>"

    await state.update_data(grand_total=grand_total)
    await state.set_state(OrderForm.confirm)
    # Показываем карточку подтверждения
    await send_step_msg(state, bot, message.chat.id, text, reply_markup=kb.confirm_kb())


# ---------- Подтверждение и способ оплаты ----------

@router.callback_query(F.data == "confirm")
async def cb_confirm(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    cart = data.get("cart", {})
    if not cart:
        await cb.answer("Корзина пуста!", show_alert=True)
        return

    _, items_total = cart_text(cart)
    deliv_type = data.get("delivery_type", "pickup")
    deliv_cost = float(data.get("delivery_cost", 0.0))
    grand_total = data.get("grand_total", items_total + deliv_cost)

    order_id = await create_order(
        user_id=cb.from_user.id,
        username=cb.from_user.username,
        name=data["name"],
        phone=data["phone"],
        pickup_time=data["pickup_time"],
        cart=cart,
        comment=data.get("comment", ""),
        total=grand_total,
        delivery_type=deliv_type,
        delivery_address=data.get("delivery_address", ""),
        delivery_cost=deliv_cost,
    )

    pay_url = PAYMENT_URL.format(order_id=order_id, amount=f"{grand_total:.2f}")

    if deliv_type == "yandex":
        deliv_note = (
            f"🚕 Доставка: <b>Яндекс Доставка (Yandex Go)</b>\n"
            f"📍 Адрес: <b>{data.get('delivery_address')}</b>\n"
            f"⏱ Время доставки: <b>{data.get('pickup_time')}</b>\n"
        )
    else:
        deliv_note = (
            f"🕐 Время готовности: <b>{data['pickup_time']}</b>\n"
            f"📍 Забирайте: {CAFE['address']}\n"
        )

    confirmation = (
        f"✅ <b>Заказ №{order_id} сохранён!</b>\n\n"
        f"{deliv_note}"
        f"💰 К оплате: <b>{grand_total:.2f} Br</b>\n\n"
        "💳 <b>Выберите способ оплаты</b> — после выбора заказ сразу поступит на кухню:"
    )

    # Очищаем корзину и редактируем сообщение в выбор оплаты
    await save_cart(state, {})
    await state.set_state(OrderForm.browsing)
    await state.update_data(current_step_msg_id=None)

    await cb.message.edit_text(confirmation, reply_markup=kb.payment_method_kb(order_id, pay_url))
    await cb.answer("Заказ сохранён")


@router.callback_query(F.data.startswith("pay_cash:"))
async def cb_pay_cash(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":", 1)[1])
    await set_order_payment(order_id, "cash")
    delivered = await _send_order_to_group(bot, order_id, "cash", cb.from_user.id)

    status_note = (
        "Мы передали ваш заказ поварам! Уведомления о готовности («Принят», «Готовится», «Готов») будут приходить сюда."
        if delivered
        else "⚠️ Не удалось передать заказ поварам. Пожалуйста, свяжитесь с кафе напрямую."
    )

    await cb.message.edit_text(
        f"✅ <b>Заказ №{order_id} принят в обработку!</b>\n\n"
        "💵 Способ оплаты: <b>на месте при получении</b>.\n\n"
        f"{status_note}",
        reply_markup=None,
    )
    # Возвращаем панель быстрых действий (Задача 2)
    await cb.message.answer("Быстрые действия:", reply_markup=kb.main_menu())
    await cb.answer("Оплата на месте выбрана")


@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":", 1)[1])
    await set_order_payment(order_id, "online_marked")
    delivered = await _send_order_to_group(bot, order_id, "online_marked", cb.from_user.id)

    status_note = (
        "Заказ передан поварам. Администратор проверит платёж и заказ начнёт готовиться."
        if delivered
        else "⚠️ Не удалось передать заказ поварам. Пожалуйста, свяжитесь с кафе напрямую."
    )

    await cb.message.edit_text(
        f"✅ <b>Заказ №{order_id} принят в обработку!</b>\n\n"
        "💳 Вы выбрали <b>онлайн-оплату</b>.\n\n"
        f"{status_note}",
        reply_markup=None,
    )
    # Возвращаем панель быстрых действий (Задача 2)
    await cb.message.answer("Быстрые действия:", reply_markup=kb.main_menu())
    await cb.answer("Заказ отправлен поварам")


async def cancel_order_flow(chat_id: int, state: FSMContext, bot: Bot):
    await cleanup_step_msg(state, bot, chat_id)
    await state.set_state(OrderForm.browsing)
    await bot.send_message(
        chat_id,
        "❌ Оформление заказа отменено. Корзина сохранена.",
        reply_markup=kb.main_menu(),
    )


@router.callback_query(F.data == "cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await delete(cb.message)
    await cancel_order_flow(cb.message.chat.id, state, bot)
    await cb.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    await cancel_order_flow(message.chat.id, state, bot)


# ---------- Отправка заказа на кухню и авто-готовка ----------

async def _send_order_to_group(bot: Bot, order_id: int, payment: str, user_id: int = 0) -> bool:
    """Отправляет заказ в группу заведения или гостю в демо-режиме."""
    order = await get_order(order_id)
    if not order:
        logging.error("Order %s was not found before delivery", order_id)
        return False
    order = dict(order)
    order["payment"] = payment
    order["status"] = "new"

    chat = user_id if DEMO_MODE else MANAGER_CHAT_ID
    manager_text = make_order_text(order, is_demo=DEMO_MODE)
    manager_kb = kb.status_kb(order_id, status="new", payment=payment)
    try:
        sent_msg = await bot.send_message(chat, manager_text, reply_markup=manager_kb)
        await bot.send_message(chat, f"🔔 Новый заказ №{order_id} — смотри выше!")
        # Авто-перевод в «Готовится» через 2.5 мин если повар не нажал сам
        _schedule_auto_cooking(
            bot, order_id, order["user_id"], sent_msg.chat.id, sent_msg.message_id
        )

        # Если заказ через Яндекс Доставку — запускаем симуляцию курьера
        if order.get("delivery_type") == "yandex":
            asyncio.create_task(
                run_yandex_delivery_simulation(
                    bot=bot,
                    order_id=order_id,
                    user_id=order["user_id"],
                    address=order.get("delivery_address") or "ул. Притыцкого, 83",
                    admin_chat_id=sent_msg.chat.id,
                    admin_msg_id=sent_msg.message_id,
                )
            )

        return True
    except Exception:
        logging.exception("Could not deliver order %s to chat %s", order_id, chat)
        return False


AUTO_COOKING_DELAY = 150  # 2.5 минуты


def _schedule_auto_cooking(
    bot: Bot, order_id: int, user_id: int, message_chat_id: int, message_id: int
):
    """Через 2.5 минуты заказ автоматически переходит в статус «Готовится»."""
    async def _job():
        await asyncio.sleep(AUTO_COOKING_DELAY)
        order = await get_order(order_id)
        if not order:
            return
        order = dict(order)
        if order.get("status") in ("new", "accepted"):
            await set_order_status(order_id, "cooking")
            order["status"] = "cooking"
            # 1. Пуш гостю
            try:
                await bot.send_message(
                    user_id,
                    f"🔔 <b>Заказ №{order_id}</b>: 🔥 готовится поваром!\nПриготовим точно к {order['pickup_time']}."
                )
            except Exception:
                pass
            # 2. Обновление карточки заказа в чате админа / группы
            try:
                await bot.edit_message_text(
                    chat_id=message_chat_id,
                    message_id=message_id,
                    text=make_order_text(order, is_demo=DEMO_MODE),
                    reply_markup=kb.status_kb(order_id, status="cooking", payment=order.get("payment", "none")),
                )
            except Exception:
                pass

    asyncio.create_task(_job())


# ---------- Статусы (для кухни и заведения) ----------

@router.callback_query(F.data.startswith("st:"))
async def cb_status(cb: CallbackQuery, bot: Bot):
    parts = cb.data.split(":")
    if len(parts) != 3:
        await cb.answer()
        return
    order_id = int(parts[1])
    status = parts[2]
    text = STATUS_TEXT.get(status)
    if not text:
        await cb.answer()
        return

    await set_order_status(order_id, status)
    order = await get_order(order_id)
    if not order:
        await cb.answer()
        return
    order = dict(order)
    order["status"] = status

    try:
        new_text = make_order_text(order, is_demo=DEMO_MODE)
        new_kb = kb.status_kb(order_id, status=status, payment=order.get("payment", "none"))
        await cb.message.edit_text(new_text, reply_markup=new_kb)
    except Exception:
        logging.exception("Could not update order card %s after status change", order_id)

    await cb.answer(f"Статус: {text}")

    is_yandex = order.get("delivery_type") == "yandex"
    ready_text = (
        f"🔔 <b>Заказ №{order_id}</b>: 🛍 собран на кухне! Передаём курьеру Яндекс Go."
        if is_yandex
        else f"🔔 <b>Заказ №{order_id}</b>: 🛍 ГОТОВ к выдаче!\nЖдём вас на стойке кафе «ПивДонер» ({CAFE['address']})."
    )
    completed_text = (
        f"❤️ <b>Заказ №{order_id} доставлен курьером!</b>\nПриятного аппетита! Ждём вас снова в «ПивДонер»!"
        if is_yandex
        else f"❤️ <b>Заказ №{order_id} выдан!</b>\nПриятного аппетита! Ждём вас снова в «ПивДонер»!"
    )

    guest_msg = {
        "accepted": f"🔔 <b>Заказ №{order_id}</b>: ✅ принят в работу!\nСкоро повара начнут приготовление.",
        "cooking": f"🔔 <b>Заказ №{order_id}</b>: 🔥 готовится поваром!\nПриготовим точно к {order.get('pickup_time', 'скоро')}.",
        "ready": ready_text,
        "completed": completed_text,
        "cancelled": f"❌ <b>Заказ №{order_id} отменён заведением.</b>",
    }.get(status)

    if guest_msg and order.get("user_id"):
        try:
            await bot.send_message(order["user_id"], guest_msg)
        except Exception:
            pass

    if status == "completed" and order.get("user_id"):
        schedule_order_review(bot, order_id, order["user_id"], delay_sec=10)


@router.callback_query(F.data.startswith("payok:"))
async def cb_payok(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":", 1)[1])
    await set_order_payment(order_id, "paid")
    order = await get_order(order_id)
    if not order:
        await cb.answer()
        return
    order = dict(order)
    order["payment"] = "paid"

    try:
        new_text = make_order_text(order, is_demo=DEMO_MODE)
        new_kb = kb.status_kb(order_id, status=order.get("status", "new"), payment="paid")
        await cb.message.edit_text(new_text, reply_markup=new_kb)
    except Exception:
        pass

    await cb.answer("Оплата подтверждена")

    if order.get("user_id"):
        try:
            await bot.send_message(
                order["user_id"],
                f"✅ Оплата по заказу №{order_id} подтверждена заведением. Спасибо!",
            )
        except Exception:
            pass


# ---------- Панель администратора ----------

@router.callback_query(F.data == "admin_active")
async def cb_admin_active(cb: CallbackQuery):
    orders = await get_active_orders()
    if not orders:
        text = "Активных заказов нет."
    else:
        text = "📋 <b>Активные заказы:</b>\n\n"
        for o in orders:
            pay = PAYMENT_TEXT.get(o["payment"], o["payment"])
            text += (
                f"№{o['id']} · {o['pickup_time']} · {o['total']:.2f} Br · "
                f"{o['status']} · 💳 {pay}\n  {o['items']}\n\n"
            )
    await cb.message.answer(text, reply_markup=kb.admin_kb())
    await cb.answer()


@router.callback_query(F.data == "admin_help")
async def cb_admin_help(cb: CallbackQuery, bot: Bot):
    await delete(cb.message)
    await send_and_pin_instruction(cb.message.chat.id, bot)
    await cb.answer("Инструкция закреплена")


@router.message(F.text.in_({"📖 Инструкция", "📖 Инструкция к боту", "Инструкция", "/instruction", "/guide"}))
async def msg_instruction(message: Message, bot: Bot):
    await delete(message)
    await send_and_pin_instruction(message.chat.id, bot)


async def _report_text() -> str:
    rows, total = await get_today_stats()
    if not rows:
        return "📊 Сегодня заказов ещё не было."
    counter = {}
    paid_cnt, cash_cnt = 0, 0
    for r in rows:
        for part in r["items"].split(", "):
            counter[part] = counter.get(part, 0) + 1
        if r["payment"] == "paid":
            paid_cnt += 1
        elif r["payment"] == "cash":
            cash_cnt += 1
    top = sorted(counter.items(), key=lambda x: -x[1])[:5]
    text = (
        f"📊 <b>Отчёт за сегодня</b>\n\n"
        f"Заказов: {len(rows)}\n"
        f"Выручка: <b>{total:.2f} Br</b>\n\n"
        f"💳 Оплачено онлайн: {paid_cnt}\n"
        f"💵 На месте: {cash_cnt}\n\n"
        f"<b>Топ позиций:</b>\n"
    )
    for name, cnt in top:
        text += f"• {name}\n"
    return text


@router.callback_query(F.data == "admin_report")
async def cb_admin_report(cb: CallbackQuery):
    await cb.message.answer(await _report_text(), reply_markup=kb.admin_kb())
    await cb.answer()


@router.message(Command("report"))
async def cmd_report(message: Message):
    await message.answer(await _report_text(), reply_markup=kb.admin_kb())


@router.message(F.text.in_({"⚙️ Панель администратора", "/admin"}))
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    await message.answer("⚙️ <b>Панель администратора</b>", reply_markup=kb.admin_kb())


# ---------- Поиск заказов по номеру телефона для администратора ----------

@router.callback_query(F.data == "admin_search_phone")
async def cb_admin_search_phone(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await delete(cb.message)
    await state.set_state(AdminSearchForm.waiting_for_phone)
    await send_step_msg(
        state,
        bot,
        cb.message.chat.id,
        "🔍 <b>Поиск истории заказов гостя по номеру телефона</b>\n\n"
        "Введите номер телефона гостя (например: <code>+375 29 123-45-67</code> или фрагмент номера):",
        reply_markup=kb.cancel_reply_kb(),
    )
    await cb.answer()


@router.callback_query(F.data == "admin_menu")
async def cb_admin_menu(cb: CallbackQuery):
    await cb.message.answer("⚙️ <b>Панель администратора</b>", reply_markup=kb.admin_kb())
    await cb.answer()


@router.message(AdminSearchForm.waiting_for_phone, F.text)
async def admin_got_phone_search(message: Message, state: FSMContext, bot: Bot):
    await delete(message)
    if message.text.strip() == "❌ Отмена":
        await cleanup_step_msg(state, bot, message.chat.id)
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await message.answer("Поиск отменён.", reply_markup=kb.main_menu())
        return

    query = message.text.strip()
    await cleanup_step_msg(state, bot, message.chat.id)
    await state.clear()
    await state.set_state(OrderForm.browsing)
    await _show_admin_search_results(message.chat.id, bot, query)


@router.message(Command("find"))
@router.message(Command("search"))
async def cmd_find(message: Message, state: FSMContext, bot: Bot):
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        query = args[1].strip()
        await delete(message)
        await _show_admin_search_results(message.chat.id, bot, query)
    else:
        await delete(message)
        await state.set_state(AdminSearchForm.waiting_for_phone)
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "🔍 Введите номер телефона гостя для поиска истории заказов:",
            reply_markup=kb.cancel_reply_kb(),
        )


async def _show_admin_search_results(chat_id: int, bot: Bot, query: str):
    user, orders = await search_orders_by_phone(query)

    if not orders and not user:
        await bot.send_message(
            chat_id,
            f"🔍 По запросу <code>{query}</code> ничего не найдено.\n"
            "Проверьте правильность введённого номера телефона.",
            reply_markup=kb.admin_search_again_kb(),
        )
        return

    phone_display = (user["phone"] if user else None) or query
    name_display = (user["name"] if user else None) or (orders[0]["name"] if orders else "Не указано")
    total_spent = sum(o["total"] for o in orders if o.get("status") != "cancelled")

    verified_str = "✅ Подтверждён" if (user and user.get("is_verified") == 1) else "⚠️ Не подтверждён"
    bonus_str = f"{user['bonus']:.0f} Br" if user else "0 Br"

    user_id = user["user_id"] if user else (orders[0]["user_id"] if orders else None)
    if user_id:
        rev_cnt, avg_r = await get_user_average_rating(user_id)
        if rev_cnt > 0:
            stars_guest = "⭐" * round(avg_r)
            rating_str = f"{stars_guest} {avg_r:.1f} / 5.0 (всего оценок: {rev_cnt})"
        else:
            rating_str = "Пока нет оценок"
    else:
        rating_str = "Пока нет оценок"

    header = (
        f"🔍 <b>История заказов гостя по номеру:</b> <code>{phone_display}</code>\n\n"
        f"👤 Гость: <b>{name_display}</b>\n"
        f"⭐ Общая оценка гостя: <b>{rating_str}</b>\n"
        f"📱 Статус номера: <b>{verified_str}</b>\n"
        f"🎁 Баланс бонусов: <b>{bonus_str}</b>\n"
        f"📦 Всего найдено заказов: <b>{len(orders)}</b> (на сумму <b>{total_spent:.2f} Br</b>)\n"
    )

    if not orders:
        text = header + "\n<i>У данного пользователя пока нет оформленных заказов.</i>"
        await bot.send_message(chat_id, text, reply_markup=kb.admin_search_again_kb())
        return

    lines = [header]
    for o in orders:
        dt = o["created_at"][:19].replace("T", " ")
        st = STATUS_TEXT.get(o["status"], o["status"])
        pay = PAYMENT_TEXT.get(o["payment"], o["payment"])
        deliv_type = o.get("delivery_type") or "pickup"
        if deliv_type == "yandex":
            deliv_line = f"🚕 <b>Яндекс Доставка:</b> {o.get('delivery_address', 'Адрес не указан')} (доставка {o.get('delivery_cost', 0):.2f} Br)"
        else:
            deliv_line = f"🏃 <b>Самовывоз:</b> {CAFE['address']}"

        card = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 <b>Заказ №{o['id']}</b>\n"
            f"📅 <b>Дата и время заказа:</b> {dt}\n"
            f"🕐 <b>Время:</b> {o['pickup_time']}\n"
            f"{deliv_line}\n"
            f"🍽 <b>Состав:</b> {o['items']}\n"
            f"💰 <b>Сумма:</b> {o['total']:.2f} Br\n"
            f"📊 <b>Статус:</b> {st} · <b>Оплата:</b> {pay}"
        )
        if o.get("comment"):
            card += f"\n💬 <b>Пожелание:</b> <i>{o['comment']}</i>"
        lines.append(card)

    full_text = "\n".join(lines)
    if len(full_text) > 4000:
        chunks = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
        for idx, chunk in enumerate(chunks):
            markup = kb.admin_search_again_kb() if idx == len(chunks) - 1 else None
            await bot.send_message(chat_id, chunk, reply_markup=markup)
    else:
        await bot.send_message(chat_id, full_text, reply_markup=kb.admin_search_again_kb())


# ---------- Функция 1: Автоматическая печать чеков на кухне (58/80 мм) ----------

@router.callback_query(F.data.startswith("receipt:"))
async def cb_print_receipt(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":", 1)[1])
    order = await get_order(order_id)
    if not order:
        await cb.answer("Заказ не найден!", show_alert=True)
        return
    order_dict = dict(order)
    receipt_txt = format_receipt_text(order_dict, width=32)
    esc_bytes = generate_esc_pos_bytes(order_dict)

    await cb.message.answer(
        f"🖨 <b>Кухонный чек для термопринтера (58/80 мм):</b>\n\n<pre>{receipt_txt}</pre>",
        reply_markup=None,
    )
    # Отправляем бинарный файл ESC/POS команд для прямого вывода на принтер
    bin_file = BufferedInputFile(esc_bytes, filename=f"receipt_order_{order_id}.bin")
    await cb.message.answer_document(
        bin_file,
        caption=f"📄 Файл ESC/POS команд для термопринтера (Заказ №{order_id})",
    )
    await cb.answer("Чек сгенерирован")


# ---------- Функция 2: Выгрузка отчёта за месяц в Excel (.xlsx) ----------

@router.callback_query(F.data == "admin_export_excel")
async def cb_export_excel(cb: CallbackQuery, bot: Bot):
    await cb.answer("Формирую Excel отчёт...")
    orders = await get_all_orders_for_export(limit=1000)
    if not orders:
        await cb.message.answer("📊 В базе пока нет заказов для отчёта.")
        return

    filepath = generate_excel_report(orders)
    file_to_send = FSInputFile(filepath)
    total_rev = sum(o["total"] for o in orders if o.get("status") != "cancelled")

    await cb.message.answer_document(
        file_to_send,
        caption=(
            f"📊 <b>Отчёт по заказам и выручке кафедры «ПивДонер»</b>\n\n"
            f"📦 Всего заказов в файле: <b>{len(orders)}</b>\n"
            f"💰 Общая выручка: <b>{total_rev:.2f} Br</b>\n\n"
            f"Таблица оформлена со стилями, формулами и авто-шириной колонок."
        ),
        reply_markup=kb.admin_kb(),
    )


# ---------- Рейтинг и отзывы заведения (NPS) ----------

@router.callback_query(F.data == "admin_reviews_stats")
async def cb_admin_reviews_stats(cb: CallbackQuery):
    stats, recent = await get_overall_reviews_stats()
    total = stats.get("total_count") or 0
    avg = stats.get("avg_rating") or 0.0
    c5 = stats.get("c5") or 0
    c4 = stats.get("c4") or 0
    c3 = stats.get("c3") or 0
    c2 = stats.get("c2") or 0
    c1 = stats.get("c1") or 0

    stars_str = "⭐" * round(avg) if total > 0 else "—"

    text = (
        f"⭐ <b>Общая статистика отзывов и репутации (NPS)</b>\n\n"
        f"📊 Средний рейтинг заведения: <b>{stars_str} {avg:.2f} / 5.00</b>\n"
        f"👥 Всего отзывов: <b>{total}</b>\n\n"
        f"<b>Распределение оценок:</b>\n"
        f"5 ⭐: <b>{c5}</b>\n"
        f"4 ⭐: <b>{c4}</b>\n"
        f"3 ⭐: <b>{c3}</b>\n"
        f"2 ⭐: <b>{c2}</b>\n"
        f"1 ⭐: <b>{c1}</b>\n\n"
    )

    if recent:
        text += "📝 <b>Последние 5 отзывов:</b>\n"
        for r in recent:
            st = "⭐" * r.get("rating", 5)
            dt = (r.get("created_at") or "")[:16].replace("T", " ")
            comm = f"<i>«{r.get('comment')}»</i>" if r.get("comment") else "<i>(без комментария)</i>"
            guest = r.get("user_name") or r.get("user_phone") or f"ID {r.get('user_id')}"
            text += f"• {st} от <b>{guest}</b> ({dt}):\n  {comm}\n"
    else:
        text += "<i>Пока нет подробных оценок от гостей.</i>"

    await cb.message.edit_text(text, reply_markup=kb.admin_kb())
    await cb.answer()


# ---------- Функция 3: Таргетированная рассылка от владельца ----------

@router.message(F.text.in_({"📢 Сделать рассылку", "/broadcast"}))
async def msg_start_broadcast(message: Message, state: FSMContext):
    await state.set_state(BroadcastForm.waiting_for_content)
    await message.answer(
        "📢 <b>Таргетированная рассылка от владельца</b>\n\n"
        "Отправьте текст акции или спецпредложения (можно с прикреплённой фотографией).\n\n"
        "<i>Пример: «🔥 Только в эти выходные: при заказе любого Донера — картофель фри в подарок по промокоду ПИВФРИ!»</i>",
        reply_markup=kb.cancel_reply_kb(),
    )


@router.callback_query(F.data == "admin_broadcast")
async def cb_start_broadcast(cb: CallbackQuery, state: FSMContext):
    await state.set_state(BroadcastForm.waiting_for_content)
    await cb.message.answer(
        "📢 <b>Таргетированная рассылка от владельца</b>\n\n"
        "Отправьте текст акции или спецпредложения (можно с прикреплённой фотографией).\n\n"
        "<i>Пример: «🔥 Только в эти выходные: при заказе любого Донера — картофель фри в подарок по промокоду ПИВФРИ!»</i>",
        reply_markup=kb.cancel_reply_kb(),
    )
    await cb.answer()


@router.message(BroadcastForm.waiting_for_content, F.photo)
async def broadcast_got_photo(message: Message, state: FSMContext, bot: Bot):
    photo_id = message.photo[-1].file_id
    caption = message.caption or ""
    users = await get_all_users()
    count = len(users)

    await state.update_data(photo_id=photo_id, text=caption, target_count=count)
    await state.set_state(BroadcastForm.confirm_send)

    await message.answer_photo(
        photo=photo_id,
        caption=(
            f"📢 <b>Предпросмотр рассылки:</b>\n\n"
            f"{caption}\n\n"
            f"👥 Получателей: <b>{count} человек</b> (все зарегистрированные гости)\n\n"
            "Отправить сообщение всем гостям прямо сейчас?"
        ),
        reply_markup=kb.broadcast_confirm_kb(),
    )


@router.message(BroadcastForm.waiting_for_content, F.text)
async def broadcast_got_text(message: Message, state: FSMContext, bot: Bot):
    if message.text.strip() == "❌ Отмена":
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await message.answer("Рассылка отменена.", reply_markup=kb.main_menu())
        return

    text = message.text.strip()
    users = await get_all_users()
    count = len(users)

    await state.update_data(text=text, photo_id=None, target_count=count)
    await state.set_state(BroadcastForm.confirm_send)

    await message.answer(
        f"📢 <b>Предпросмотр рассылки:</b>\n\n"
        f"{text}\n\n"
        f"👥 Получателей: <b>{count} человек</b> (все зарегистрированные гости)\n\n"
        "Отправить сообщение всем гостям прямо сейчас?",
        reply_markup=kb.broadcast_confirm_kb(),
    )


@router.callback_query(BroadcastForm.confirm_send, F.data == "broadcast:send")
async def cb_send_broadcast(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    text = data.get("text", "")
    photo_id = data.get("photo_id")
    users = await get_all_users()

    await cb.message.edit_text("⏳ <b>Идёт отправка рассылки...</b> Пожалуйста, подождите.")

    success_cnt = 0
    fail_cnt = 0

    for u in users:
        uid = u["user_id"]
        try:
            if photo_id:
                await bot.send_photo(uid, photo_id, caption=text)
            else:
                await bot.send_message(uid, text)
            success_cnt += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_cnt += 1

    await state.clear()
    await state.set_state(OrderForm.browsing)

    await cb.message.edit_text(
        f"✅ <b>Рассылка успешно завершена!</b>\n\n"
        f"📬 Доставлено: <b>{success_cnt}</b> пользователям\n"
        f"⚠️ Не доставлено: <b>{fail_cnt}</b> (заблокировали бота)\n\n"
        "Все клиенты получили ваше спецпредложение!",
        reply_markup=kb.admin_kb(),
    )
    await cb.answer("Рассылка завершена")


@router.callback_query(BroadcastForm.confirm_send, F.data == "broadcast:cancel")
async def cb_cancel_broadcast(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(OrderForm.browsing)
    await cb.message.edit_text("❌ Рассылка отменена.", reply_markup=kb.admin_kb())
    await cb.answer("Отменено")


# ---------- Функция 4: Автоматический сбор отзывов и репутация (NPS) ----------

def schedule_order_review(bot: Bot, order_id: int, user_id: int, delay_sec: int = 15):
    """Планирует опрос качества заказа (NPS) после выдачи/доставки."""
    async def _job():
        await asyncio.sleep(delay_sec)
        try:
            await bot.send_message(
                user_id,
                f"❤️ <b>Как вам наш заказ №{order_id}?</b>\n\n"
                "Пожалуйста, оцените вкус блюд и качество обслуживания от 1 до 5 звёзд:\n"
                "(Ваш отзыв помогает нам становиться лучше!)",
                reply_markup=kb.review_kb(order_id),
            )
        except Exception:
            pass
    asyncio.create_task(_job())


@router.callback_query(F.data.startswith("review:"))
async def cb_review_rating(cb: CallbackQuery, state: FSMContext, bot: Bot):
    parts = cb.data.split(":")
    order_id = int(parts[1])
    rating = int(parts[2])
    user_id = cb.from_user.id

    await create_review(order_id=order_id, user_id=user_id, rating=rating)

    # МГНОВЕННОЕ УВЕДОМЛЕНИЕ АДМИНИСТРАТОРУ О ЛЮБОЙ ОЦЕНКЕ (1-5 ⭐)
    user = await get_user(user_id)
    uname = user["name"] if user else cb.from_user.first_name
    uphone = user["phone"] if user else "Не указан"
    chat = user_id if DEMO_MODE else MANAGER_CHAT_ID

    stars_icon = "⭐" * rating
    if rating >= 4:
        header_alert = f"🌟 <b>НОВАЯ ПОЛОЖИТЕЛЬНАЯ ОЦЕНКА ПО ЗАКАЗУ №{order_id}!</b>"
    else:
        header_alert = f"⚠️ <b>НИЗКАЯ ОЦЕНКА ПО ЗАКАЗУ №{order_id}!</b>"

    alert_msg = (
        f"{header_alert}\n\n"
        f"⭐ Оценка: <b>{stars_icon} ({rating}/5)</b>\n"
        f"👤 Клиент: <b>{uname}</b>\n"
        f"📱 Телефон: <code>{uphone}</code>\n"
        f"🧾 Заказ: <b>№{order_id}</b>"
    )
    try:
        await bot.send_message(chat, alert_msg)
    except Exception:
        pass

    if rating >= 4:
        stars_str = "⭐" * rating
        await cb.message.edit_text(
            f"🌟 <b>Спасибо за вашу оценку {stars_str}!</b>\n\n"
            "Мы безумно рады, что вам понравилась наша шаурма!\n\n"
            "Поделитесь вашим впечатлением на <b>Яндекс Картах</b> — мы начислим вам <b>+2.00 Br бонусов</b> на баланс личного кабинета!",
            reply_markup=kb.review_high_kb(order_id),
        )
    else:
        stars_str = "⭐" * rating
        await state.update_data(review_order_id=order_id, review_rating=rating)
        await state.set_state(ReviewForm.waiting_for_comment)
        await cb.message.edit_text(
            f"😔 <b>Приносим искренние извинения! (Ваша оценка: {stars_str})</b>\n\n"
            "Для нас критически важно качество. Пожалуйста, напишите в ответном сообщении, что именно пошло не так (вкус, температура, время ожидания или курьер)?\n\n"
            "Шеф-повар и управляющий немедленно разберутся в ситуации:",
            reply_markup=kb.cancel_reply_kb(),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("review_bonus:"))
async def cb_review_bonus(cb: CallbackQuery):
    order_id = int(cb.data.split(":", 1)[1])
    await add_bonus(cb.from_user.id, 2.0)
    await cb.message.edit_text(
        "🎉 <b>+2.00 Br бонусов зачислено на ваш баланс!</b>\n\n"
        "Спасибо за отзыв на Яндекс Картах! Вы можете использовать бонусы в личном кабинете при следующих заказах.",
        reply_markup=None,
    )
    await cb.answer("Бонусы зачислены!")


@router.message(ReviewForm.waiting_for_comment, F.text)
async def review_got_comment(message: Message, state: FSMContext, bot: Bot):
    if message.text.strip() == "❌ Отмена":
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await message.answer("Спасибо за обратную связь!", reply_markup=kb.main_menu())
        return

    data = await state.get_data()
    order_id = data.get("review_order_id", 0)
    rating = data.get("review_rating", 1)
    comment = message.text.strip()

    await create_review(order_id=order_id, user_id=message.from_user.id, rating=rating, comment=comment)

    user = await get_user(message.from_user.id)
    uname = user["name"] if user else message.from_user.first_name
    uphone = user["phone"] if user else "Не указан"
    chat = message.from_user.id if DEMO_MODE else MANAGER_CHAT_ID

    alert_text = (
        f"🚨 <b>ВНИМАНИЕ РУКОВОДСТВУ! НЕГАТИВНЫЙ ОТЗЫВ ПО ЗАКАЗУ №{order_id}</b>\n\n"
        f"⭐ Оценка: <b>{'⭐' * rating} ({rating}/5)</b>\n"
        f"👤 Клиент: <b>{uname}</b>\n"
        f"📱 Телефон: <code>{uphone}</code>\n"
        f"💬 Замечание: <i>«{comment}»</i>\n\n"
        "👉 Пожалуйста, свяжитесь с клиентом для урегулирования ситуации!"
    )
    try:
        await bot.send_message(chat, alert_text)
    except Exception:
        pass

    await state.clear()
    await state.set_state(OrderForm.browsing)
    await message.answer(
        "🙏 <b>Спасибо за честный отзыв!</b>\n"
        "Ваше обращение передано руководству. Мы обязательно разберёмся и сделаем выводы.",
        reply_markup=kb.main_menu(),
    )


# ---------- Функция 5: Telegram Web App (Mini App) ----------

@router.message(F.web_app_data)
async def got_webapp_data(message: Message, state: FSMContext, bot: Bot):
    raw_data = message.web_app_data.data
    try:
        parsed = json.loads(raw_data)
        cart = parsed.get("cart", {})
        if not cart:
            await message.answer("🧺 Корзина в Mini App пуста. Выберите позиции в меню.")
            return

        await save_cart(state, cart)
        await message.answer("🚀 <b>Заказ из Mini App принят!</b> Переходим к оформлению:")
        await proceed_to_checkout(message.chat.id, message.from_user.id, state, bot)
    except Exception as e:
        logging.exception("Error processing web_app_data: %s", e)
        await message.answer("⚠️ Не удалось прочитать данные из Mini App.")


@router.message(F.text.in_({"🚀 Интерактивное меню (Mini App)", "🚀 Меню в Mini App", "🚀 Меню (Mini App)", "/webapp", "/app"}))
async def msg_open_webapp(message: Message):
    await message.answer(
        "🍔 <b>Интерактивная витрина «ПивДонер» (Telegram Mini App)</b>\n\n"
        "Нажмите кнопку ниже, чтобы открыть красивое меню с фотографиями, составом блюд и быстрой сборкой корзины:",
        reply_markup=kb.webapp_kb(),
    )
