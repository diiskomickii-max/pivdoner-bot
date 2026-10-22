"""Модуль генерации профессиональных отчётов по продажам в Excel (.xlsx) для кафе «ПивДонер»."""

import os
from datetime import datetime
from typing import List, Dict, Any
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def generate_excel_report(orders: List[Dict[str, Any]], reports_dir: str = "reports") -> str:
    """Формирует красивую Excel-таблицу со всеми заказами, выручкой и статистикой."""
    os.makedirs(reports_dir, exist_ok=True)
    now = datetime.now()
    filename = f"pivdoner_report_{now.strftime('%Y_%m_%d_%H%M%S')}.xlsx"
    filepath = os.path.join(reports_dir, filename)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Заказы ПивДонер"

    # Заголовок отчёта
    ws.merge_cells("A1:L1")
    title_cell = ws["A1"]
    title_cell.value = f"ОТЧЁТ ПО ЗАКАЗАМ И ВЫРУЧКЕ — КАФЕ «ПИВДОНЕР» (сформирован {now.strftime('%d.%m.%Y %H:%M')})"
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 35

    # Шапка таблицы
    headers = [
        "№ Заказа",
        "Дата и время",
        "Имя гостя",
        "Телефон",
        "Способ получения",
        "Адрес доставки",
        "Состав блюд",
        "Сумма блюд (Br)",
        "Доставка (Br)",
        "Итого (Br)",
        "Оплата",
        "Статус",
    ]

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
    border_thin = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    ws.row_dimensions[2].height = 24
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border_thin

    # Заполнение строк
    row_num = 3
    total_revenue = 0.0

    for o in orders:
        dt = o.get("created_at", "")[:19].replace("T", " ")
        deliv_type = "🚕 Яндекс Доставка" if o.get("delivery_type") == "yandex" else "🏃 Самовывоз"
        addr = o.get("delivery_address") or ("ул. Одинцова, 20" if deliv_type == "🏃 Самовывоз" else "Не указан")
        d_cost = float(o.get("delivery_cost", 0.0))
        total = float(o.get("total", 0.0))
        items_cost = total - d_cost
        pay_str = "💵 Наличные" if o.get("payment") == "cash" else ("💳 Онлайн (оплачен)" if o.get("payment") == "paid" else "💳 Онлайн")

        row_data = [
            o.get("id"),
            dt,
            o.get("name"),
            o.get("phone"),
            deliv_type,
            addr,
            o.get("items"),
            round(items_cost, 2),
            round(d_cost, 2),
            round(total, 2),
            pay_str,
            o.get("status"),
        ]

        ws.row_dimensions[row_num].height = 20
        fill_row = PatternFill(start_color="F2F2F2" if row_num % 2 == 0 else "FFFFFF", fill_type="solid")

        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=val)
            cell.font = Font(name="Calibri", size=10)
            cell.border = border_thin
            cell.fill = fill_row
            if col_idx in (8, 9, 10):
                cell.number_format = '#,##0.00 "Br"'
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx in (1, 2, 4, 11, 12):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

        if o.get("status") != "cancelled":
            total_revenue += total
        row_num += 1

    # Итоговая строка
    summary_row = row_num
    ws.row_dimensions[summary_row].height = 25
    ws.merge_cells(f"A{summary_row}:I{summary_row}")
    sum_label = ws[f"A{summary_row}"]
    sum_label.value = f"ИТОГО ВЫРУЧКА ПО ВЫПОЛНЕННЫМ ЗАКАЗАМ:"
    sum_label.font = Font(name="Calibri", size=11, bold=True)
    sum_label.alignment = Alignment(horizontal="right", vertical="center")

    sum_val = ws[f"J{summary_row}"]
    sum_val.value = round(total_revenue, 2)
    sum_val.font = Font(name="Calibri", size=12, bold=True, color="006100")
    sum_val.fill = PatternFill(start_color="C6EFCE", fill_type="solid")
    sum_val.number_format = '#,##0.00 "Br"'
    sum_val.alignment = Alignment(horizontal="right", vertical="center")

    # Автоматическая настройка ширины колонок
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(min(max_len + 3, 40), 12)

    wb.save(filepath)
    return filepath
