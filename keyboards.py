from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import WEBAPP_URL
from menu import ITEMS, MENU, fmt_price


def main_menu(is_admin_or_demo: bool = True) -> ReplyKeyboardMarkup:
    """Постоянная панель быстрых действий (кнопки под строкой ввода)."""
    buttons = [
        [KeyboardButton(text="🛒 Оформить заказ")],
        [KeyboardButton(text="🍔 Меню"), KeyboardButton(text="🧺 Корзина")],
        [KeyboardButton(text="👤 Личный кабинет"), KeyboardButton(text="📜 Мои заказы")],
        [KeyboardButton(text="📍 Адрес и инфо"), KeyboardButton(text="🎲 Игра с бонусами")],
        [KeyboardButton(text="🚨 Подать жалобу")],
    ]
    if is_admin_or_demo:
        buttons.append([
            KeyboardButton(text="📢 Сделать рассылку"),
            KeyboardButton(text="⚙️ Панель администратора"),
        ])
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        is_persistent=True,
    )


def phone_request_kb() -> ReplyKeyboardMarkup:
    """Клавиатура запроса номера телефона для подтверждения (СМС/контакт через Telegram)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Подтвердить номер через Telegram", request_contact=True)],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def cancel_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def quick_actions_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🛒 Оформить заказ", callback_data="quick_order"))
    kb.row(
        InlineKeyboardButton(text="🍔 Меню", callback_data="menu"),
        InlineKeyboardButton(text="🧺 Корзина", callback_data="cart"),
    )
    kb.row(
        InlineKeyboardButton(text="👤 Личный кабинет", callback_data="quick_profile"),
        InlineKeyboardButton(text="📜 Мои заказы", callback_data="quick_history"),
    )
    return kb.as_markup()


def profile_kb(is_verified: bool = True) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if is_verified:
        kb.row(
            InlineKeyboardButton(text="✏️ Изменить имя", callback_data="profile_edit_name"),
            InlineKeyboardButton(text="📱 Сменить телефон", callback_data="profile_edit_phone"),
        )
    else:
        kb.row(
            InlineKeyboardButton(text="🔐 Подтвердить номер телефона", callback_data="start_reg"),
        )
    kb.row(
        InlineKeyboardButton(text="🎁 Реферальная ссылка («Пригласи друга»)", callback_data="referral_link")
    )
    kb.row(
        InlineKeyboardButton(text="📜 История заказов", callback_data="quick_history"),
        InlineKeyboardButton(text="🎲 Сыграть в кубик", callback_data="dice_menu"),
    )
    kb.row(
        InlineKeyboardButton(text="🚨 Подать жалобу администратору", callback_data="make_complaint"),
    )
    kb.row(
        InlineKeyboardButton(text="🛒 Сделать заказ", callback_data="quick_order"),
        InlineKeyboardButton(text="🍔 Меню", callback_data="menu"),
    )
    return kb.as_markup()


def info_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🚨 Написать жалобу / отзыв", callback_data="make_complaint"))
    kb.row(InlineKeyboardButton(text="🍔 Открыть меню", callback_data="menu"))
    return kb.as_markup()


def delivery_choice_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🚕 Яндекс Доставка (курьер)", callback_data="deliv:yandex"))
    kb.row(InlineKeyboardButton(text="🏃 Самовывоз (ул. Одинцова, 20)", callback_data="deliv:pickup"))
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return kb.as_markup()


def address_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геопозицию", request_location=True)],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def order_phone_choice_kb(saved_phone: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=f"✅ Использовать {saved_phone}", callback_data="use_saved_phone"))
    kb.row(InlineKeyboardButton(text="✍️ Указать другой номер", callback_data="enter_new_phone"))
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return kb.as_markup()


def categories_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat in MENU:
        kb.row(InlineKeyboardButton(text=cat, callback_data=f"cat:{cat}"))
    kb.row(InlineKeyboardButton(text="🧺 Корзина", callback_data="cart"))
    return kb.as_markup()


def items_kb(cat: str, cart: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for item in MENU[cat]:
        qty = cart.get(item["id"], 0)
        label = f"{item['name']} — {fmt_price(item['price'])}"
        if qty:
            label += f"  ✓{qty}"
        kb.row(InlineKeyboardButton(text=label, callback_data=f"item:{item['id']}"))
    kb.row(
        InlineKeyboardButton(text="⬅️ Категории", callback_data="menu"),
        InlineKeyboardButton(text="🧺 Корзина", callback_data="cart"),
    )
    return kb.as_markup()


def item_kb(item_id: str, qty: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="➖", callback_data=f"dec:{item_id}"),
        InlineKeyboardButton(text=f"{qty} шт", callback_data="noop"),
        InlineKeyboardButton(text="➕", callback_data=f"inc:{item_id}"),
    )
    if item_id.startswith("doner_") or "Донер" in ITEMS.get(item_id, {}).get("category", ""):
        kb.row(
            InlineKeyboardButton(text="🧀 Добавить добавки к шаурме", callback_data="cat:🧀 Добавки в шаурму"),
        )
    kb.row(
        InlineKeyboardButton(text="⬅️ Назад в категорию", callback_data=f"cat:{ITEMS[item_id]['category']}"),
        InlineKeyboardButton(text="🧺 В корзину", callback_data="cart"),
    )
    return kb.as_markup()


def cart_kb(cart: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for iid, qty in cart.items():
        item = ITEMS[iid]
        kb.row(
            InlineKeyboardButton(text="➖", callback_data=f"cdec:{iid}"),
            InlineKeyboardButton(text=f"{item['name']} ×{qty}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"cinc:{iid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"cdel:{iid}"),
        )
    kb.row(InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout"))
    kb.row(
        InlineKeyboardButton(text="⬅️ В меню", callback_data="menu"),
        InlineKeyboardButton(text="🗑 Очистить", callback_data="clear_cart"),
    )
    return kb.as_markup()


def empty_cart_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🍔 В меню", callback_data="menu"))
    return kb.as_markup()


def pickup_time_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="Как можно скорее", callback_data="time:asap"),
        InlineKeyboardButton(text="Через 20 мин", callback_data="time:+20"),
    )
    kb.row(
        InlineKeyboardButton(text="Через 40 мин", callback_data="time:+40"),
        InlineKeyboardButton(text="Через час", callback_data="time:+60"),
    )
    kb.row(InlineKeyboardButton(text="✍️ Указать своё время", callback_data="time:custom"))
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return kb.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    return kb.as_markup()


def payment_method_kb(order_id: int, pay_url: str) -> InlineKeyboardMarkup:
    """Выбор способа оплаты после подтверждения заказа (для самовывоза)."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Оплатить онлайн", url=pay_url))
    kb.row(InlineKeyboardButton(text="✅ Я оплатил онлайн", callback_data=f"paid:{order_id}"))
    kb.row(InlineKeyboardButton(text="💵 Оплачу на месте", callback_data=f"pay_cash:{order_id}"))
    return kb.as_markup()


def yandex_delivery_payment_kb(eda_url: str, delivery_cab_url: str) -> InlineKeyboardMarkup:
    """Оплата и оформление курьерской доставки через Яндекс (только онлайн-переход, без лишних кнопок)."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Оплатить в Яндекс Еде / Go", url=eda_url))
    kb.row(InlineKeyboardButton(text="🚚 Кабинет Яндекс Доставки", url=delivery_cab_url))
    return kb.as_markup()


def status_kb(order_id: int, status: str = "new", payment: str = "none") -> InlineKeyboardMarkup:
    """Последовательные кнопки управления заказом для администратора/повара."""
    kb = InlineKeyboardBuilder()

    if status == "new":
        kb.row(InlineKeyboardButton(text="✅ Принять заказ", callback_data=f"st:{order_id}:accepted"))
        kb.row(InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"st:{order_id}:cancelled"))
    elif status == "accepted":
        kb.row(InlineKeyboardButton(text="🔥 Начать готовить", callback_data=f"st:{order_id}:cooking"))
        kb.row(
            InlineKeyboardButton(text="🛍 Сразу готов", callback_data=f"st:{order_id}:ready"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"st:{order_id}:cancelled"),
        )
    elif status == "cooking":
        kb.row(InlineKeyboardButton(text="🛍 Заказ готов!", callback_data=f"st:{order_id}:ready"))
        kb.row(InlineKeyboardButton(text="❌ Отменить", callback_data=f"st:{order_id}:cancelled"))
    elif status == "ready":
        kb.row(InlineKeyboardButton(text="🏁 Выдан гостю (Завершить)", callback_data=f"st:{order_id}:completed"))

    if payment != "paid" and status not in ("completed", "cancelled"):
        kb.row(InlineKeyboardButton(text="💰 Оплата подтверждена", callback_data=f"payok:{order_id}"))

    # Кнопка печати кухонного чека (58/80мм)
    kb.row(InlineKeyboardButton(text="🖨 Печать чека (58/80мм)", callback_data=f"receipt:{order_id}"))

    return kb.as_markup()


def after_order_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🛒 Новый заказ", callback_data="menu"))
    kb.row(
        InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile"),
        InlineKeyboardButton(text="🎮 Игра", callback_data="dice_menu"),
    )
    return kb.as_markup()


def admin_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔍 Поиск заказов по номеру", callback_data="admin_search_phone"))
    kb.row(
        InlineKeyboardButton(text="📊 Отчёт за сегодня", callback_data="admin_report"),
        InlineKeyboardButton(text="⭐ Рейтинг и отзывы", callback_data="admin_reviews_stats"),
    )
    kb.row(
        InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin_broadcast"),
        InlineKeyboardButton(text="📑 Экспорт в Excel", callback_data="admin_export_excel"),
    )
    kb.row(
        InlineKeyboardButton(text="📋 Активные заказы", callback_data="admin_active"),
        InlineKeyboardButton(text="📖 Инструкция", callback_data="admin_help"),
    )
    return kb.as_markup()


def admin_search_again_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔍 Искать другой номер", callback_data="admin_search_phone"))
    kb.row(InlineKeyboardButton(text="⚙️ Меню администратора", callback_data="admin_menu"))
    return kb.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📢 Да, отправить всем", callback_data="broadcast:send"))
    kb.row(InlineKeyboardButton(text="❌ Отменить рассылку", callback_data="broadcast:cancel"))
    return kb.as_markup()


def review_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="⭐ 1", callback_data=f"review:{order_id}:1"),
        InlineKeyboardButton(text="⭐ 2", callback_data=f"review:{order_id}:2"),
        InlineKeyboardButton(text="⭐ 3", callback_data=f"review:{order_id}:3"),
        InlineKeyboardButton(text="⭐ 4", callback_data=f"review:{order_id}:4"),
        InlineKeyboardButton(text="⭐ 5", callback_data=f"review:{order_id}:5"),
    )
    return kb.as_markup()


def review_high_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⭐ Оставить отзыв на Яндекс Картах", url="https://yandex.by/maps/org/pivdoner/154443905584/"))
    kb.row(InlineKeyboardButton(text="🎁 Забрать +2.00 Br бонусов", callback_data=f"review_bonus:{order_id}"))
    return kb.as_markup()


def webapp_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🚀 Открыть Mini App витрину", web_app=WebAppInfo(url=WEBAPP_URL)))
    return kb.as_markup()


def dice_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎲 Бросить кубик", callback_data="dice"))
    return kb.as_markup()
