from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from menu import MENU, ITEMS, fmt_price


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Оформить предзаказ")],
            [KeyboardButton(text="🍔 Меню"), KeyboardButton(text="🧺 Корзина")],
            [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📜 История заказов")],
            [KeyboardButton(text="🎮 Мини-игра"), KeyboardButton(text="📍 Адрес и время работы")],
        ],
        resize_keyboard=True,
    )


def quick_actions_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🛒 Оформить заказ", callback_data="quick_order"))
    kb.row(
        InlineKeyboardButton(text="👤 Личный кабинет", callback_data="quick_profile"),
        InlineKeyboardButton(text="📜 Мои заказы", callback_data="quick_history"),
    )
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
        InlineKeyboardButton(text=f"{qty}", callback_data="noop"),
        InlineKeyboardButton(text="➕", callback_data=f"inc:{item_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat:{ITEMS[item_id]['category']}"),
        InlineKeyboardButton(text="🧺 Корзина", callback_data="cart"),
    )
    return kb.as_markup()


def cart_kb(cart: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for iid, qty in cart.items():
        item = ITEMS[iid]
        kb.row(
            InlineKeyboardButton(text="➖", callback_data=f"cdec:{iid}"),
            InlineKeyboardButton(
                text=f"{item['name']} ×{qty}", callback_data="noop"),
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


def phone_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def payment_method_kb(order_id: int, pay_url: str) -> InlineKeyboardMarkup:
    """Выбор способа оплаты после подтверждения заказа (без лишней кнопки статуса)."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="💳 Оплатить онлайн", url=pay_url))
    kb.row(InlineKeyboardButton(
        text="✅ Я оплатил онлайн", callback_data=f"paid:{order_id}"))
    kb.row(InlineKeyboardButton(
        text="💵 Оплачу на месте", callback_data=f"pay_cash:{order_id}"))
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
    
    # Кнопка подтверждения оплаты если еще не оплачено и заказ не закрыт
    if payment != "paid" and status not in ("completed", "cancelled"):
        kb.row(InlineKeyboardButton(
            text="💰 Оплата подтверждена", callback_data=f"payok:{order_id}"))

    return kb.as_markup()


def after_order_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🛒 Новый заказ", callback_data="menu"))
    kb.row(
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
        InlineKeyboardButton(text="🎮 Игра", callback_data="dice_menu"),
    )
    return kb.as_markup()


def admin_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📊 Отчёт за сегодня", callback_data="admin_report"))
    kb.row(InlineKeyboardButton(text="📋 Активные заказы", callback_data="admin_active"))
    kb.row(InlineKeyboardButton(text="📖 Инструкция", callback_data="admin_help"))
    return kb.as_markup()


def dice_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎲 Бросить кубик", callback_data="dice"))
    return kb.as_markup()
