import aiosqlite
import re
from datetime import datetime
from config import DB_PATH
from menu import ITEMS

CREATE_ORDERS = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    pickup_time TEXT NOT NULL,
    items TEXT NOT NULL,
    comment TEXT,
    total REAL NOT NULL,
    delivery_type TEXT NOT NULL DEFAULT 'pickup',
    delivery_address TEXT,
    delivery_cost REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'new',
    payment TEXT NOT NULL DEFAULT 'none',
    created_at TEXT NOT NULL
);
"""

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    phone TEXT,
    bonus REAL NOT NULL DEFAULT 0,
    last_bonus_game TEXT,
    is_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

CREATE_COMPLAINTS = """
CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    name TEXT,
    phone TEXT,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
);
"""

CREATE_REVIEWS = """
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    rating INTEGER NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);
"""



CREATE_STOP_LIST = """
CREATE TABLE IF NOT EXISTS stop_list (
    item_id TEXT PRIMARY KEY,
    item_name TEXT NOT NULL,
    item_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_ORDERS)
        await db.execute(CREATE_USERS)
        await db.execute(CREATE_COMPLAINTS)
        await db.execute(CREATE_REVIEWS)
        await db.execute(CREATE_STOP_LIST)
        # миграция: добавить колонку payment в старые базы
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN payment TEXT NOT NULL DEFAULT 'none'")
        except Exception:
            pass  # колонка уже есть
        # миграция: добавить колонку is_verified в старые базы
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        # миграции: доставка Яндекс Go
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN delivery_type TEXT NOT NULL DEFAULT 'pickup'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN delivery_address TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN delivery_cost REAL NOT NULL DEFAULT 0.0")
        except Exception:
            pass
        # миграция: реферальная программа
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        except Exception:
            pass
        # миграция: причина отмены заказа
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN cancellation_reason TEXT")
        except Exception:
            pass
        # миграция: согласие на рассылку
        try:
            await db.execute("ALTER TABLE users ADD COLUMN broadcast_consent INTEGER DEFAULT NULL")
        except Exception:
            pass
        await db.commit()


# ---------- Заказы ----------

async def create_order(
    user_id, username, name, phone, pickup_time, cart, comment, total,
    delivery_type="pickup", delivery_address="", delivery_cost=0.0
):
    from menu import parse_cart_item, ITEMS
    items_list = []
    for iid, q in cart.items():
        parsed = parse_cart_item(iid)
        iname = parsed["name"] if parsed else ITEMS.get(iid, {}).get("name", iid)
        items_list.append(f"{iname} x{q}")
    items_str = ", ".join(items_list)
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO orders
               (user_id, username, name, phone, pickup_time, items, comment, total,
                delivery_type, delivery_address, delivery_cost, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, username, name, phone, pickup_time, items_str, comment, total,
             delivery_type, delivery_address, delivery_cost, now),
        )
        await db.commit()
        return cur.lastrowid


async def get_order(order_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        return await cur.fetchone()


async def set_order_status(order_id, status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        await db.commit()


async def set_order_payment(order_id, payment):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET payment=? WHERE id=?", (payment, order_id))
        await db.commit()


async def set_order_cancellation(order_id: int, reason: str):
    """Устанавливает статус отмены и причину отказа заведением."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET status='cancelled', cancellation_reason=? WHERE id=?",
            (reason, order_id),
        )
        await db.commit()


async def switch_order_to_pickup(order_id: int):
    """Переключает заказ на самовывоз при сбое онлайн-оплаты, убирая стоимость доставки."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        order = await cur.fetchone()
        if not order:
            return None
        deliv_cost = order["delivery_cost"]
        new_total = max(0.0, order["total"] - deliv_cost)
        await db.execute(
            """UPDATE orders 
               SET delivery_type='pickup', delivery_cost=0.0, total=?, payment='cash'
               WHERE id=?""",
            (new_total, order_id),
        )
        await db.commit()
        return new_total


async def get_today_stats():
    """Продажи за сегодня: заказы, сумма, топ позиций."""
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT id, items, total, status, payment, pickup_time FROM orders
               WHERE created_at LIKE ? AND status != 'cancelled' ORDER BY id""",
            (f"{today}%",),
        )
        rows = await cur.fetchall()
        total = sum(r["total"] for r in rows)
        return rows, total


async def get_order_status(order_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT status FROM orders WHERE id=?", (order_id,))
        row = await cur.fetchone()
        return row[0] if row else None


async def get_active_orders(limit=20):
    """Список активных заказов (только в процессе приготовления или передачи курьеру)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT * FROM orders 
               WHERE status IN ('new', 'accepted', 'cooking', 'ready', 'to_courier') 
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        )
        return await cur.fetchall()


async def get_order_full(order_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        return await cur.fetchone()


async def get_user_orders(user_id, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return await cur.fetchall()





# ---------- Профили гостей ----------

async def upsert_user(user_id, username=None, name=None, phone=None, is_verified=None):
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if await cur.fetchone():
            await db.execute(
                "UPDATE users SET username=COALESCE(?,username), "
                "name=COALESCE(?,name), phone=COALESCE(?,phone), "
                "is_verified=COALESCE(?,is_verified) WHERE user_id=?",
                (username, name, phone, is_verified, user_id),
            )
        else:
            ver = is_verified if is_verified is not None else 0
            await db.execute(
                "INSERT INTO users (user_id, username, name, phone, is_verified, created_at) VALUES (?,?,?,?,?,?)",
                (user_id, username, name, phone, ver, now),
            )
        await db.commit()


async def update_user_name(user_id, name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET name=? WHERE user_id=?", (name, user_id))
        await db.commit()


async def update_user_phone(user_id, phone, is_verified=1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET phone=?, is_verified=? WHERE user_id=?",
            (phone, is_verified, user_id),
        )
        await db.commit()


async def get_user_stats(user_id):
    """Статистика гостя для личного кабинета: количество заказов и сумма покупок."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders WHERE user_id=? AND status != 'cancelled'",
            (user_id,),
        )
        row = await cur.fetchone()
        return (row[0], row[1]) if row else (0, 0.0)


async def get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()


async def add_bonus(user_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET bonus=bonus+? WHERE user_id=?", (amount, user_id))
        await db.commit()


async def set_last_bonus_game(user_id, ts):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_bonus_game=? WHERE user_id=?", (ts, user_id))
        await db.commit()


# ---------- Жалобы и обращения ----------

async def create_complaint(user_id, username, name, phone, text):
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO complaints (user_id, username, name, phone, text, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, username, name, phone, text, now),
        )
        await db.commit()
        return cur.lastrowid


async def search_orders_by_phone(phone_query: str):
    """Поиск истории заказов гостя по номеру телефона для администратора."""
    digits = re.sub(r"\D", "", phone_query.strip())
    if not digits:
        return None, []

    # Берём для поиска последние 7-9 цифр для универсального поиска по любым форматам
    search_suffix = f"%{digits[-7:]}%" if len(digits) >= 7 else f"%{digits}%"
    full_pattern = f"%{digits}%"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Ищем профиль пользователя
        cur_u = await db.execute(
            "SELECT * FROM users WHERE phone LIKE ? OR phone LIKE ? ORDER BY user_id DESC LIMIT 1",
            (full_pattern, search_suffix),
        )
        user = await cur_u.fetchone()

        # Ищем все заказы с таким телефоном
        cur_o = await db.execute(
            """SELECT * FROM orders 
               WHERE phone LIKE ? OR phone LIKE ? 
               ORDER BY id DESC""",
            (full_pattern, search_suffix),
        )
        orders = await cur_o.fetchall()

        # Если в таблице orders номер был записан чуть иначе, но профиль найден
        if not orders and user:
            cur_o = await db.execute(
                "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC",
                (user["user_id"],),
            )
            orders = await cur_o.fetchall()

        return dict(user) if user else None, [dict(o) for o in orders]


# ---------- Отзывы (NPS) ----------

async def create_review(order_id: int, user_id: int, rating: int, comment: str = ""):
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO reviews (order_id, user_id, rating, comment, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (order_id, user_id, rating, comment, now),
        )
        await db.commit()
        return cur.lastrowid


async def get_all_users(verified_only: bool = False, subscribed_only: bool = False):
    """Список пользователей для таргетированной рассылки (с проверкой согласия)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        clauses = []
        if verified_only:
            clauses.append("is_verified=1")
        if subscribed_only:
            # Исключаем тех, кто явно нажал "Не присылать рассылку" (0)
            clauses.append("broadcast_consent = 1")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM users{where}"
        cur = await db.execute(sql)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def set_broadcast_consent(user_id: int, consent: int):
    """Устанавливает согласие гостя на получение рассылок акций (1 или 0)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET broadcast_consent=? WHERE user_id=?", (consent, user_id))
        await db.commit()


async def get_broadcast_consent(user_id: int):
    """Проверяет согласие пользователя на рассылку."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT broadcast_consent FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None


async def get_all_orders_for_export(limit: int = 1000):
    """Список всех заказов для выгрузки отчёта в Excel."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ---------- Реферальная программа ----------

async def set_referrer(user_id: int, referrer_id: int) -> bool:
    """Устанавливает реферера и начисляет приветственный бонус 2.0 Br новому гостю."""
    if user_id == referrer_id:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row["referred_by"] is not None:
            return False

        await db.execute(
            "UPDATE users SET referred_by=?, bonus=bonus+2.0 WHERE user_id=?",
            (referrer_id, user_id),
        )
        await db.commit()
        return True


async def get_user_referral_stats(user_id: int):
    """Возвращает (кол-во приглашённых, начисленные бонусы)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
        row = await cur.fetchone()
        invited_cnt = row[0] if row else 0
        earned_bonus = invited_cnt * 2.0
        return invited_cnt, earned_bonus


# ---------- Статистика отзывов для Администратора ----------

async def get_overall_reviews_stats():
    """Общая статистика рейтинга (NPS) для заведения."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT 
                COUNT(*) as total_count,
                AVG(rating) as avg_rating,
                SUM(CASE WHEN rating=5 THEN 1 ELSE 0 END) as c5,
                SUM(CASE WHEN rating=4 THEN 1 ELSE 0 END) as c4,
                SUM(CASE WHEN rating=3 THEN 1 ELSE 0 END) as c3,
                SUM(CASE WHEN rating=2 THEN 1 ELSE 0 END) as c2,
                SUM(CASE WHEN rating=1 THEN 1 ELSE 0 END) as c1
               FROM reviews"""
        )
        stats = await cur.fetchone()

        cur_recent = await db.execute(
            """SELECT r.*, u.name as user_name, u.phone as user_phone 
               FROM reviews r 
               LEFT JOIN users u ON r.user_id = u.user_id 
               ORDER BY r.id DESC LIMIT 5"""
        )
        recent = await cur_recent.fetchall()

        return dict(stats) if stats else {}, [dict(r) for r in recent]


async def get_user_average_rating(user_id: int):
    """Средняя оценка конкретного гостя за всё время."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*), AVG(rating) FROM reviews WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        if row and row[0] > 0:
            return row[0], round(row[1], 1)
        return 0, 0.0




# ---------- Стоп-лист (Блюда и ингредиенты) ----------

STOP_LIST_CACHE = None


async def get_stop_list() -> dict:
    """Возвращает словарь {item_id: {'item_id': ..., 'item_name': ..., 'item_type': ..., 'reason': ...}}."""
    global STOP_LIST_CACHE
    if STOP_LIST_CACHE is not None:
        return STOP_LIST_CACHE
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM stop_list")
        rows = await cur.fetchall()
        STOP_LIST_CACHE = {r["item_id"]: dict(r) for r in rows}
        return STOP_LIST_CACHE


async def add_to_stop_list(item_id: str, item_name: str, item_type: str, reason: str):
    """Добавляет блюдо или добавку в стоп-лист с указанием причины."""
    global STOP_LIST_CACHE
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO stop_list (item_id, item_name, item_type, reason, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(item_id) DO UPDATE SET 
                   item_name=excluded.item_name,
                   item_type=excluded.item_type,
                   reason=excluded.reason,
                   created_at=excluded.created_at""",
            (item_id, item_name, item_type, reason, now),
        )
        await db.commit()
    STOP_LIST_CACHE = None
    await get_stop_list()


async def remove_from_stop_list(item_id: str):
    """Удаляет позицию из стоп-листа (возвращает в меню)."""
    global STOP_LIST_CACHE
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM stop_list WHERE item_id=?", (item_id,))
        await db.commit()
    STOP_LIST_CACHE = None
    await get_stop_list()


async def get_item_stop_info(item_id: str) -> dict | None:
    """Проверяет, находится ли позиция на стопе. Возвращает dict с причиной или None."""
    sl = await get_stop_list()
    return sl.get(item_id)
