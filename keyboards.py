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
from menu import ITEMS, MENU, TOPPINGS, fmt_price, parse_cart_item


def admin_reply_menu() -> ReplyKeyboardMarkup:
    """Панель администратора (под строкой ввода) — ТОЛЬКО управление заведением, без кнопок гостя."""
    buttons = [
        [KeyboardButton(text="⚙️ Панель администратора"), KeyboardButton(text="ℹ️ Информация о заведении")],
        [KeyboardButton(text="📋 Активные заказы"), KeyboardButton(text="⛔ Стоп-лист кухни")],
        [KeyboardButton(text="📊 Отчёт за сегодня"), KeyboardButton(text="📑 Экспорт в Excel")],
        [KeyboardButton(text="📢 Сделать рассылку"), KeyboardButton(text="🔍 Поиск заказов по номеру")],
        [KeyboardButton(text="📖 Инструкция к боту")],
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        is_persistent=True,
    )


def guest_reply_menu() -> ReplyKeyboardMarkup:
    """Панель гостя под строкой ввода."""
    buttons = [
        [KeyboardButton(text="🛒 Оформить заказ")],
        [KeyboardButton(text="🍔 Меню"), KeyboardButton(text="🧺 Корзина")],
        [KeyboardButton(text="👤 Личный кабинет"), KeyboardButton(text="📜 Мои заказы")],
        [KeyboardButton(text="📍 Адрес и инфо"), KeyboardButton(text="🎲 Игра с бонусами")],
        [KeyboardButton(text="🚨 Подать жалобу")],
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        is_persistent=True,
    )


def main_menu(user_or_admin=None) -> ReplyKeyboardMarkup:
    """Возвращает панель администратора для админов/группы, либо панель гостя для клиентов."""
    is_admin = False
    if isinstance(user_or_admin, bool):
        is_admin = user_or_admin
    elif isinstance(user_or_admin, int):
        from config import ADMIN_IDS, DEMO_MODE, MANAGER_CHAT_ID
        is_admin = DEMO_MODE or (user_or_admin in ADMIN_IDS) or (user_or_admin == MANAGER_CHAT_ID)
    elif user_or_admin is not None:
        try:
            from config import ADMIN_IDS, DEMO_MODE, MANAGER_CHAT_ID
            uid = int(user_or_admin)
            is_admin = DEMO_MODE or (uid in ADMIN_IDS) or (uid == MANAGER_CHAT_ID)
        except Exception:
            is_admin = False
    else:
        from config import DEMO_MODE
        is_admin = DEMO_MODE

    if is_admin:
        return admin_reply_menu()
    return guest_reply_menu()


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


def broadcast_consent_kb() -> InlineKeyboardMarkup:
    """Запрос согласия на получение рекламных рассылок при первом старте."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✅ Да, хочу получать акции", callback_data="bcast_consent:1"))
    kb.row(InlineKeyboardButton(text="❌ Нет, не присылать рассылки", callback_data="bcast_consent:0"))
    return kb.as_markup()


def profile_kb(is_verified: bool = True, broadcast_consent: int = 1) -> InlineKeyboardMarkup:
    """Клавиатура личного кабинета с переключателем согласия на рассылку."""
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
    
    bcast_btn = (
        InlineKeyboardButton(text="🔔 Рассылка акций: Включена", callback_data="toggle_bcast:0")
        if broadcast_consent == 1
        else InlineKeyboardButton(text="🔕 Рассылка акций: Отключена", callback_data="toggle_bcast:1")
    )
    kb.row(bcast_btn)

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
    """Список категорий меню. 'Добавки в шаурму' исключены — они настраиваются внутри шаурмы."""
    kb = InlineKeyboardBuilder()
    for cat in MENU:
        if cat == "🧀 Добавки в шаурму":
            continue  # Исключаем из общего списка категорий
        kb.row(InlineKeyboardButton(text=cat, callback_data=f"cat:{cat}"))
    kb.row(InlineKeyboardButton(text="🧺 Корзина", callback_data="cart"))
    return kb.as_markup()


def items_kb(cat: str, cart: dict, stop_list: dict = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for item in MENU[cat]:
        is_stopped = bool(stop_list and item["id"] in stop_list)
        if is_stopped:
            label = f"⛔ {item['name']} (СТОП)"
        else:
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
    # Если блюдо — шаурма/донер, даём кнопку настройки добавок прямо к ней
    if item_id.startswith("doner_") or "Донер" in ITEMS.get(item_id, {}).get("name", ""):
        kb.row(
            InlineKeyboardButton(text="🧀 Выбрать добавки к этой шаурме", callback_data=f"top_sel:{item_id}"),
        )
    kb.row(
        InlineKeyboardButton(text="⬅️ Назад в категорию", callback_data=f"cat:{ITEMS[item_id]['category']}"),
        InlineKeyboardButton(text="🧺 В корзину", callback_data="cart"),
    )
    return kb.as_markup()


def toppings_selector_kb(doner_id: str, mask: str = "", stop_list: dict = None) -> InlineKeyboardMarkup:
    """
    Интерактивный конструктор добавок к конкретной шаурме с учётом стоп-листа.
    mask: строка выбранных цифр-индексов в TOPPINGS, например '02' (сыр + халапеньо).
    """
    kb = InlineKeyboardBuilder()
    base_item = ITEMS.get(doner_id, {})
    total_price = base_item.get("price", 0.0)

    selected_set = set(mask.split("_")) if mask else set()
    for idx, top in enumerate(TOPPINGS):
        top_id = top["id"]
        is_stopped = bool(stop_list and top_id in stop_list)
        if is_stopped:
            label = f"⛔ {top['name']} (закончилась)"
            kb.row(InlineKeyboardButton(text=label, callback_data=f"top_blocked:{top_id}"))
            continue
        is_selected = str(idx) in selected_set
        prefix = "✅" if is_selected else "▫️"
        label = f"{prefix} {top['name']} (+{top['price']:.2f} Br)"
        if is_selected:
            total_price += top["price"]
        kb.row(InlineKeyboardButton(text=label, callback_data=f"top_t:{doner_id}:{idx}:{mask}"))

    # Кнопка добавления настроенной шаурмы в корзину
    kb.row(
        InlineKeyboardButton(
            text=f"🛒 Добавить в корзину ({total_price:.2f} Br)",
            callback_data=f"top_add:{doner_id}:{mask}",
        )
    )
    kb.row(
        InlineKeyboardButton(text="⬅️ Назад к блюду", callback_data=f"item:{doner_id}"),
        InlineKeyboardButton(text="🧺 В корзину", callback_data="cart"),
    )
    return kb.as_markup()


def cart_kb(cart: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for iid, qty in cart.items():
        parsed = parse_cart_item(iid)
        name = parsed["name"] if parsed else ITEMS.get(iid, {}).get("name", iid)
        display_name = name if len(name) <= 22 else name[:20] + "…"
        kb.row(
            InlineKeyboardButton(text="➖", callback_data=f"cdec:{iid}"),
            InlineKeyboardButton(text=f"{display_name} ×{qty}", callback_data="noop"),
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


def yandex_delivery_payment_kb(order_id: int, eda_url: str, delivery_cab_url: str) -> InlineKeyboardMarkup:
    """Оплата и оформление курьерской доставки через Яндекс."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 Оплатить в Яндекс Еде / Go", url=eda_url))
    kb.row(InlineKeyboardButton(text="🚚 Кабинет Яндекс Доставки", url=delivery_cab_url))
    # Тестовые кнопки эмуляции ответа Яндекс API
    kb.row(
        InlineKeyboardButton(text="🧪 Тест: Оплата прошла", callback_data=f"yandex_pay_sim:ok:{order_id}"),
        InlineKeyboardButton(text="🧪 Тест: Оплата не прошла", callback_data=f"yandex_pay_sim:fail:{order_id}"),
    )
    return kb.as_markup()


def yandex_payment_failed_kb(order_id: int, eda_url: str) -> InlineKeyboardMarkup:
    """Клавиатура при неудачной оплате в сервисе Яндекс."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔄 Попробовать оплатить снова", url=eda_url))
    kb.row(InlineKeyboardButton(text="🏃 Переключить на самовывоз (оплата на месте)", callback_data=f"yandex_to_pickup:{order_id}"))
    kb.row(InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_order_guest:{order_id}"))
    kb.row(InlineKeyboardButton(text="🧪 Тест: Оплата прошла", callback_data=f"yandex_pay_sim:ok:{order_id}"))
    return kb.as_markup()


def admin_cancel_reasons_kb(order_id: int) -> InlineKeyboardMarkup:
    """Выбор причины отмены заказа администратором."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🥩 Закончились ингредиенты", callback_data=f"cancel_r:{order_id}:ingredients"))
    kb.row(InlineKeyboardButton(text="⚡ Отключение электричества / форс-мажор", callback_data=f"cancel_r:{order_id}:power"))
    kb.row(InlineKeyboardButton(text="⏳ Большая загрузка кухни (>60 мин)", callback_data=f"cancel_r:{order_id}:overload"))
    kb.row(InlineKeyboardButton(text="📞 Не удалось связаться с клиентом", callback_data=f"cancel_r:{order_id}:unreachable"))
    kb.row(InlineKeyboardButton(text="✍️ Написать свою причину", callback_data=f"cancel_r:{order_id}:custom"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад (Не отменять)", callback_data=f"cancel_r:{order_id}:back"))
    return kb.as_markup()


def status_kb(order_id: int, status: str = "new", payment: str = "none", delivery_type: str = "pickup") -> InlineKeyboardMarkup:
    """Последовательные кнопки управления заказом для администратора/повара."""
    kb = InlineKeyboardBuilder()

    if status == "new":
        kb.row(InlineKeyboardButton(text="✅ Принять заказ", callback_data=f"st:{order_id}:accepted"))
        kb.row(InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"st_cancel:{order_id}"))
    elif status == "accepted":
        kb.row(InlineKeyboardButton(text="🔥 Начать готовить", callback_data=f"st:{order_id}:cooking"))
        kb.row(
            InlineKeyboardButton(text="🛍 Сразу готов", callback_data=f"st:{order_id}:ready"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"st_cancel:{order_id}"),
        )
    elif status == "cooking":
        kb.row(InlineKeyboardButton(text="🛍 Заказ готов!", callback_data=f"st:{order_id}:ready"))
        kb.row(InlineKeyboardButton(text="❌ Отменить", callback_data=f"st_cancel:{order_id}"))
    elif status == "ready":
        if delivery_type == "yandex":
            kb.row(InlineKeyboardButton(text="🚗 Передать заказ курьеру", callback_data=f"st:{order_id}:to_courier"))
        else:
            kb.row(InlineKeyboardButton(text="🏁 Выдан гостю (Завершить)", callback_data=f"st:{order_id}:completed"))
        kb.row(InlineKeyboardButton(text="❌ Отменить", callback_data=f"st_cancel:{order_id}"))
    elif status == "to_courier":
        kb.row(InlineKeyboardButton(text="🏁 Подтвердить доставку (Завершить)", callback_data=f"st:{order_id}:completed"))

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
    kb.row(
        InlineKeyboardButton(text="ℹ️ Информация о заведении", callback_data="admin_cafe_info"),
        InlineKeyboardButton(text="🔍 Поиск по номеру", callback_data="admin_search_phone"),
    )
    kb.row(
        InlineKeyboardButton(text="📋 Активные заказы", callback_data="admin_active"),
        InlineKeyboardButton(text="⛔ Стоп-лист кухни", callback_data="admin_stop_list"),
    )
    kb.row(
        InlineKeyboardButton(text="📊 Отчёт за сегодня", callback_data="admin_report"),
        InlineKeyboardButton(text="⭐ Рейтинг и отзывы", callback_data="admin_reviews_stats"),
    )
    kb.row(
        InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin_broadcast"),
        InlineKeyboardButton(text="📑 Экспорт в Excel", callback_data="admin_export_excel"),
    )
    kb.row(InlineKeyboardButton(text="📖 Инструкция к боту", callback_data="admin_help"))
    return kb.as_markup()


def admin_cafe_info_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🔄 Обновить сводку", callback_data="admin_cafe_info"),
        InlineKeyboardButton(text="⛔ Стоп-лист кухни", callback_data="admin_stop_list"),
    )
    kb.row(
        InlineKeyboardButton(text="📋 Активные заказы", callback_data="admin_active"),
        InlineKeyboardButton(text="📊 Отчёт за сегодня", callback_data="admin_report"),
    )
    kb.row(InlineKeyboardButton(text="⚙️ Панель администратора", callback_data="admin_menu"))
    return kb.as_markup()


def admin_search_again_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔍 Искать другой номер", callback_data="admin_search_phone"))
    kb.row(InlineKeyboardButton(text="⚙️ Меню администратора", callback_data="admin_menu"))
    return kb.as_markup()


def admin_cancel_search_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Отменить поиск", callback_data="admin_cancel_search"))
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


def admin_stop_menu_kb(has_stopped: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Поставить БЛЮДО на стоп", callback_data="stop_add_dish"))
    kb.row(InlineKeyboardButton(text="➕ Поставить ДОБАВКУ на стоп", callback_data="stop_add_top"))
    if has_stopped:
        kb.row(InlineKeyboardButton(text="🟢 Снять позицию со стопа (Вернуть)", callback_data="stop_unstop_menu"))
    kb.row(
        InlineKeyboardButton(text="🔄 Обновить список", callback_data="stop_list_refresh"),
        InlineKeyboardButton(text="⚙️ Панель администратора", callback_data="admin_menu"),
    )
    return kb.as_markup()


def admin_stop_choose_dish_kb(stop_list: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat, items in MENU.items():
        if cat == "🧀 Добавки в шаурму":
            continue
        for item in items:
            if item["id"] in stop_list:
                continue
            kb.row(InlineKeyboardButton(text=f"⛔ {item['name']}", callback_data=f"stop_pick:dish:{item['id']}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад в стоп-лист", callback_data="admin_stop_list"))
    return kb.as_markup()


def admin_stop_choose_top_kb(stop_list: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for top in TOPPINGS:
        if top["id"] in stop_list:
            continue
        kb.row(InlineKeyboardButton(text=f"⛔ {top['name']}", callback_data=f"stop_pick:top:{top['id']}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад в стоп-лист", callback_data="admin_stop_list"))
    return kb.as_markup()


def admin_stop_unstop_kb(stop_list: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for item_id, info in stop_list.items():
        name = info.get("item_name") or ITEMS.get(item_id, {}).get("name", item_id)
        kb.row(InlineKeyboardButton(text=f"🟢 Вернуть: {name}", callback_data=f"stop_unstop_do:{item_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад в стоп-лист", callback_data="admin_stop_list"))
    return kb.as_markup()


def admin_stop_reason_kb(item_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🥩 Закончились ингредиенты", callback_data=f"stop_set_r:{item_id}:ingredients"))
    kb.row(InlineKeyboardButton(text="🚚 Задержка поставки продуктов", callback_data=f"stop_set_r:{item_id}:supplier"))
    kb.row(InlineKeyboardButton(text="⚙️ Проблема с оборудованием", callback_data=f"stop_set_r:{item_id}:equipment"))
    kb.row(InlineKeyboardButton(text="⏳ Временно не успеваем готовить", callback_data=f"stop_set_r:{item_id}:overload"))
    kb.row(InlineKeyboardButton(text="✍️ Ввести свою причину", callback_data=f"stop_set_r:{item_id}:custom"))
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_stop_list"))
    return kb.as_markup()
