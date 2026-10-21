import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import keyboards as kb
from config import MANAGER_CHAT_ID, PAYMENT_ENABLED, PAYMENT_URL
from db import (add_bonus, create_order, get_active_orders, get_order,
                get_today_stats, get_user, get_user_orders,
                set_last_bonus_game, set_order_payment, set_order_status,
                upsert_user)
from menu import CAFE, ITEMS, cart_text, fmt_price, pickup_ready_text
from states import OrderForm

router = Router()

STATUS_TEXT = {
    "accepted": "✅ Принят",
    "cooking": "🔥 Готовится",
    "ready": "🛍 Готов",
    "cancelled": "❌ Отменён",
}


# ---------- Хелперы ----------

async def get_cart(state: FSMContext) -> dict:
    data = await state.get_data()
    return dict(data.get("cart", {}))


async def save_cart(state: FSMContext, cart: dict):
    cart = {k: v for k, v in cart.items() if v > 0}
    await state.update_data(cart=cart)


async def delete(msg: Message):
    try:
        await msg.delete()
    except Exception:
        pass


async def send(state: FSMContext, message: Message, text: str, **kwargs):
    """Отправить сообщение и запомнить его id для возможной чистки."""
    msg = await message.answer(text, **kwargs)
    data = await state.get_data()
    last = data.get("_bot_msgs", [])
    last.append(msg.message_id)
    await state.update_data(_bot_msgs=last[-10:])
    return msg


async def cleanup_chat(state: FSMContext, bot: Bot, chat_id: int, keep_last=0):
    data = await state.get_data()
    ids = data.get("_bot_msgs", [])[:-keep_last] if keep_last else data.get("_bot_msgs", [])
    for mid in ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    await state.update_data(_bot_msgs=[])


# ---------- Старт ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(OrderForm.browsing)
    await upsert_user(message.from_user.id, message.from_user.username,
                      message.from_user.first_name)
    name = message.from_user.first_name or "друг"
    await message.answer(
        f"👋 Привет, {name}!\n\n"
        f"Это <b>{CAFE['name']}</b> — донеры, ланчбоксы и хот-доги "
        f"без очереди и ожидания.\n\n"
        "🛒 Сделай предзаказ — и к твоему приезду всё будет готово.\n"
        "🕐 Забери к выбранному времени по адресу:\n"
        f"📍 {CAFE['address']}",
        reply_markup=kb.main_menu(),
    )


# ---------- Инфо ----------

@router.message(F.text == "📍 Адрес и время работы")
async def cafe_info(message: Message):
    await message.answer(
        f"📍 <b>{CAFE['name']}</b>\n"
        f"{CAFE['address']}\n\n"
        f"🕐 Ежедневно {CAFE['hours']}\n"
        f"📞 {CAFE['phone']}\n\n"
        "Сделай предзаказ через бота — и забери без ожидания."
    )


# ---------- Личный кабинет ----------

@router.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message, state: FSMContext):
    await delete(message)
    user = await get_user(message.from_user.id)
    orders = await get_user_orders(message.from_user.id, limit=5)
    text = f"👤 <b>{message.from_user.first_name}</b>\n"
    if user and user["phone"]:
        text += f"📱 {user['phone']}\n"
    if user:
        text += f"🎁 Бонусы: <b>{user['bonus']:.0f}</b>\n"
    text += f"\n📦 Заказов: {len(orders)}\n"
    if orders:
        text += "\n<b>Последние:</b>\n"
        for o in orders:
            dt = o["created_at"][:16].replace("T", " ")
            text += f"• №{o['id']} · {dt} · {o['total']:.2f} Br · {o['status']}\n"
    await send(state, message, text)


@router.message(F.text == "📜 История заказов")
async def order_history(message: Message, state: FSMContext):
    await delete(message)
    orders = await get_user_orders(message.from_user.id, limit=10)
    if not orders:
        await send(state, message, "У тебя пока нет заказов.")
        return
    text = "📜 <b>История заказов:</b>\n\n"
    for o in orders:
        dt = o["created_at"][:16].replace("T", " ")
        text += f"№{o['id']} · {dt}\n  {o['items']}\n  💰 {o['total']:.2f} Br · {o['status']}\n\n"
    await send(state, message, text)


# ---------- Мини-игра ----------

@router.message(F.text == "🎮 Мини-игра")
async def mini_game(message: Message, state: FSMContext):
    await delete(message)
    user = await get_user(message.from_user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    if user and user["last_bonus_game"] == today:
        await send(state, message,
                   "Ты уже играл сегодня. Возвращайся завтра — кубик ждёт! 🎲")
        return
    await send(state, message,
               "🎲 <b>Игра «Кубик»</b>\n\n"
               "Бросай кубик — выиграй бонусы к следующему заказу!\n"
               "1–3 → +1 бонус · 4–5 → +2 · 6 → +5 бонусов\n\n"
               "Одна игра в день.",
               reply_markup=kb.dice_kb())


@router.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery, state: FSMContext):
    await delete(cb.message)
    await my_profile(cb.message, state)
    await cb.answer()


@router.callback_query(F.data == "dice_menu")
async def cb_dice_menu(cb: CallbackQuery, state: FSMContext):
    await delete(cb.message)
    await mini_game(cb.message, state)
    await cb.answer()


@router.callback_query(F.data == "dice")
async def cb_dice(cb: CallbackQuery, state: FSMContext):
    user = await get_user(cb.from_user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    if user and user["last_bonus_game"] == today:
        await cb.answer("Сегодня уже играл!")
        return
    msg = await cb.message.answer_dice(emoji="🎲")
    await asyncio.sleep(4)  # ждём анимацию
    val = msg.dice.value
    bonus = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 5}[val]
    await add_bonus(cb.from_user.id, bonus)
    await set_last_bonus_game(cb.from_user.id, today)
    await cb.message.edit_text(
        f"🎲 Выпало <b>{val}</b> → <b>+{bonus} бонусов!</b>\n\n"
        f"Твой баланс: <b>{(user['bonus'] if user else 0) + bonus:.0f}</b>\n"
        "Приходи завтра за новой игрой.",
        reply_markup=None,
    )
    await cb.answer(f"+{bonus} бонусов!")


# ---------- Меню и корзина ----------

@router.message(F.text == "🍔 Меню")
async def show_menu_msg(message: Message, state: FSMContext):
    await delete(message)
    await send(state, message, "Выбери категорию:", reply_markup=kb.categories_kb())


@router.message(F.text == "🧺 Корзина")
async def show_cart_msg(message: Message, state: FSMContext):
    await delete(message)
    await _send_cart(message, state)


@router.message(F.text == "🛒 Оформить предзаказ")
async def start_order(message: Message, state: FSMContext):
    await delete(message)
    await state.set_state(OrderForm.browsing)
    await send(state, message,
               "Собери заказ — выбери категорию и добавь позиции:",
               reply_markup=kb.categories_kb())


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery):
    await cb.message.edit_text("Выбери категорию:", reply_markup=kb.categories_kb())
    await cb.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(cb: CallbackQuery, state: FSMContext):
    cat = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    await cb.message.edit_text(
        f"{cat} — выбери позицию:",
        reply_markup=kb.items_kb(cat, cart),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("item:"))
async def cb_item(cb: CallbackQuery, state: FSMContext):
    item_id = cb.data.split(":", 1)[1]
    item = ITEMS[item_id]
    cart = await get_cart(state)
    qty = cart.get(item_id, 0)
    text = f"<b>{item['name']}</b> — {fmt_price(item['price'])}"
    if item.get("desc"):
        text += f"\n\n{item['desc']}"
    text += "\n\nКоличество:"
    await cb.message.edit_text(text, reply_markup=kb.item_kb(item_id, qty))
    await cb.answer()


@router.callback_query(F.data.startswith("inc:"))
async def cb_inc(cb: CallbackQuery, state: FSMContext):
    item_id = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    cart[item_id] = cart.get(item_id, 0) + 1
    await save_cart(state, cart)
    await cb.message.edit_reply_markup(reply_markup=kb.item_kb(item_id, cart[item_id]))
    await cb.answer(f"+1 {ITEMS[item_id]['name']}")


@router.callback_query(F.data.startswith("dec:"))
async def cb_dec(cb: CallbackQuery, state: FSMContext):
    item_id = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    if cart.get(item_id, 0) > 0:
        cart[item_id] -= 1
    await save_cart(state, cart)
    qty = cart.get(item_id, 0)
    await cb.message.edit_reply_markup(reply_markup=kb.item_kb(item_id, qty))
    await cb.answer()


# ---------- Корзина ----------

async def _send_cart(target, state: FSMContext, edit=False):
    cart = await get_cart(state)
    if not cart:
        text = "🧺 Корзина пуста. Загляни в меню!"
        markup = kb.empty_cart_kb()
    else:
        body, _ = cart_text(cart)
        text = f"🧺 <b>Твой заказ:</b>\n\n{body}"
        markup = kb.cart_kb(cart)
    if edit:
        await target.message.edit_text(text, reply_markup=markup)
    else:
        await send(state, target, text, reply_markup=markup)


@router.callback_query(F.data == "cart")
async def cb_cart(cb: CallbackQuery, state: FSMContext):
    await _send_cart(cb, state, edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("cinc:"))
async def cb_cart_inc(cb: CallbackQuery, state: FSMContext):
    iid = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    cart[iid] = cart.get(iid, 0) + 1
    await save_cart(state, cart)
    await _send_cart(cb, state, edit=True)
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
    await _send_cart(cb, state, edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("cdel:"))
async def cb_cart_del(cb: CallbackQuery, state: FSMContext):
    iid = cb.data.split(":", 1)[1]
    cart = await get_cart(state)
    cart.pop(iid, None)
    await save_cart(state, cart)
    await _send_cart(cb, state, edit=True)
    await cb.answer()


@router.callback_query(F.data == "clear_cart")
async def cb_clear(cb: CallbackQuery, state: FSMContext):
    await save_cart(state, {})
    await _send_cart(cb, state, edit=True)
    await cb.answer("Корзина очищена")


# ---------- Оформление ----------

@router.callback_query(F.data == "checkout")
async def cb_checkout(cb: CallbackQuery, state: FSMContext):
    cart = await get_cart(state)
    if not cart:
        await cb.answer("Корзина пуста!")
        return
    # удаляем сообщение с корзиной — начинаем чистое оформление
    await delete(cb.message)
    await state.set_state(OrderForm.phone)
    await send(state, cb.message,
               "📱 Укажи номер телефона для связи — "
               "или нажми кнопку ниже:",
               reply_markup=kb.phone_kb())
    await cb.answer()


@router.message(OrderForm.phone, F.contact)
async def got_contact(message: Message, state: FSMContext):
    await delete(message)
    await state.update_data(phone=message.contact.phone_number)
    await _ask_name(message, state)


@router.message(OrderForm.phone)
async def got_phone_text(message: Message, state: FSMContext):
    await delete(message)
    await state.update_data(phone=message.text.strip())
    await _ask_name(message, state)


async def _ask_name(message: Message, state: FSMContext):
    await state.set_state(OrderForm.name)
    await send(state, message, "Как тебя зовут?")


@router.message(OrderForm.name)
async def got_name(message: Message, state: FSMContext):
    await delete(message)
    await state.update_data(name=message.text.strip())
    await state.set_state(OrderForm.pickup_time)
    await send(state, message, "🕐 Когда заберёшь заказ?",
               reply_markup=kb.pickup_time_kb())


@router.callback_query(OrderForm.pickup_time, F.data.startswith("time:"))
async def cb_time(cb: CallbackQuery, state: FSMContext):
    kind = cb.data.split(":", 1)[1]
    if kind == "asap":
        t = "Как можно скорее"
    elif kind == "custom":
        await cb.message.answer("Напиши время, например: 18:30")
        await cb.answer()
        return
    else:
        mins = int(kind)
        t = (datetime.now() + timedelta(minutes=mins)).strftime("%H:%M")
    await delete(cb.message)
    await state.update_data(pickup_time=t)
    await state.set_state(OrderForm.comment)
    await send(state, cb.message, "✍️ Комментарий к заказу? (или напиши «-»)")
    await cb.answer()


@router.message(OrderForm.pickup_time)
async def got_custom_time(message: Message, state: FSMContext):
    await delete(message)
    await state.update_data(pickup_time=message.text.strip())
    await state.set_state(OrderForm.comment)
    await send(state, message, "✍️ Комментарий к заказу? (или напиши «-»)")


@router.message(OrderForm.comment)
async def got_comment(message: Message, state: FSMContext):
    await delete(message)
    comment = "" if message.text.strip() == "-" else message.text.strip()
    await state.update_data(comment=comment)
    data = await state.get_data()
    cart = data.get("cart", {})
    body, total = cart_text(cart)
    text = (
        f"🧾 <b>Проверь заказ:</b>\n\n{body}\n\n"
        f"👤 {data['name']}\n"
        f"📱 {data['phone']}\n"
        f"🕐 Придёт за заказом: {data['pickup_time']}\n"
        f"📍 {CAFE['address']}"
    )
    if comment:
        text += f"\n💬 {comment}"
    await state.set_state(OrderForm.confirm)
    await send(state, message, text, reply_markup=kb.confirm_kb())


# ---------- Подтверждение ----------

@router.callback_query(F.data == "confirm")
async def cb_confirm(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    cart = data.get("cart", {})
    if not cart:
        await cb.answer("Корзина пуста")
        return
    _, total = cart_text(cart)
    await upsert_user(cb.from_user.id, cb.from_user.username,
                      data["name"], data["phone"])
    order_id = await create_order(
        user_id=cb.from_user.id,
        username=cb.from_user.username,
        name=data["name"],
        phone=data["phone"],
        pickup_time=data["pickup_time"],
        cart=cart,
        comment=data.get("comment", ""),
        total=total,
    )
    # клиенту — выбор способа оплаты (заказ в группу уйдёт после выбора)
    pay_url = PAYMENT_URL.format(order_id=order_id, amount=f"{total:.2f}")
    await cb.message.edit_text(
        f"✅ <b>Заказ №{order_id} принят!</b>\n\n"
        f"Он будет готов к {data['pickup_time']}.\n"
        f"📍 Забирай: {CAFE['address']}\n\n"
        f"💰 К оплате: <b>{total:.2f} Br</b>\n\n"
        "Как будешь платить?",
        reply_markup=kb.payment_method_kb(order_id, pay_url),
    )
    await save_cart(state, {})
    await state.set_state(OrderForm.browsing)
    await cb.answer("Заказ отправлен!")


@router.callback_query(F.data.startswith("my_st:"))
async def cb_my_status(cb: CallbackQuery):
    order_id = int(cb.data.split(":", 1)[1])
    order = await get_order(order_id)
    if not order:
        await cb.answer("Заказ не найден")
        return
    pay = PAYMENT_TEXT.get(order["payment"], order["payment"])
    st = STATUS_TEXT.get(order["status"], order["status"])
    await cb.answer(
        f"№{order_id} · {st} · 💳 {pay} · {order['pickup_time']}",
        show_alert=True,
    )


@router.callback_query(F.data == "cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await delete(cb.message)
    await state.set_state(OrderForm.browsing)
    await send(state, cb.message, "❌ Заказ отменён. Собери новый через меню.")
    await cb.answer()


# ---------- Статусы (для заведения) ----------

@router.callback_query(F.data.startswith("st:"))
async def cb_status(cb: CallbackQuery, bot: Bot):
    _, order_id, status = cb.data.split(":")
    text = STATUS_TEXT.get(status)
    if not text:
        await cb.answer()
        return
    await set_order_status(order_id, status)
    await cb.message.edit_text(cb.message.text + f"\n\n<b>Статус: {text}</b>")
    await cb.answer(f"Статус: {text}")
    # уведомление клиенту со звуком
    order = await get_order(order_id)
    if order:
        try:
            await bot.send_message(
                order["user_id"],
                f"🔔 <b>Заказ №{order_id}</b>: {text.lower()}"
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("payok:"))
async def cb_payok(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":", 1)[1])
    await set_order_payment(order_id, "paid")
    await cb.message.edit_text(cb.message.text + "\n\n<b>💰 Оплата подтверждена</b>")
    await cb.answer("Оплата подтверждена")
    order = await get_order(order_id)
    if order:
        try:
            await bot.send_message(
                order["user_id"],
                f"✅ Оплата по заказу №{order_id} подтверждена. Спасибо!",
            )
        except Exception:
            pass


# ---------- Админ-панель ----------

@router.callback_query(F.data == "admin_active")
async def cb_admin_active(cb: CallbackQuery):
    orders = await get_active_orders()
    if not orders:
        text = "Активных заказов нет."
    else:
        text = "📋 <b>Активные заказы:</b>\n\n"
        for o in orders:
            pay = PAYMENT_TEXT.get(o["payment"], o["payment"])
            text += (f"№{o['id']} · {o['pickup_time']} · {o['total']:.2f} Br · "
                     f"{o['status']} · 💳 {pay}\n  {o['items']}\n\n")
    await cb.message.answer(text, reply_markup=kb.admin_kb())
    await cb.answer()


@router.callback_query(F.data == "admin_help")
async def cb_admin_help(cb: CallbackQuery):
    text = (
        "📖 <b>Как работать с заказами</b>\n\n"
        "1️⃣ Заказ приходит в этот чат → жми <b>«✅ Принят»</b>\n"
        "2️⃣ Пробей в кассе / скажи повару → жми <b>«🔥 Готовится»</b>\n"
        "3️⃣ Когда собрал — жми <b>«🛍 Готов»</b> (гость получит уведомление)\n"
        "4️⃣ Если отменяют — <b>«❌ Отменён»</b>\n\n"
        "<b>Оплата:</b>\n"
        "• «💳 Оплатить онлайн» → гость платит по ссылке банка\n"
        "• «💵 На месте» → платит при получении\n"
        "• Когда деньги пришли — жми <b>«💰 Оплата подтверждена»</b>\n\n"
        "🕐 «Придёт за заказом» — время прихода гостя\n"
        "🍽 «собрать к…» — когда заказ должен быть готов\n\n"
        "Включи звук уведомлений в этом чате, чтобы не пропускать заказы."
    )
    await cb.message.answer(text, reply_markup=kb.admin_kb())
    await cb.answer()


PAYMENT_TEXT = {
    "none": "не выбрана",
    "cash": "💵 на месте",
    "online_marked": "💳 онлайн (ждёт подтверждения)",
    "paid": "✅ оплачен онлайн",
}


async def _send_order_to_group(bot: Bot, order_id: int, payment: str):
    """Отправляет заказ в группу заведения с указанным способом оплаты."""
    order = await get_order(order_id)
    if not order:
        return
    pay_str = PAYMENT_TEXT.get(payment, payment)
    manager_text = (
        f"🆕 <b>Новый предзаказ №{order_id}</b>\n\n{order['items']}\n\n"
        f"💰 {order['total']:.2f} Br\n\n"
        f"👤 {order['name']}\n"
        f"📱 {order['phone']}\n"
        f"🕐 Придёт за заказом: {order['pickup_time']}\n"
        f"🍽 {pickup_ready_text(order['pickup_time'])}\n"
        f"💳 Оплата: <b>{pay_str}</b>"
    )
    if order["comment"]:
        manager_text += f"\n💬 {order['comment']}"
    if order["username"]:
        manager_text += f"\n🔗 @{order['username']}"
    try:
        await bot.send_message(
            MANAGER_CHAT_ID, manager_text,
            reply_markup=kb.status_kb(order_id, payment))
        await bot.send_message(MANAGER_CHAT_ID, "🔔 Новый заказ — смотри выше!")
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay_cash:"))
async def cb_pay_cash(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":", 1)[1])
    await set_order_payment(order_id, "cash")
    await cb.message.edit_text(
        "💵 Ок, оплата на месте при получении.\n"
        "Ждём тебя!",
        reply_markup=kb.client_order_kb(order_id),
    )
    await _send_order_to_group(bot, order_id, "cash")
    await cb.answer("Оплата на месте")


@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":", 1)[1])
    await set_order_payment(order_id, "online_marked")
    await cb.message.edit_text(
        "💳 Ты отметил оплату онлайн.\n"
        "Проверим и подтвердим — уведомим здесь.\n\n"
        "Что дальше?",
        reply_markup=kb.client_order_kb(order_id),
    )
    await _send_order_to_group(bot, order_id, "online_marked")
    await cb.answer("Отмечено")


# ---------- Отчёт за день (для заведения) ----------

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
    # отдельным сообщением, не трогая сообщение с заказом
    await cb.message.answer(await _report_text(), reply_markup=kb.admin_kb())
    await cb.answer()


@router.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    await message.answer(await _report_text(), reply_markup=kb.admin_kb())


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await message.answer("⚙️ <b>Панель админа</b>", reply_markup=kb.admin_kb())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.set_state(OrderForm.browsing)
    await message.answer("Ок, отменил. Что-нибудь ещё?", reply_markup=kb.main_menu())
