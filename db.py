import aiosqlite
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
    created_at TEXT NOT NULL
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_ORDERS)
        await db.execute(CREATE_USERS)
        # миграция: добавить колонку payment в старые базы
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN payment TEXT NOT NULL DEFAULT 'none'")
        except Exception:
            pass  # колонка уже есть
        await db.commit()


# ---------- Заказы ----------

async def create_order(user_id, username, name, phone, pickup_time, cart, comment, total):
    items_str = ", ".join(f"{ITEMS[iid]['name']} x{q}" for iid, q in cart.items())
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO orders
               (user_id, username, name, phone, pickup_time, items, comment, total, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, username, name, phone, pickup_time, items_str, comment, total,
             datetime.now().isoformat(timespec="seconds")),
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


async def get_active_orders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM orders WHERE status NOT IN ('ready','cancelled') ORDER BY id DESC LIMIT ?",
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

async def upsert_user(user_id, username=None, name=None, phone=None):
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if await cur.fetchone():
            await db.execute(
                "UPDATE users SET username=COALESCE(?,username), "
                "name=COALESCE(?,name), phone=COALESCE(?,phone) WHERE user_id=?",
                (username, name, phone, user_id),
            )
        else:
            await db.execute(
                "INSERT INTO users (user_id, username, name, phone, created_at) VALUES (?,?,?,?,?)",
                (user_id, username, name, phone, now),
            )
        await db.commit()


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
