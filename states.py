from aiogram.fsm.state import StatesGroup, State


class RegistrationForm(StatesGroup):
    waiting_for_phone = State()     # ждём номер телефона или контакт
    waiting_for_sms_code = State()  # ждём ввод 4-значного кода подтверждения (СМС через Телеграм)
    waiting_for_name = State()      # ждём имя гостя


class ProfileEditForm(StatesGroup):
    waiting_for_name = State()      # изменение имени
    waiting_for_phone = State()     # изменение телефона
    waiting_for_sms_code = State()  # подтверждение кода при смене телефона


class ComplaintForm(StatesGroup):
    waiting_for_text = State()      # ждём текст жалобы или фото


class AdminSearchForm(StatesGroup):
    waiting_for_phone = State()     # администратор вводит номер для поиска истории


class BroadcastForm(StatesGroup):
    waiting_for_content = State()   # ждём текст или фото для рассылки
    confirm_send = State()          # подтверждение отправки


class ReviewForm(StatesGroup):
    waiting_for_comment = State()   # клиент пишет замечание при низкой оценке


class AdminCancelForm(StatesGroup):
    waiting_for_reason = State()    # администратор вводит причину отмены заказа текстом


class OrderForm(StatesGroup):
    browsing = State()          # листает меню / корзина
    delivery_choice = State()   # выбор: Яндекс Доставка / Самовывоз
    address = State()           # ввод адреса доставки
    phone = State()             # ждём телефон при оформлении (если не верифицирован или меняет)
    sms_code = State()          # ждём код подтверждения
    name = State()              # ждём имя
    pickup_time = State()       # ждём время самовывоза / доставки
    comment = State()           # ждём комментарий
    confirm = State()           # подтверждение заказа
