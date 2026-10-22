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
    ADMIN_IDS,
    DEMO_MODE,
    MANAGER_CHAT_ID,
    PAYMENT_ENABLED,
    PAYMENT_URL,
    SELLER_CONTACT,
)


def is_admin_user(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    if not user_id:
        return False
    if DEMO_MODE:
        return True
    return user_id in ADMIN_IDS
from db import (
    add_bonus,
    add_to_stop_list,
    create_complaint,
    create_order,
    create_review,
    get_active_orders,
    get_all_orders_for_export,
    get_all_users,
    get_broadcast_consent,
    get_establishment_dashboard,
    get_item_stop_info,
    get_order,
    get_order_status,
    get_overall_reviews_stats,
    get_stop_list,
    get_today_stats,
    get_user,
    get_user_average_rating,
    get_user_orders,
    get_user_referral_stats,
    get_user_stats,
    has_review_for_order,
    remove_from_stop_list,
    search_orders_by_phone,
    set_broadcast_consent,
    set_last_bonus_game,
    set_order_cancellation,
    set_order_group_msg,
    set_order_payment,
    set_order_status,
    set_referrer,
    switch_order_to_pickup,
    update_user_name,
    update_user_phone,
    upsert_user,
)
from excel_report import generate_excel_report
from menu import CAFE, ITEMS, MENU, TOPPINGS, TOPPINGS_MAP, cart_text, fmt_price, parse_cart_item, pickup_ready_text
from states import (
    AdminCancelForm,
    AdminSearchForm,
    AdminStopForm,
    BroadcastForm,
    ComplaintForm,
    OrderForm,
    ProfileEditForm,
    RegistrationForm,
    ReviewForm,
)
from thermal_printer import format_receipt_text, generate_esc_pos_bytes
from yandex_delivery import calculate_yandex_delivery, cancel_delivery_simulation, run_yandex_delivery_simulation

router = Router()

STATUS_TEXT = {
    "new": "🆕 Новый",
    "accepted": "✅ Принят",
    "cooking": "🔥 Готовится",
    "ready": "🛍 Готов к выдаче",
    "to_courier": "🚗 Передан курьеру (в пути)",
    "completed": "🏁 Выдан гостю",
    "cancelled": "❌ Отменён",
}

PAYMENT_TEXT = {
    "none": "не выбрана",
    "cash": "💵 на месте",
    "online_marked": "💳 онлайн (ждёт подтверждения)",
    "yandex_pending": "⏳ ожидает онлайн-оплаты в Яндекс",
    "yandex_online": "💳 онлайн (Яндекс)",
    "paid": "✅ оплачен онлайн",
}

CANCEL_REASONS = {
    "ingredients": "Закончились необходимые ингредиенты на кухне",
    "power": "Аварийное отключение электричества / оборудования (форс-мажор)",
    "overload": "Пиковая загрузка кухни, время ожидания более 60 минут",
    "unreachable": "Не удалось связаться с клиентом по указанному номеру",
}

STOP_REASONS = {
    "ingredients": "Закончились необходимые ингредиенты",
    "supplier": "Задержка поставки продуктов от поставщика",
    "equipment": "Техническое обслуживание / ремонт оборудования",
    "overload": "Пиковая загрузка кухни, временно не принимается",
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
    if order.get("cancellation_reason"):
        text += f"\n❌ Причина отмены: <b>{order['cancellation_reason']}</b>"
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


async def safe_edit(cb: CallbackQuery, text: str, reply_markup=None):
    """Безопасный edit: если сообщение без текста (фото/документ/стикер) — шлём новое."""
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await cb.message.answer(text, reply_markup=reply_markup)
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
    "📌 <b>АКТУАЛЬНАЯ ИНСТРУКЦИЯ И РАБОЧИЙ РЕЖИМ «ПИВДОНЕР PRO»</b>\n"
    "<i>(Служебная панель администратора заведения и управления кухней)</i>\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "👨‍🍳 <b>1. СЛУЖЕБНЫЕ ФУНКЦИИ АДМИНИСТРАТОРА:</b>\n\n"
    "• <b>ℹ️ Информация о заведении</b> — полная оперативная сводка смены в реальном времени: название и адрес кафе, текущий стоп-лист, число принятых и отменённых заказов, выручка, новости заведения.\n"
    "• <b>⛔ Стоп-лист кухни (/stop)</b> — постановка любого блюда или добавки в шаурму на стоп с фиксацией обязательной причины (закончились ингредиенты, задержка поставщика, сбой оборудования). Клиенты не могут заказать позицию и видят вежливое объяснение.\n"
    "• <b>📋 Активные заказы (/active)</b> — список всех заказов, которые готовятся на кухне или переданы курьеру Яндекс Go.\n"
    "• <b>📊 Отчёт за смену (/report)</b> — финансовый отчёт по выручке, числу заказов и топ-позициям за день.\n"
    "• <b>📑 Экспорт в Excel (/excel)</b> — скачивание детализированного файла .xlsx со всеми заказами, адресами доставки и суммами.\n"
    "• <b>📢 Таргетированная рассылка</b> — моментальная отправка акций и спецпредложений всем гостям с фото и текстом.\n"
    "• <b>🔍 Поиск по номеру (/search)</b> — поиск истории заказов и среднего чека гостя по номеру телефона.\n"
    "• <b>⭐ Рейтинг и отзывы</b> — статистика оценок NPS гостей (1-5 ⭐) с авто-начислением бонусов за отзывы на Яндекс Картах.\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "🛎 <b>2. КАРТОЧКА ЗАКАЗА НА КУХНЕ:</b>\n\n"
    "Каждый заказ поступает в группу с интерактивными кнопками смены статуса:\n"
    "• <b>[✅ Принять]</b> → повара уведомлены, включается поиск машины Яндекс Доставки.\n"
    "• <b>[🔥 Готовится]</b> → клиент видит уведомление, что блюда на гриле.\n"
    "• <b>[🛍 Готов к выдаче]</b> → заказ упакован в крафт-пакет и ждёт гостя или курьера.\n"
    "• <b>[🏁 Выдан гостю]</b> → завершение заказа, спустя 20 мин клиенту придёт опрос качества.\n"
    "• <b>[❌ Отменить заказ]</b> → обязательный выбор причины отмены с уведомлением клиента.\n"
    "• <b>[🖨 Печать чека]</b> → термопечать кухонного чека 58/80 мм на ESC/POS принтер.\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "🔒 <b>3. СТРОГОЕ РАЗДЕЛЕНИЕ ЧАТОВ:</b>\n\n"
    "• <b>В группе «Заказы ПивДонер»</b> отключены все кнопки гостя (оформить заказ, меню, корзина). Доступна ТОЛЬКО служебная панель администратора.\n"
    "• <b>В личном чате с ботом</b> гости оформляют предзаказы, выбирают самовывоз или Яндекс Доставку и копят бонусы.\n\n"
    "👇 <i>Используйте кнопки под строкой ввода и интерактивную панель ниже для управления:</i>"
)


async def send_and_pin_instruction(chat_id: int, bot: Bot, reply_markup=None):
    """Отправляет актуальную инструкцию администратора/кухни и закрепляет её в чате."""
    markup = reply_markup or kb.admin_kb()
    msg = await bot.send_message(chat_id, INSTRUCTION_TEXT, reply_markup=markup)
    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
    except Exception as e:
        logging.warning("Could not pin instruction message in chat %s: %s", chat_id, e)
    return msg


async def send_main_greeting(message: Message, name: str, bot: Bot = None):
    """Главное приветствие для зарегистрированного пользователя (разное для гостя и админа)."""
    b = bot or message.bot
    uid = message.from_user.id if message.from_user else 0
    is_admin = is_admin_user(uid)

    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID or is_admin:
        # Для администратора или группы кухни: ТОЛЬКО панель администратора! Без кнопок гостя!
        await message.answer(
            f"⚙️ <b>Панель администратора «{CAFE['name']}»</b>\n\n"
            f"👤 Авторизован: <b>{name}</b> (Администратор)\n"
            "Все кнопки гостя скрыты. Вам доступно только управление кухней, стоп-листом и заказами.",
            reply_markup=kb.admin_reply_menu(),
        )
        await message.answer("Панель быстрого доступа:", reply_markup=kb.admin_kb())
        await send_and_pin_instruction(message.chat.id, b)
        return

    # Для обычного гостя:
    await message.answer(
        f"👋 Привет, {name}!\n\n"
        f"Это <b>{CAFE['name']}</b> — донеры, ланчбоксы и хот-доги без очереди и ожидания.\n\n"
        "🛒 Сделай предзаказ — и к твоему приезду всё будет готово.\n"
        "🕐 Забери к выбранному времени по адресу:\n"
        f"📍 {CAFE['address']}\n"
        f"📞 {CAFE['phone']}",
        reply_markup=kb.guest_reply_menu(),
    )
    await message.answer("Быстрые действия:", reply_markup=kb.quick_actions_kb())
    if DEMO_MODE:
        await send_and_pin_instruction(message.chat.id, b)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        await message.reply(
            "👨‍🍳 <b>Группа кухни «ПивДонер» активна!</b>\n\n"
            "Сюда поступают подтверждённые заказы.\n"
            "Панель администратора закреплена. Для управления используйте кнопки под строкой ввода.",
            reply_markup=kb.admin_reply_menu(),
        )
        return

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

    # Проверяем согласие на получение рассылок при первом запуске
    user = dict(user)
    if user.get("broadcast_consent") is None:
        await message.answer(
            f"👋 Привет, {name}!\n\n"
            f"Добро пожаловать в кафе <b>«{CAFE['name']}»</b>.\n\n"
            "📢 <b>Уведомления и специальные предложения:</b>\n"
            "Хотите получать информацию об эксклюзивных скидках, новинках меню и секретных промокодах от «ПивДонер»?\n"
            "<i>(Вы всегда сможете изменить этот выбор в личном кабинете)</i>",
            reply_markup=kb.broadcast_consent_kb(),
        )
        return

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


@router.callback_query(F.data.startswith("bcast_consent:"))
async def cb_bcast_consent(cb: CallbackQuery, state: FSMContext, bot: Bot):
    val = int(cb.data.split(":", 1)[1])
    await set_broadcast_consent(cb.from_user.id, val)
    user = await get_user(cb.from_user.id)
    name = (user["name"] if user else None) or cb.from_user.first_name or "Гость"
    ack = "✅ Вы согласились получать акции и скидки!" if val == 1 else "❌ Хорошо, мы не будем беспокоить вас рекламными рассылками."
    await cb.message.edit_text(
        f"{ack}\n\nНастройки сохранены. Вы всегда можете изменить их в личном кабинете.",
        reply_markup=None,
    )
    if not is_user_verified(user):
        await state.set_state(RegistrationForm.waiting_for_phone)
        await send_step_msg(
            state,
            bot,
            cb.message.chat.id,
            f"🔐 <b>Регистрация гостя:</b>\n\n"
            f"Перед оформлением заказов подтвердите свой номер телефона.\n"
            f"Нажмите кнопку ниже или введите номер сообщением:",
            reply_markup=kb.phone_request_kb(),
        )
    else:
        await send_main_greeting(cb.message, name)
    await cb.answer()


@router.callback_query(F.data.startswith("toggle_bcast:"))
async def cb_toggle_bcast(cb: CallbackQuery, state: FSMContext, bot: Bot):
    val = int(cb.data.split(":", 1)[1])
    await set_broadcast_consent(cb.from_user.id, val)
    await show_profile(cb.message.chat.id, cb.from_user.id, bot, state)
    status_str = "включена ✅" if val == 1 else "отключена 🔕"
    await cb.answer(f"Рассылка акций {status_str}")


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

    user_d = dict(user)
    bcast_status = user_d.get("broadcast_consent") if user_d.get("broadcast_consent") is not None else 1
    markup = kb.profile_kb(is_verified=verified, broadcast_consent=bcast_status)
    if state:
        await send_step_msg(state, bot, chat_id, text, reply_markup=markup)
    else:
        await bot.send_message(chat_id, text, reply_markup=markup)


@router.message(Command("profile"))
@router.message(F.text.in_({"👤 Личный кабинет", "👤 Мой профиль", "/profile"}))
async def my_profile_msg(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        bot_info = await bot.get_me()
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="👤 Личный кабинет (в личке)", url=f"https://t.me/{bot_info.username}?start=profile"))
        await message.reply("👤 Личный кабинет гостя доступен в личном чате с ботом:", reply_markup=b.as_markup())
        return
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


@router.message(Command(commands=["ref", "referral"]))
@router.message(F.text.in_({"🎁 Пригласи друга (+2 Br)", "🎁 Реферальная ссылка", "/ref", "/referral"}))
async def msg_referral_link(message: Message, bot: Bot):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        return
    await delete(message)
    await _send_referral_info(message.chat.id, message.from_user.id, bot)


@router.callback_query(F.data == "referral_link")
async def cb_referral_link(cb: CallbackQuery, bot: Bot):
    await _send_referral_info(cb.message.chat.id, cb.from_user.id, bot, edit_message=cb.message)
    await cb.answer()


# ---------- История заказов и Инфо ----------

@router.message(Command("history"))
@router.message(F.text.in_({"📜 Мои заказы", "📜 История заказов", "/history"}))
async def order_history_msg(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        return
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
        for row in orders:
            o = dict(row)
            dt = o["created_at"][:16].replace("T", " ")
            st = STATUS_TEXT.get(o.get("status", "new"), o.get("status", "new"))
            pay = PAYMENT_TEXT.get(o.get("payment", "none"), o.get("payment", "none"))
            deliv = "🚕 Яндекс Доставка" if o.get("delivery_type") == "yandex" else "🏃 Самовывоз"
            text += f"№{o['id']} · {dt} · <b>{o.get('total', 0.0):.2f} Br</b> ({deliv})\n  {o.get('items', '')}\n  📊 {st} · {pay}\n\n"

    kb_markup = kb.categories_kb()
    if state:
        await send_step_msg(state, bot, chat_id, text, reply_markup=kb_markup)
    else:
        await bot.send_message(chat_id, text, reply_markup=kb_markup)


@router.message(F.text.in_({"📍 Адрес и инфо", "📍 Адрес и время работы"}))
async def cafe_info_msg(message: Message):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        return
    await message.answer(
        f"📍 <b>{CAFE['name']}</b>\n"
        f"Адрес: {CAFE['address']}\n\n"
        f"🕐 Время работы: ежедневно {CAFE['hours']}\n"
        f"📞 Телефон: {CAFE['phone']}\n\n"
        "Сделайте заказ в боте к нужному времени — заберите горячим и без очереди!",
        reply_markup=kb.info_kb(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        text = (
            "👨‍🍳 <b>Команды кухни и администратора:</b>\n\n"
            "• /stop или /stoplist — управление стоп-листом кухни (блюда и добавки)\n"
            "• /active — список активных заказов в работе\n"
            "• /report — финансовый отчёт за сегодня\n"
            "• /excel — выгрузка всех заказов в Excel (.xlsx)\n"
            "• /id — ID текущего чата\n"
            "• /help — эта справка\n\n"
            "💡 Все входящие заказы приходят сюда в виде карточек с кнопками управления статусом и печатью чека."
        )
        await message.reply(text)
    else:
        await message.answer(
            "🍔 <b>Помощь по боту «ПивДонер»:</b>\n\n"
            "• /menu — открыть меню блюд\n"
            "• /order — оформить предзаказ\n"
            "• /cart — открыть корзину\n"
            "• /profile — личный кабинет и бонусы\n"
            "• /history — история ваших заказов\n"
            "• /game — ежедневная игра в кубик за бонусы\n"
            "• /complaint — написать обращение руководству",
            reply_markup=kb.main_menu(),
        )


# ---------- Подача жалобы администратору ----------

@router.message(Command("complaint"))
@router.message(F.text.in_({"🚨 Подать жалобу", "🚨 Подать жалобу администратору", "Подать жалобу", "Жалоба", "/complaint"}))
async def start_complaint_msg(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        return
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

@router.message(Command("game"))
@router.message(F.text.in_({"🎲 Игра с бонусами", "🎲 Игра «Кубик»", "🎮 Мини-игра", "/game"}))
async def mini_game_msg(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        return
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

@router.message(Command("menu"))
@router.message(F.text.in_({"🍔 Меню", "/menu"}))
async def show_menu_msg(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        bot_info = await bot.get_me()
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🍔 Открыть меню в боте (в личке)", url=f"https://t.me/{bot_info.username}?start=menu"))
        await message.reply(
            "👋 <b>В группе кухни меню не отображается.</b>\nОформить заказ и посмотреть меню можно в личном чате с ботом:",
            reply_markup=b.as_markup()
        )
        return
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
    stop_list = await get_stop_list()
    await cb.message.edit_text(
        f"<b>{cat}</b>\n\n"
        "Нажмите на позицию, чтобы посмотреть подробный состав, граммовку и добавить в корзину:",
        reply_markup=kb.items_kb(cat, cart, stop_list=stop_list),
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
    stop_info = await get_item_stop_info(item_id)
    if stop_info:
        item = ITEMS.get(item_id, {})
        item_name = item.get("name", item_id)
        reason = stop_info.get("reason", "Закончилось на кухне")
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        cat = item.get("category", "")
        if cat:
            b.row(InlineKeyboardButton(text="⬅️ Назад в категорию", callback_data=f"cat:{cat}"))
        b.row(
            InlineKeyboardButton(text="🍔 Главное меню", callback_data="menu"),
            InlineKeyboardButton(text="🧺 Корзина", callback_data="cart"),
        )
        await cb.message.edit_text(
            f"⛔ <b>Блюдо временно недоступно для заказа!</b>\n\n"
            f"«<b>{item_name}</b>» сейчас находится на стопе кухни.\n\n"
            f"📌 <b>Причина:</b> <i>{reason}</i>\n\n"
            "Приносим искренние извинения за временные неудобства! Пожалуйста, выберите другое аппетитное блюдо из нашего меню.",
            reply_markup=b.as_markup(),
        )
        await cb.answer("Позиция на стопе")
        return

    cart = await get_cart(state)
    qty = cart.get(item_id, 0)
    text = make_item_card_text(item_id, qty)
    await cb.message.edit_text(text, reply_markup=kb.item_kb(item_id, qty))
    await cb.answer()


@router.callback_query(F.data.startswith("inc:"))
async def cb_inc(cb: CallbackQuery, state: FSMContext):
    item_id = cb.data.split(":", 1)[1]
    stop_info = await get_item_stop_info(item_id)
    if stop_info:
        await cb.answer(f"⛔ Блюдо на стопе: {stop_info.get('reason', 'Закончилось')}", show_alert=True)
        return
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
    stop_info = await get_item_stop_info(item_id)
    if stop_info:
        await cb.answer(f"⛔ Блюдо на стопе: {stop_info.get('reason', 'Закончилось')}", show_alert=True)
        return
    cart = await get_cart(state)
    if cart.get(item_id, 0) > 0:
        cart[item_id] -= 1
    await save_cart(state, cart)
    qty = cart.get(item_id, 0)
    text = make_item_card_text(item_id, qty)
    await cb.message.edit_text(text, reply_markup=kb.item_kb(item_id, qty))
    await cb.answer()


@router.callback_query(F.data.startswith("top_sel:"))
async def cb_top_sel(cb: CallbackQuery):
    doner_id = cb.data.split(":", 1)[1]
    stop_list = await get_stop_list()
    base = ITEMS.get(doner_id, {})
    text = (
        f"🧀 <b>Конструктор добавок к «{base.get('name', 'Шаурме')}»:</b>\n\n"
        f"Базовая цена: <b>{base.get('price', 0.0):.2f} Br</b>\n\n"
        f"Отмечайте нужные добавки кнопками ниже и нажмите <b>«Добавить в корзину»</b>:"
    )
    await cb.message.edit_text(text, reply_markup=kb.toppings_selector_kb(doner_id, mask="", stop_list=stop_list))
    await cb.answer()


@router.callback_query(F.data.startswith("top_t:"))
async def cb_top_toggle(cb: CallbackQuery):
    parts = cb.data.split(":")
    if len(parts) < 3:
        await cb.answer()
        return
    doner_id = parts[1]
    idx_str = parts[2]
    old_mask = parts[3] if len(parts) >= 4 else ""

    mask_set = set(old_mask)
    if idx_str in mask_set:
        mask_set.remove(idx_str)
    else:
        mask_set.add(idx_str)
    new_mask = "".join(sorted(mask_set))

    base = ITEMS.get(doner_id, {})
    total_price = base.get("price", 0.0)
    selected_names = []
    for d in new_mask:
        t = TOPPINGS[int(d)]
        total_price += t["price"]
        selected_names.append(t["name"])

    stop_list = await get_stop_list()
    tops_info = f"\nВыбрано: <i>{', '.join(selected_names)}</i>" if selected_names else ""
    text = (
        f"🧀 <b>Конструктор добавок к «{base.get('name', 'Шаурме')}»:</b>\n\n"
        f"Базовая цена: <b>{base.get('price', 0.0):.2f} Br</b>{tops_info}\n"
        f"Итоговая цена: <b>{total_price:.2f} Br</b>\n\n"
        f"Отмечайте нужные добавки кнопками ниже и нажмите <b>«Добавить в корзину»</b>:"
    )
    await cb.message.edit_text(text, reply_markup=kb.toppings_selector_kb(doner_id, mask=new_mask, stop_list=stop_list))
    await cb.answer()


@router.callback_query(F.data.startswith("top_blocked:"))
async def cb_top_blocked(cb: CallbackQuery):
    top_id = cb.data.split(":", 1)[1]
    stop_info = await get_item_stop_info(top_id)
    reason = stop_info.get("reason", "Закончилась на кухне") if stop_info else "Закончилась на кухне"
    top_name = TOPPINGS_MAP.get(top_id, {}).get("name", top_id)
    await cb.answer(f"⛔ Добавка «{top_name}» временно на стопе!\nПричина: {reason}", show_alert=True)


@router.callback_query(F.data.startswith("top_add:"))
async def cb_top_add(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    doner_id = parts[1]
    mask = parts[2] if len(parts) >= 3 else ""

    stop_list = await get_stop_list()
    if doner_id in stop_list:
        dname = ITEMS.get(doner_id, {}).get("name", doner_id)
        await cb.answer(f"⛔ Блюдо «{dname}» сейчас на стопе кухни!", show_alert=True)
        return

    stopped_tops = []
    top_ids = []
    for d in mask:
        if d.isdigit() and int(d) < len(TOPPINGS):
            tid = TOPPINGS[int(d)]["id"]
            if tid in stop_list:
                stopped_tops.append(TOPPINGS[int(d)]["name"])
            else:
                top_ids.append(tid)

    if stopped_tops:
        await cb.answer(f"⛔ Добавка {', '.join(stopped_tops)} сейчас на стопе!", show_alert=True)
        return

    if top_ids:
        item_key = f"{doner_id}+{'+'.join(top_ids)}"
    else:
        item_key = doner_id

    cart = await get_cart(state)
    cart[item_key] = cart.get(item_key, 0) + 1
    await save_cart(state, cart)

    parsed = parse_cart_item(item_key)
    item_name = parsed["name"] if parsed else ITEMS.get(doner_id, {}).get("name", doner_id)
    item_price = parsed["price"] if parsed else ITEMS.get(doner_id, {}).get("price", 0.0)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🧺 Перейти в корзину", callback_data="cart"),
        InlineKeyboardButton(text="🍔 Меню", callback_data="menu"),
    )
    cat = ITEMS.get(doner_id, {}).get("category", "🌯 Донеры / Шаурма")
    b.row(InlineKeyboardButton(text="🌯 Ещё шаурму", callback_data=f"cat:{cat}"))

    text = (
        f"✅ <b>{item_name}</b> добавлена в корзину!\n\n"
        f"💰 Цена: <b>{item_price:.2f} Br</b>\n"
        f"В корзине: <b>{cart[item_key]} шт</b>"
    )
    await cb.message.edit_text(text, reply_markup=b.as_markup())
    await cb.answer("Шаурма добавлена в корзину!")


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


@router.message(Command("cart"))
@router.message(F.text.in_({"🧺 Корзина", "/cart"}))
async def show_cart_msg(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        bot_info = await bot.get_me()
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🧺 Корзина в боте (в личке)", url=f"https://t.me/{bot_info.username}?start=cart"))
        await message.reply("🧺 Корзина доступна в личном чате с ботом:", reply_markup=b.as_markup())
        return
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

@router.message(Command("order"))
@router.message(F.text.in_({"🛒 Оформить заказ", "🛒 Оформить предзаказ", "/order"}))
async def start_order_msg(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID:
        bot_info = await bot.get_me()
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🛒 Оформить заказ в боте (в личке)", url=f"https://t.me/{bot_info.username}?start=order"))
        await message.reply("🛒 Оформление заказа доступно в личном чате с ботом:", reply_markup=b.as_markup())
        return
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
    """Начало чистого оформления заказа с проверкой стоп-листа кухни, верификации гостя и выбором доставки."""
    cart = await get_cart(state)
    if not cart:
        await send_step_msg(
            state,
            bot,
            chat_id,
            "🧺 Корзина пуста. Сначала добавьте блюда из меню:",
            reply_markup=kb.categories_kb(),
        )
        return

    # Проверка позиций корзины по актуальному стоп-листу кухни
    stop_list = await get_stop_list()
    if stop_list:
        stopped_in_cart = []
        for raw_id in cart.keys():
            parsed = parse_cart_item(raw_id)
            base_id = parsed["base_id"] if parsed else raw_id
            if base_id in stop_list:
                stopped_in_cart.append((parsed["name"] if parsed else base_id, stop_list[base_id].get("reason", "Закончилось на кухне")))
            if parsed and parsed.get("toppings"):
                for top_id in parsed["toppings"]:
                    if top_id in stop_list:
                        top_name = TOPPINGS_MAP.get(top_id, {}).get("name", top_id)
                        stopped_in_cart.append((f"{parsed['name']} (добавка {top_name})", stop_list[top_id].get("reason", "Закончилась на кухне")))

        if stopped_in_cart:
            err_lines = "\n".join([f"• <b>{name}</b> — <i>{reason}</i>" for name, reason in stopped_in_cart])
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            from aiogram.types import InlineKeyboardButton
            b = InlineKeyboardBuilder()
            b.row(InlineKeyboardButton(text="🧺 Открыть корзину и изменить", callback_data="cart"))
            b.row(InlineKeyboardButton(text="🍔 Меню", callback_data="menu"))
            await send_step_msg(
                state,
                bot,
                chat_id,
                f"⚠️ <b>Внимание: часть позиций в вашей корзине сейчас на стопе кухни!</b>\n\n"
                f"{err_lines}\n\n"
                "Пожалуйста, удалите эти позиции из корзины или замените их перед продолжением заказа.",
                reply_markup=b.as_markup(),
            )
            return

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
    if message.text.strip() == "❌ Отмена":
        await delete(message)
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
    try:
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
    except Exception as e:
        logging.exception("Error processing delivery address: %s", e)
        await bot.send_message(
            chat_id,
            "⚠️ Не удалось рассчитать адрес доставки. Пожалуйста, напишите улицу и номер дома ещё раз:",
            reply_markup=kb.address_request_kb(),
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
    # Валидация формата ЧЧ:ММ и разумных границ
    m = re.fullmatch(r"(\d{1,2})[:.\s](\d{2})", time_str)
    if not m:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "⚠️ Неверный формат времени. Напишите время в формате <b>ЧЧ:ММ</b> (например, <code>18:30</code>):",
            reply_markup=kb.cancel_reply_kb(),
        )
        return
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        await send_step_msg(
            state,
            bot,
            message.chat.id,
            "⚠️ Такого времени не существует. Введите корректное время <b>ЧЧ:ММ</b> (00:00–23:59):",
            reply_markup=kb.cancel_reply_kb(),
        )
        return
    time_str = f"{hh:02d}:{mm:02d}"
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
    if message.text.strip() == "❌ Отмена":
        await delete(message)
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
        confirmation = (
            f"🚕 <b>Заказ №{order_id} зарегистрирован!</b>\n\n"
            f"{deliv_note}"
            f"💰 Сумма к оплате: <b>{grand_total:.2f} Br</b> (включая доставку)\n\n"
            "💳 <b>Оплата через Яндекс:</b>\n"
            "При оформлении курьерской доставки доступна только онлайн-оплата через сервис <b>Яндекс Еда / Go</b>.\n\n"
            "Для дальнейшего оформления и оплаты заказа перейдите в сервис Яндекс. После подтверждения оплаты заказ сразу поступит поварам на кухню!"
        )
        await set_order_payment(order_id, "yandex_pending")
        
        yandex_eda = os.getenv("YANDEX_EDA_URL", "https://eda.yandex.by/")
        yandex_cab = os.getenv("YANDEX_DELIVERY_URL", "https://dostavka.yandex.by/")
        markup = kb.yandex_delivery_payment_kb(order_id, yandex_eda, yandex_cab)
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
        markup = kb.payment_method_kb(order_id, pay_url)

    # Очищаем корзину и редактируем сообщение
    await save_cart(state, {})
    await state.set_state(OrderForm.browsing)
    await state.update_data(current_step_msg_id=None)

    await cb.message.edit_text(confirmation, reply_markup=markup)
    if deliv_type == "yandex":
        await cb.message.answer("Быстрые действия:", reply_markup=kb.main_menu())
    await cb.answer("Заказ оформлен")


@router.callback_query(F.data.startswith("yandex_pay_sim:ok:"))
async def cb_yandex_pay_sim_ok(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":")[-1])
    await set_order_payment(order_id, "paid")
    await cb.message.edit_text(
        f"✅ <b>Оплата заказа №{order_id} через сервис Яндекс успешно подтверждена!</b> (Оплачено)\n\n"
        f"Заказ поступил на кухню «ПивДонер». Как только кафе примет заказ, система начнёт поиск водителя Яндекс Go!",
        reply_markup=None,
    )
    await _send_order_to_group(bot, order_id, payment="paid", user_id=cb.from_user.id)
    await cb.answer("Оплата подтверждена")


@router.callback_query(F.data.startswith("yandex_pay_sim:fail:"))
async def cb_yandex_pay_sim_fail(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":")[-1])
    yandex_eda = os.getenv("YANDEX_EDA_URL", "https://eda.yandex.by/")
    await cb.message.edit_text(
        f"⚠️ <b>Оплата заказа №{order_id} в сервисе Яндекс не прошла или была отклонена банком.</b>\n\n"
        f"Заказ пока не передан поварам.\n\n"
        f"<b>Что вы хотите сделать?</b>\n"
        f"• Попробовать оплатить повторно через Яндекс;\n"
        f"• Или переключить заказ на <b>Самовывоз</b> — стоимость доставки спишется, и вы сможете оплатить заказ на месте при получении наличными или картой.",
        reply_markup=kb.yandex_payment_failed_kb(order_id, yandex_eda),
    )
    await cb.answer("Сбой оплаты", show_alert=True)


@router.callback_query(F.data.startswith("yandex_to_pickup:"))
async def cb_yandex_to_pickup(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":")[-1])
    new_total = await switch_order_to_pickup(order_id)
    await _send_order_to_group(bot, order_id, payment="cash", user_id=cb.from_user.id)
    await cb.message.edit_text(
        f"🏃 <b>Заказ №{order_id} переключен на самовывоз!</b>\n\n"
        f"📍 Адрес кафе: <b>{CAFE['address']}</b>\n"
        f"💰 Новая сумма: <b>{new_total:.2f} Br</b> (стоимость доставки исключена)\n"
        f"💵 Оплата: <b>на месте при получении (наличные или карта)</b>\n\n"
        f"Заказ передан поварам на кухню «ПивДонер»!",
        reply_markup=None,
    )
    await cb.answer("Переключено на самовывоз")


@router.callback_query(F.data.startswith("cancel_order_guest:"))
async def cb_cancel_order_guest(cb: CallbackQuery):
    order_id = int(cb.data.split(":")[-1])
    await set_order_cancellation(order_id, "Отменено клиентом (сбой онлайн-оплаты Яндекс)")
    await cb.message.edit_text(
        f"❌ <b>Заказ №{order_id} отменён.</b>\nБудем рады видеть вас снова в «ПивДонер»!",
        reply_markup=None,
    )
    await cb.answer("Заказ отменён")


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
    """Отправляет заказ в группу заведения или гостю в демо-режиме.
    Защита от дублей: если у заказа уже есть карточка в группе — не шлём повторно."""
    order = await get_order(order_id)
    if not order:
        logging.error("Order %s was not found before delivery", order_id)
        return False
    order = dict(order)
    # Идемпотентность: карточка уже отправлена в группу
    if order.get("group_msg_id"):
        logging.info("Order %s already delivered to group (msg %s), skipping duplicate.", order_id, order["group_msg_id"])
        return True
    order["payment"] = payment
    order["status"] = "new"

    chat = user_id if DEMO_MODE else MANAGER_CHAT_ID
    manager_text = make_order_text(order, is_demo=DEMO_MODE)
    manager_kb = kb.status_kb(order_id, status="new", payment=payment, delivery_type=order.get("delivery_type", "pickup"))
    try:
        sent_msg = await bot.send_message(chat, manager_text, reply_markup=manager_kb)
        try:
            await set_order_group_msg(order_id, sent_msg.chat.id, sent_msg.message_id)
        except Exception:
            pass
        # Авто-перевод в «Готовится» через 2.5 мин если повар не нажал сам
        _schedule_auto_cooking(
            bot, order_id, order["user_id"], sent_msg.chat.id, sent_msg.message_id
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

def _is_admin_context(cb: CallbackQuery) -> bool:
    """Разрешает действие только админу или в группе кухни."""
    if DEMO_MODE:
        return True
    if cb.message and cb.message.chat.id == MANAGER_CHAT_ID:
        return True
    return is_admin_user(cb.from_user.id if cb.from_user else 0)


@router.callback_query(F.data.startswith("st:"))
async def cb_status(cb: CallbackQuery, bot: Bot):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни может менять статус заказа.", show_alert=True)
        return
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
        new_kb = kb.status_kb(
            order_id,
            status=status,
            payment=order.get("payment", "none"),
            delivery_type=order.get("delivery_type", "pickup"),
        )
        await cb.message.edit_text(new_text, reply_markup=new_kb)
    except Exception:
        logging.exception("Could not update order card %s after status change", order_id)

    await cb.answer(f"Статус: {text}")

    is_yandex = order.get("delivery_type") == "yandex"
    ready_text = (
        f"🔔 <b>Заказ №{order_id}</b>: 🛍 собран на кухне! Ожидаем курьера Яндекс Go для передачи."
        if is_yandex
        else f"🔔 <b>Заказ №{order_id}</b>: 🛍 ГОТОВ к выдаче!\nЖдём вас на стойке кафе «ПивДонер» ({CAFE['address']})."
    )

    guest_msg = {
        "accepted": f"🔔 <b>Заказ №{order_id}</b>: ✅ принят заведением в работу!\nПовара приступают к приготовлению.",
        "cooking": f"🔔 <b>Заказ №{order_id}</b>: 🔥 готовится поваром!\nПриготовим точно к {order.get('pickup_time', 'скоро')}.",
        "ready": ready_text,
        "to_courier": f"🚗 <b>Заказ №{order_id} передан курьеру Яндекс Go!</b>\nКурьер уже мчит по вашему адресу с горячей едой в термосумке.",
        "completed": (
            f"❤️ <b>Заказ №{order_id} успешно доставлен!</b>\nПриятного аппетита! Ждём вас снова в «ПивДонер»!"
            if is_yandex
            else f"❤️ <b>Заказ №{order_id} выдан!</b>\nПриятного аппетита! Ждём вас снова в «ПивДонер»!"
        ),
        "cancelled": f"❌ <b>Заказ №{order_id} отменён заведением.</b>",
    }.get(status)

    if guest_msg and order.get("user_id"):
        try:
            await bot.send_message(order["user_id"], guest_msg)
        except Exception:
            pass

    # Поиск машины включается ТОЛЬКО когда кафе приняло заказ
    if status == "accepted" and is_yandex:
        asyncio.create_task(
            run_yandex_delivery_simulation(
                bot=bot,
                order_id=order_id,
                user_id=order["user_id"],
                address=order.get("delivery_address") or "ул. Притыцкого, 83",
                admin_chat_id=cb.message.chat.id,
                admin_msg_id=cb.message.message_id,
            )
        )

    if status == "cancelled":
        try:
            cancel_delivery_simulation(order_id)
        except Exception:
            pass

    if status == "completed" and order.get("user_id"):
        schedule_order_review(bot, order_id, order["user_id"], delay_sec=1200)


@router.callback_query(F.data.startswith("st_cancel:"))
async def cb_st_cancel(cb: CallbackQuery):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    order_id = int(cb.data.split(":", 1)[1])
    await cb.message.edit_reply_markup(reply_markup=kb.admin_cancel_reasons_kb(order_id))
    await cb.answer("Укажите причину отмены")


@router.callback_query(F.data.startswith("cancel_r:"))
async def cb_cancel_reason(cb: CallbackQuery, state: FSMContext, bot: Bot):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    parts = cb.data.split(":")
    if len(parts) < 3:
        await cb.answer()
        return
    order_id = int(parts[1])
    code = parts[2]

    order = await get_order(order_id)
    if not order:
        await cb.answer("Заказ не найден", show_alert=True)
        return
    order = dict(order)

    if code == "back":
        original_kb = kb.status_kb(
            order_id,
            status=order.get("status", "new"),
            payment=order.get("payment", "none"),
            delivery_type=order.get("delivery_type", "pickup"),
        )
        await cb.message.edit_reply_markup(reply_markup=original_kb)
        await cb.answer("Отмена действия")
        return

    if code == "custom":
        await state.set_state(AdminCancelForm.waiting_for_reason)
        await state.update_data(
            cancel_order_id=order_id,
            admin_chat_id=cb.message.chat.id,
            admin_msg_id=cb.message.message_id,
        )
        cancel_kb = InlineKeyboardBuilder()
        cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_r:{order_id}:back"))
        await cb.message.answer(
            f"✍️ <b>Введите причину отмены заказа №{order_id} сообщением в чат:</b>\n"
            f"(Она отобразится в отчётах и будет отправлена гостю)",
            reply_markup=cancel_kb.as_markup(),
        )
        await cb.answer()
        return

    reason_text = CANCEL_REASONS.get(code, "Отменено заведением")
    await _apply_admin_cancellation(
        bot=bot,
        order_id=order_id,
        reason=reason_text,
        chat_id=cb.message.chat.id,
        msg_id=cb.message.message_id,
    )
    await cb.answer("Заказ отменён")


@router.message(AdminCancelForm.waiting_for_reason, F.text)
async def admin_got_custom_reason(message: Message, state: FSMContext, bot: Bot):
    if message.text.strip() == "❌ Отмена":
        await state.clear()
        await message.answer("Отмена отклонена.")
        return
    data = await state.get_data()
    order_id = data.get("cancel_order_id")
    chat_id = data.get("admin_chat_id", message.chat.id)
    msg_id = data.get("admin_msg_id")
    await state.clear()

    if not order_id:
        await message.answer("Номер заказа не найден.")
        return

    reason = message.text.strip()
    await _apply_admin_cancellation(
        bot=bot,
        order_id=order_id,
        reason=reason,
        chat_id=chat_id,
        msg_id=msg_id,
    )
    await message.answer(f"✅ Заказ №{order_id} отменён с причиной:\n«{reason}»")


async def _apply_admin_cancellation(bot: Bot, order_id: int, reason: str, chat_id: int, msg_id: int = None):
    """Применяет отмену заказа с сохранением причины, остановкой курьера и уведомлением гостя."""
    await set_order_cancellation(order_id, reason)
    try:
        cancel_delivery_simulation(order_id)
    except Exception:
        pass

    order = await get_order(order_id)
    if not order:
        return
    order = dict(order)
    order["status"] = "cancelled"
    order["cancellation_reason"] = reason

    if msg_id:
        try:
            new_text = make_order_text(order, is_demo=DEMO_MODE)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=new_text,
                reply_markup=None,
            )
        except Exception:
            pass

    user_id = order.get("user_id")
    if user_id:
        try:
            refund_note = (
                "\n\n💳 <i>Если заказ был оплачен онлайн через Яндекс, деньги будут автоматически возвращены на вашу карту.</i>"
                if order.get("delivery_type") == "yandex"
                else ""
            )
            await bot.send_message(
                user_id,
                f"❌ <b>Заказ №{order_id} отменён заведением.</b>\n\n"
                f"Причина: <b>{reason}</b>\n\n"
                f"Приносим искренние извинения за доставленные неудобства!{refund_note}"
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("payok:"))
async def cb_payok(cb: CallbackQuery, bot: Bot):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни может подтверждать оплату.", show_alert=True)
        return
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


@router.message(Command(commands=["active", "orders"]))
@router.message(F.text.in_({"📋 Активные заказы", "Активные заказы"}))
async def cmd_group_active(message: Message):
    if not is_admin_user(message.from_user.id) and message.chat.id != MANAGER_CHAT_ID:
        await message.answer("⚠️ Данный раздел доступен только персоналу кафе.")
        return
    orders = await get_active_orders()
    if not orders:
        await message.answer("📋 <b>На кухне нет активных заказов.</b>\nВсе заказы выданы или завершены!")
        return
    text = f"📋 <b>Активные заказы в работе ({len(orders)} шт):</b>\n\n"
    for row in orders:
        o = dict(row)
        pay = PAYMENT_TEXT.get(o.get("payment", "none"), o.get("payment", "none"))
        st = STATUS_TEXT.get(o.get("status", "new"), o.get("status", "new"))
        deliv = "🚕 Яндекс Доставка" if o.get("delivery_type") == "yandex" else "🏃 Самовывоз"
        text += (
            f"<b>Заказ №{o['id']}</b> ({deliv})\n"
            f"⏱ {o.get('pickup_time', '')} · 💰 {o.get('total', 0.0):.2f} Br\n"
            f"📌 {st} · 💳 {pay}\n"
            f"🛒 {o.get('items', '')}\n\n"
        )
    await message.answer(text)


@router.message(Command("report"))
async def cmd_group_report(message: Message):
    if not is_admin_user(message.from_user.id) and message.chat.id != MANAGER_CHAT_ID:
        await message.answer("⚠️ Данный раздел доступен только персоналу кафе.")
        return
    text = await _report_text()
    await message.answer(text)


@router.message(Command("excel"))
@router.message(F.text.in_({"📑 Экспорт в Excel", "Экспорт в Excel"}))
async def cmd_group_excel(message: Message, bot: Bot):
    if not is_admin_user(message.from_user.id) and message.chat.id != MANAGER_CHAT_ID:
        await message.answer("⚠️ Данный раздел доступен только персоналу кафе.")
        return
    try:
        from excel_report import generate_excel_report
        file_path = await generate_excel_report()
        from aiogram.types import FSInputFile
        doc = FSInputFile(file_path, filename=os.path.basename(file_path))
        await bot.send_document(
            message.chat.id,
            doc,
            caption="📑 <b>Сводный отчёт по заказам кафе «ПивДонер» (.xlsx)</b>",
        )
    except Exception as e:
        await message.answer(f"⚠️ Ошибка формирования отчёта: {e}")


@router.message(Command("id"))
async def cmd_show_id(message: Message):
    await message.answer(
        f"ℹ️ <b>Информация о чате:</b>\n"
        f"• ID чата: <code>{message.chat.id}</code>\n"
        f"• Тип: <b>{message.chat.type}</b>\n"
        f"• Ваш ID: <code>{message.from_user.id}</code>"
    )


# ---------- Панель администратора ----------

@router.callback_query(F.data == "admin_active")
async def cb_admin_active(cb: CallbackQuery):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    orders = await get_active_orders()
    if not orders:
        text = (
            "📋 <b>На данный момент нет активных заказов.</b>\n\n"
            "Все завершённые и архивные заказы можно посмотреть в <b>📊 Отчёте за сегодня</b> или выгрузить в Excel."
        )
    else:
        text = "📋 <b>Активные заказы в работе:</b>\n\n"
        for row in orders:
            o = dict(row)
            pay = PAYMENT_TEXT.get(o.get("payment", "none"), o.get("payment", "none"))
            st = STATUS_TEXT.get(o.get("status", "new"), o.get("status", "new"))
            deliv = "🚕 Яндекс" if o.get("delivery_type") == "yandex" else "🏃 Самовывоз"
            text += (
                f"<b>Заказ №{o['id']}</b> ({deliv})\n"
                f"⏱ Время: {o.get('pickup_time', '')} · 💰 {o.get('total', 0.0):.2f} Br\n"
                f"📌 Статус: <b>{st}</b> · 💳 {pay}\n"
                f"🛒 Блюда: {o.get('items', '')}\n\n"
            )
    await cb.message.answer(text, reply_markup=kb.admin_kb())
    await cb.answer()


# ---------- Управление стоп-листом кухни (Задачи кухни) ----------

async def _render_stop_list_view(target, edit: bool = True):
    stop_list = await get_stop_list()
    if not stop_list:
        text = (
            "⛔ <b>Стоп-лист кухни «ПивДонер»</b>\n\n"
            "🟢 Сейчас на стопе <b>нет позиций</b>.\n"
            "Все блюда меню и добавки доступны для заказа гостями!\n\n"
            "Чтобы поставить блюдо или добавку на стоп, выберите кнопку ниже:"
        )
        markup = kb.admin_stop_menu_kb(has_stopped=False)
    else:
        text = f"⛔ <b>Текущий стоп-лист кухни ({len(stop_list)} поз.):</b>\n\n"
        for item_id, info in stop_list.items():
            name = info.get("item_name") or ITEMS.get(item_id, {}).get("name") or TOPPINGS_MAP.get(item_id, {}).get("name", item_id)
            itype = "🌯 Блюдо" if info.get("item_type") == "dish" else "🧀 Добавка"
            reason = info.get("reason", "Причина не указана")
            dt = (info.get("created_at") or "")[:16].replace("T", " ")
            text += f"• <b>{name}</b> ({itype})\n  Причина: <i>{reason}</i>\n  Поставлен: {dt}\n\n"
        text += "<i>Гости видят эти позиции с пометкой (СТОП) и не могут их заказать.</i>"
        markup = kb.admin_stop_menu_kb(has_stopped=True)

    if edit and isinstance(target, CallbackQuery):
        await safe_edit(target, text, reply_markup=markup)
    elif isinstance(target, CallbackQuery):
        await target.message.answer(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.message(Command(commands=["stop", "stoplist"]))
@router.message(F.text.in_({"⛔ Стоп-лист кухни", "Стоп-лист кухни", "Стоп-лист"}))
async def cmd_admin_stop(message: Message):
    if not is_admin_user(message.from_user.id) and message.chat.id != MANAGER_CHAT_ID:
        await message.answer("⚠️ Данный раздел доступен только администраторам кухни.")
        return
    await _render_stop_list_view(message, edit=False)


@router.callback_query(F.data.in_({"admin_stop_list", "stop_list_refresh"}))
async def cb_admin_stop_list(cb: CallbackQuery):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    await _render_stop_list_view(cb, edit=True)
    await cb.answer()


@router.callback_query(F.data == "stop_add_dish")
async def cb_stop_add_dish(cb: CallbackQuery):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    stop_list = await get_stop_list()
    await safe_edit(
        cb,
        "⛔ <b>Постановка БЛЮДА на стоп</b>\n\n"
        "Выберите блюдо, которое закончилось или временно не готовится:",
        reply_markup=kb.admin_stop_choose_dish_kb(stop_list),
    )
    await cb.answer()


@router.callback_query(F.data == "stop_add_top")
async def cb_stop_add_top(cb: CallbackQuery):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    stop_list = await get_stop_list()
    await safe_edit(
        cb,
        "⛔ <b>Постановка ДОБАВКИ на стоп</b>\n\n"
        "Выберите добавку к шаурме, которая закончилась:",
        reply_markup=kb.admin_stop_choose_top_kb(stop_list),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("stop_pick:"))
async def cb_stop_pick(cb: CallbackQuery):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    parts = cb.data.split(":")
    itype = parts[1]
    item_id = parts[2]
    if itype == "dish":
        name = ITEMS.get(item_id, {}).get("name", item_id)
    else:
        name = TOPPINGS_MAP.get(item_id, {}).get("name", item_id)

    await safe_edit(
        cb,
        f"⛔ <b>Причина постановки на стоп</b>\n\n"
        f"Позиция: <b>{name}</b>\n\n"
        "Укажите причину для гостей и отчётов:",
        reply_markup=kb.admin_stop_reason_kb(item_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("stop_set_r:"))
async def cb_stop_set_reason(cb: CallbackQuery, state: FSMContext):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    parts = cb.data.split(":")
    item_id = parts[1]
    reason_code = parts[2]
    itype = "top" if item_id in TOPPINGS_MAP else "dish"
    name = TOPPINGS_MAP[item_id]["name"] if itype == "top" else ITEMS.get(item_id, {}).get("name", item_id)

    if reason_code == "custom":
        await state.set_state(AdminStopForm.waiting_for_reason)
        await state.update_data(stop_item_id=item_id, stop_item_type=itype, stop_item_name=name)
        await safe_edit(
            cb,
            f"✍️ <b>Введите свою причину постановки на стоп</b> для позиции <b>{name}</b>:\n\n"
            "Напишите текст причины ответным сообщением (гость увидит его при попытке заказать):",
            reply_markup=kb.cancel_reply_kb(),
        )
        await cb.answer()
        return

    reason = STOP_REASONS.get(reason_code, "Временно закончилось на кухне")
    await add_to_stop_list(item_id=item_id, item_name=name, item_type=itype, reason=reason)

    await safe_edit(
        cb,
        f"✅ <b>Позиция поставлена на стоп!</b>\n\n"
        f"⛔ <b>{name}</b>\n"
        f"💬 Причина: <i>{reason}</i>\n\n"
        "Гости увидят предупреждение с этой причиной и не смогут сделать заказ.",
        reply_markup=kb.admin_stop_menu_kb(has_stopped=True),
    )
    await cb.answer("Позиция на стопе")


@router.message(AdminStopForm.waiting_for_reason, F.text)
async def admin_got_stop_reason(message: Message, state: FSMContext):
    if message.text.strip() == "❌ Отмена":
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await message.answer("Постановка на стоп отменена.", reply_markup=kb.admin_kb())
        return

    custom_reason = message.text.strip()
    data = await state.get_data()
    item_id = data.get("stop_item_id")
    itype = data.get("stop_item_type", "dish")
    name = data.get("stop_item_name") or (TOPPINGS_MAP[item_id]["name"] if itype == "top" else ITEMS.get(item_id, {}).get("name", item_id))

    await add_to_stop_list(item_id=item_id, item_name=name, item_type=itype, reason=custom_reason)
    await state.clear()
    await state.set_state(OrderForm.browsing)

    await message.answer(
        f"✅ <b>Позиция поставлена на стоп!</b>\n\n"
        f"⛔ <b>{name}</b>\n"
        f"💬 Причина: <i>{custom_reason}</i>\n\n"
        "Гости увидят предупреждение с этой причиной и не смогут сделать заказ.",
        reply_markup=kb.admin_stop_menu_kb(has_stopped=True),
    )


@router.callback_query(F.data == "stop_unstop_menu")
async def cb_stop_unstop_menu(cb: CallbackQuery):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    stop_list = await get_stop_list()
    if not stop_list:
        await cb.message.edit_text(
            "🟢 Сейчас на стопе нет позиций.",
            reply_markup=kb.admin_stop_menu_kb(has_stopped=False),
        )
        await cb.answer()
        return

    await safe_edit(
        cb,
        "🟢 <b>Снятие со стопа</b>\n\n"
        "Нажмите на позицию, которую хотите вернуть в продажу:",
        reply_markup=kb.admin_stop_unstop_kb(stop_list),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("stop_unstop_do:"))
async def cb_stop_unstop_do(cb: CallbackQuery):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    item_id = cb.data.split(":", 1)[1]
    name = TOPPINGS_MAP.get(item_id, {}).get("name") or ITEMS.get(item_id, {}).get("name", item_id)
    await remove_from_stop_list(item_id)
    stop_list = await get_stop_list()

    await safe_edit(
        cb,
        f"🟢 <b>Позиция возвращена в продажу!</b>\n\n"
        f"«<b>{name}</b>» снова доступна для заказа гостями в меню.",
        reply_markup=kb.admin_stop_menu_kb(has_stopped=bool(stop_list)),
    )
    await cb.answer("Снято со стопа")


# ---------- Информация о заведении и оперативная сводка ----------

async def make_establishment_info_text() -> str:
    stats = await get_establishment_dashboard()
    stop_list = await get_stop_list()

    st_cnt = stats["status_counts"]
    accepted_all = stats["accepted_total"]
    cancelled_cnt = stats["cancelled_count"]

    if not stop_list:
        stop_str = "🟢 <b>Стоп-лист кухни пуст</b> — все блюда и ингредиенты в наличии!"
    else:
        stop_lines = []
        for iid, info in list(stop_list.items())[:6]:
            name = info.get("item_name", iid)
            reason = info.get("reason", "Закончилось на кухне")
            stop_lines.append(f"• ⛔ <b>{name}</b> (<i>{reason}</i>)")
        if len(stop_list) > 6:
            stop_lines.append(f"<i>...и ещё {len(stop_list) - 6} позиций</i>")
        stop_str = "\n".join(stop_lines)

    cancel_info_str = f"• ❌ <b>Отменённых заказов: {cancelled_cnt} шт.</b>"
    if stats["cancelled_reasons"]:
        reason_counts = {}
        for r in stats["cancelled_reasons"]:
            reason_counts[r] = reason_counts.get(r, 0) + 1
        reasons_list = [f"{k}: {v}" for k, v in reason_counts.items()]
        cancel_info_str += f"\n  └ <i>Причины: {', '.join(reasons_list)}</i>"

    text = (
        f"ℹ️ <b>ОПЕРАТИВНАЯ СВОДКА И ИНФОРМАЦИЯ О ЗАВЕДЕНИИ</b>\n\n"
        f"🏪 <b>Кафе:</b> «{CAFE['name']}» (быстрое питание, донеры на гриле)\n"
        f"📍 <b>Адрес кафе:</b> {CAFE['address']}\n"
        f"🕐 <b>Время работы кухни:</b> {CAFE['hours']}\n"
        f"📞 <b>Контакты заведения:</b> {CAFE['phone']}\n"
        f"🟢 <b>Статус заведения:</b> Кухня открыта и принимает предзаказы\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>АКТУАЛЬНАЯ СТАТИСТИКА ЗА СЕГОДНЯ:</b>\n"
        f"• 📥 Всего заказов за смену: <b>{stats['total_today_orders']} шт.</b>\n"
        f"• ✅ <b>Принятых заказов: {accepted_all} шт.</b>\n"
        f"  └ 🔥 Готовятся / готовы: <b>{st_cnt['cooking'] + st_cnt['ready'] + st_cnt['to_courier']} шт.</b>\n"
        f"  └ 🏁 Выдано клиентам: <b>{st_cnt['completed']} шт.</b>\n"
        f"{cancel_info_str}\n"
        f"• 💰 <b>Выручка за сегодня: {stats['total_revenue']:.2f} Br</b>\n"
        f"  └ 💳 Онлайн: {stats['paid_online']} | 💵 На месте: {stats['paid_cash']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⛔ <b>АКТУАЛЬНЫЙ СТОП-ЛИСТ КУХНИ ({len(stop_list)} поз.):</b>\n"
        f"{stop_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>АКТУАЛЬНЫЕ НОВОСТИ ЗАВЕДЕНИЯ:</b>\n"
        f"• Панель администратора переведена в строгий режим управления.\n"
        f"• Все кнопки гостя скрыты из панели администратора.\n"
        f"• Контроль стоп-листа с фиксацией причин в режиме реального времени.\n"
        f"• Автоматическая печать кухонных чеков и выгрузка Excel-отчётов активны."
    )
    return text


@router.message(Command(commands=["info", "status", "dashboard", "cafe"]))
@router.message(F.text.contains("Информация о заведении"))
@router.message(F.text.in_({"ℹ️ Информация о заведении", "Информация о заведении", "ℹ️ Информация", "/cafe", "/dashboard"}))
@router.callback_query(F.data == "admin_cafe_info")
async def show_establishment_info(event: Message | CallbackQuery):
    if isinstance(event, CallbackQuery) and not _is_admin_context(event):
        await event.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    text = await make_establishment_info_text()
    markup = kb.admin_cafe_info_kb()
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=markup)
        except Exception:
            # Сообщение могло быть без текста (фото/документ) — шлём новое
            await event.message.answer(text, reply_markup=markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


@router.callback_query(F.data == "admin_help")
async def cb_admin_help(cb: CallbackQuery, bot: Bot):
    await delete(cb.message)
    await send_and_pin_instruction(cb.message.chat.id, bot)
    await cb.answer("Инструкция закреплена")


@router.message(F.text.in_({"📖 Инструкция", "📖 Инструкция к боту", "Инструкция к боту", "Инструкция", "/instruction", "/guide"}))
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
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    await cb.message.answer(await _report_text(), reply_markup=kb.admin_kb())
    await cb.answer()


@router.message(Command("report"))
@router.message(F.text.in_({"📊 Отчёт за сегодня", "Отчёт за сегодня"}))
async def cmd_report(message: Message):
    await message.answer(await _report_text(), reply_markup=kb.admin_kb())


@router.message(F.text.in_({"⚙️ Панель администратора", "Панель администратора", "/admin"}))
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin_user(message.from_user.id) and message.chat.id != MANAGER_CHAT_ID:
        await message.answer("⚠️ Данный раздел доступен только администраторам кафе.")
        return
    await message.answer(
        "⚙️ <b>Панель администратора кафе «ПивДонер»</b>\n\n"
        "Выберите раздел для управления кухней и заказами:",
        reply_markup=kb.admin_reply_menu(),
    )
    await message.answer("Панель быстрого доступа:", reply_markup=kb.admin_kb())


@router.message(F.text.in_({"🔍 Поиск заказов по номеру", "Поиск заказов по номеру", "Поиск по номеру"}))
async def msg_search_phone_btn(message: Message, state: FSMContext, bot: Bot):
    await state.set_state(AdminSearchForm.waiting_for_phone)
    await send_step_msg(
        state,
        bot,
        message.chat.id,
        "🔍 <b>Поиск истории заказов гостя по номеру телефона</b>\n\n"
        "Введите номер телефона гостя (например: <code>+375 29 123-45-67</code> или фрагмент номера):",
        reply_markup=kb.admin_cancel_search_kb(),
    )


# ---------- Поиск заказов по номеру телефона для администратора ----------

@router.callback_query(F.data == "admin_search_phone")
async def cb_admin_search_phone(cb: CallbackQuery, state: FSMContext, bot: Bot):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
    await state.set_state(AdminSearchForm.waiting_for_phone)
    await send_step_msg(
        state,
        bot,
        cb.message.chat.id,
        "🔍 <b>Поиск истории заказов гостя по номеру телефона</b>\n\n"
        "Введите номер телефона гостя (например: <code>+375 29 123-45-67</code> или фрагмент номера):",
        reply_markup=kb.admin_cancel_search_kb(),
    )
    await cb.answer()


@router.callback_query(F.data == "admin_cancel_search")
async def cb_admin_cancel_search(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await cleanup_step_msg(state, bot, cb.message.chat.id)
    await state.clear()
    await state.set_state(OrderForm.browsing)
    await delete(cb.message)
    await cb.answer("Поиск отменён.")


@router.callback_query(F.data == "admin_menu")
async def cb_admin_menu(cb: CallbackQuery):
    await cb.message.answer("⚙️ <b>Панель администратора</b>", reply_markup=kb.admin_kb())
    await cb.answer()


@router.message(AdminSearchForm.waiting_for_phone, F.text)
async def admin_got_phone_search(message: Message, state: FSMContext, bot: Bot):
    if message.text.strip() in ("❌ Отмена", "/cancel", "Отмена", "❌ Отменить поиск"):
        await cleanup_step_msg(state, bot, message.chat.id)
        await state.clear()
        await state.set_state(OrderForm.browsing)
        await message.answer("Поиск отменён.", reply_markup=kb.admin_reply_menu())
        return

    query = message.text.strip()
    await cleanup_step_msg(state, bot, message.chat.id)
    await state.clear()
    await state.set_state(OrderForm.browsing)
    await _show_admin_search_results(message.chat.id, bot, query)


@router.message(AdminSearchForm.waiting_for_phone, F.contact)
async def admin_got_contact_search(message: Message, state: FSMContext, bot: Bot):
    query = message.contact.phone_number
    await cleanup_step_msg(state, bot, message.chat.id)
    await state.clear()
    await state.set_state(OrderForm.browsing)
    await _show_admin_search_results(message.chat.id, bot, query)


def is_phone_number_query(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if t.startswith("/"):
        return False
    menu_keywords = ["панель", "информация", "активные", "стоп-лист", "отчёт", "экспорт", "рассылк", "поиск", "инструкция", "меню", "корзина", "отмена", "кафе", "доставка"]
    t_lower = t.lower()
    if any(k in t_lower for k in menu_keywords):
        return False
    clean = re.sub(r"[\s\-\(\)\+\.]", "", t)
    if not clean.isdigit():
        return False
    return 7 <= len(clean) <= 13


@router.message(F.text.func(is_phone_number_query))
async def msg_admin_any_phone(message: Message, state: FSMContext, bot: Bot):
    is_admin = is_admin_user(message.from_user.id)
    is_group = (message.chat.type in ('group', 'supergroup') or message.chat.id == MANAGER_CHAT_ID)
    if not is_admin and not is_group:
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
            reply_markup=kb.admin_cancel_search_kb(),
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
    for row in orders:
        o = dict(row)
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

    messages_to_send = []
    current_chunk = header
    for card in lines[1:]:
        if len(current_chunk) + len(card) + 2 > 3500:
            messages_to_send.append(current_chunk)
            current_chunk = card
        else:
            current_chunk += "\n" + card
    if current_chunk:
        messages_to_send.append(current_chunk)

    for idx, msg_text in enumerate(messages_to_send):
        markup = kb.admin_search_again_kb() if idx == len(messages_to_send) - 1 else None
        await bot.send_message(chat_id, msg_text, reply_markup=markup)


# ---------- Функция 1: Автоматическая печать чеков на кухне (58/80 мм) ----------

@router.callback_query(F.data.startswith("receipt:"))
async def cb_print_receipt(cb: CallbackQuery, bot: Bot):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
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
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
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
            f"📊 <b>Отчёт по заказам и выручке кафе «ПивДонер»</b>\n\n"
            f"📦 Всего заказов в файле: <b>{len(orders)}</b>\n"
            f"💰 Общая выручка: <b>{total_rev:.2f} Br</b>\n\n"
            f"Таблица оформлена со стилями, формулами и авто-шириной колонок."
        ),
        reply_markup=kb.admin_kb(),
    )


# ---------- Рейтинг и отзывы заведения (NPS) ----------

@router.callback_query(F.data == "admin_reviews_stats")
async def cb_admin_reviews_stats(cb: CallbackQuery):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только персонал кухни.", show_alert=True)
        return
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

    await safe_edit(cb, text, reply_markup=kb.admin_kb())
    await cb.answer()


# ---------- Функция 3: Таргетированная рассылка от владельца ----------

@router.message(F.text.in_({"📢 Сделать рассылку", "/broadcast"}))
async def msg_start_broadcast(message: Message, state: FSMContext):
    if not is_admin_user(message.from_user.id) and message.chat.id != MANAGER_CHAT_ID:
        await message.answer("⚠️ Данная функция доступна только владельцу и администраторам кафе.")
        return
    await state.set_state(BroadcastForm.waiting_for_content)
    await message.answer(
        "📢 <b>Таргетированная рассылка от владельца</b>\n\n"
        "Отправьте текст акции или спецпредложения (можно с прикреплённой фотографией).\n\n"
        "<i>Пример: «🔥 Только в эти выходные: при заказе любого Донера — картофель фри в подарок по промокоду ПИВФРИ!»</i>",
        reply_markup=kb.cancel_reply_kb(),
    )


@router.callback_query(F.data == "admin_broadcast")
async def cb_start_broadcast(cb: CallbackQuery, state: FSMContext):
    if not _is_admin_context(cb):
        await cb.answer("⚠️ Только администратор.", show_alert=True)
        return
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
    users = await get_all_users(subscribed_only=True)
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
    users = await get_all_users(subscribed_only=True)
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
    users = await get_all_users(subscribed_only=True)

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

def schedule_order_review(bot: Bot, order_id: int, user_id: int, delay_sec: int = 1200):
    """Планирует опрос качества заказа (NPS) спустя 20 минут ПОСЛЕ подтверждения выдачи/доставки."""
    async def _job():
        await asyncio.sleep(delay_sec)
        order = await get_order(order_id)
        # Отправляем опрос ТОЛЬКО если заказ был подтверждён как выдан (completed) и не отменён
        if not order or order.get("status") != "completed":
            return
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

    # Защита: оценить можно только свой заказ и только один раз
    order = await get_order(order_id)
    if not order or order.get("user_id") != user_id:
        await cb.answer("⚠️ Этот опрос относится к чужому заказу.", show_alert=True)
        return
    if await has_review_for_order(order_id, user_id):
        await cb.answer("Вы уже оценили этот заказ. Спасибо!", show_alert=True)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

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
        "💡 Функция Mini App вынесена на отдельное тестирование в специальном боте.",
        reply_markup=kb.main_menu(),
    )
