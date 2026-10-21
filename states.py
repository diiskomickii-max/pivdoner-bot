from aiogram.fsm.state import StatesGroup, State


class OrderForm(StatesGroup):
    browsing = State()     # листает меню / добавляет в корзину
    phone = State()        # ждём телефон
    name = State()         # ждём имя
    pickup_time = State()  # ждём время самовывоза
    comment = State()      # ждём комментарий
    confirm = State()      # подтверждение заказа
