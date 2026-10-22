"""Модуль генерации кухонных чеков для термопринтеров 58мм и 80мм (ESC/POS).

Поддерживает:
1. Текстовый моноширинный чек для отображения на экране и печати.
2. Бинарный ESC/POS поток байт для отправки на Bluetooth/USB/Network чековые принтеры
   (Xprinter XP-58/80, Rongta, Epson TM-T20 и др.) с командой автоматического отреза бумаги.
"""

from typing import Dict, Any
from datetime import datetime
from menu import CAFE


def format_receipt_text(order: Dict[str, Any], width: int = 32) -> str:
    """Форматирует чек для термопринтера заданной ширины (32 символа для 58мм, 42 для 80мм)."""
    sep_double = "=" * width
    sep_single = "-" * width

    dt = order.get("created_at", datetime.now().isoformat())[:16].replace("T", " ")
    deliv_type = order.get("delivery_type", "pickup")
    is_yandex = deliv_type == "yandex"

    lines = [
        sep_double,
        f"{CAFE['name'].upper()}".center(width),
        "ШАУРМА & ГРИЛЬ НА УГЛЯХ".center(width),
        f"{CAFE['address']}".center(width),
        f"Тел: {CAFE['phone']}".center(width),
        sep_double,
        f"ЗАКАЗ НА КУХНЮ №{order['id']}".center(width),
        f"Время: {dt}".center(width),
        sep_single,
    ]

    # Способ получения
    if is_yandex:
        lines.append("ТИП: 🚕 ЯНДЕКС ДОСТАВКА".ljust(width))
        lines.append(f"АДРЕС: {order.get('delivery_address', 'Не указан')[:width-7]}")
        addr_tail = (order.get("delivery_address") or "")[width-7:]
        if addr_tail:
            lines.append(f"       {addr_tail[:width-7]}")
    else:
        lines.append(f"ТИП: 🏃 САМОВЫВОЗ (к {order.get('pickup_time', 'скоро')})".ljust(width))

    lines.append(f"ГОСТЬ: {order.get('name', 'Гость')}")
    lines.append(f"ТЕЛ:   {order.get('phone', '-')}")
    lines.append(sep_single)
    lines.append("НАИМЕНОВАНИЕ        КОЛ    СУММА")
    lines.append(sep_single)

    # Список блюд (парсим строку позиций)
    raw_items = order.get("items", "")
    for item in raw_items.split(", "):
        if not item.strip():
            continue
        lines.append(f"• {item.strip()[:width-2]}")

    if is_yandex:
        d_cost = float(order.get("delivery_cost", 0.0))
        lines.append(f"• Доставка Яндекс Go:      {d_cost:.2f} Br")

    lines.append(sep_single)
    total_val = float(order.get("total", 0.0))
    lines.append(f"ИТОГО К ОПЛАТЕ:      {total_val:.2f} Br".rjust(width))
    pay_type = order.get("payment", "none")
    pay_desc = "💵 НА МЕСТЕ" if pay_type == "cash" else ("💳 ОПЛАЧЕН ОНЛАЙН" if pay_type == "paid" else "💳 ОНЛАЙН")
    lines.append(f"ОПЛАТА: {pay_desc}".rjust(width))

    if order.get("comment"):
        lines.append(sep_single)
        lines.append("ПОЖЕЛАНИЕ КЛИЕНТА:")
        lines.append(f"«{order['comment']}»")

    lines.append(sep_double)
    lines.append("ГОТОВИТЬ ГОРЯЧИМ С ГРИЛЯ!".center(width))
    lines.append(f"www.pivdoner.by".center(width))
    lines.append("[ -- отрезная линия / CUT -- ]".center(width))

    return "\n".join(lines)


def generate_esc_pos_bytes(order: Dict[str, Any]) -> bytes:
    """
    Генерирует бинарные ESC/POS команды для прямой отправки на термопринтер.
    Включает инициализацию, двойную высоту заголовка и автоотрезку.
    """
    ESC = b"\x1b"
    GS = b"\x1d"

    buf = bytearray()
    # Инициализация принтера
    buf.extend(ESC + b"@")
    # Выравнивание по центру
    buf.extend(ESC + b"a\x01")
    # Двойная высота и жирный для названия
    buf.extend(ESC + b"!\x38")
    buf.extend(f"{CAFE['name']}\n".encode("cp866", errors="replace"))
    # Нормальный шрифт
    buf.extend(ESC + b"!\x00")
    buf.extend(f"г. Минск, {CAFE['address']}\n".encode("cp866", errors="replace"))

    # Двойной размер для номера заказа
    buf.extend(ESC + b"!\x30")
    buf.extend(f"\nЗАКАЗ №{order['id']}\n".encode("cp866", errors="replace"))
    buf.extend(ESC + b"!\x00")

    # Выравнивание по левому краю
    buf.extend(ESC + b"a\x00")
    text_content = format_receipt_text(order, width=32)
    buf.extend(text_content.encode("cp866", errors="replace"))

    # Прогон ленты на 4 строки и отрезка
    buf.extend(b"\n\n\n\n")
    # Команда отрезки бумаги (Full Cut)
    buf.extend(GS + b"V\x00")

    return bytes(buf)
