"""Создание таблиц по схеме из ТЗ."""
import sqlite3

from .connection import get_connection

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS genres (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS movies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    genre_id    INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    duration    INTEGER NOT NULL CHECK (duration > 0),      -- минуты
    age_rating  TEXT    NOT NULL DEFAULT '0+',              -- '0+', '12+', '16+', '18+'
    description TEXT,
    poster_path TEXT                                            -- путь к файлу постера (необязательно)
);

CREATE TABLE IF NOT EXISTS halls (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT    NOT NULL UNIQUE,
    capacity INTEGER NOT NULL CHECK (capacity > 0)
);

CREATE TABLE IF NOT EXISTS seats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hall_id     INTEGER NOT NULL REFERENCES halls(id) ON DELETE CASCADE,
    row_number  INTEGER NOT NULL CHECK (row_number > 0),
    seat_number INTEGER NOT NULL CHECK (seat_number > 0),
    seat_type   TEXT    NOT NULL DEFAULT 'regular' CHECK (seat_type IN ('regular', 'vip')),
    UNIQUE (hall_id, row_number, seat_number)
);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id     INTEGER NOT NULL REFERENCES movies(id) ON DELETE RESTRICT,
    hall_id      INTEGER NOT NULL REFERENCES halls(id)  ON DELETE RESTRICT,
    session_date TEXT    NOT NULL,                          -- 'YYYY-MM-DD'
    session_time TEXT    NOT NULL,                          -- 'HH:MM'
    price        REAL    NOT NULL CHECK (price >= 0),
    is_cancelled INTEGER NOT NULL DEFAULT 0 CHECK (is_cancelled IN (0, 1)),   -- сеанс отменён администратором
    UNIQUE (hall_id, session_date, session_time)            -- в зале один сеанс в одно время
);

CREATE TABLE IF NOT EXISTS clients (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    phone     TEXT UNIQUE,
    email     TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'cashier', 'viewer')),
    full_name     TEXT NOT NULL,
    client_id     INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))  -- блокировка учётки
);

CREATE TABLE IF NOT EXISTS tickets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
    seat_id       INTEGER NOT NULL REFERENCES seats(id)    ON DELETE RESTRICT,
    client_id     INTEGER NOT NULL REFERENCES clients(id)  ON DELETE RESTRICT,
    purchase_date TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    status        TEXT    NOT NULL DEFAULT 'sold' CHECK (status IN ('sold', 'returned')),
    returned_at   TEXT,                                     -- дата/время возврата, пока билет не возвращён — NULL
    seller_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,  -- кто оформил продажу (для отчёта по кассирам)
    sale_id       INTEGER REFERENCES sales(id) ON DELETE RESTRICT,  -- продажа (чек), в составе которой оформлен билет
    refunded_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,  -- кто оформил возврат
    order_id      INTEGER REFERENCES orders(id) ON DELETE RESTRICT  -- заказ покупателя (онлайн-покупка), в составе которого оформлен билет
);

-- Рабочая смена кассира. Открытая смена — closed_at IS NULL; у одного кассира она может быть только одна.
CREATE TABLE IF NOT EXISTS shifts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cashier_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    opened_at  TEXT    NOT NULL,                        -- 'YYYY-MM-DD HH:MM:SS'
    closed_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_shifts_one_open ON shifts (cashier_id) WHERE closed_at IS NULL;

-- Продажа на кассе: один чек = один сеанс, один покупатель, один способ оплаты, несколько билетов.
CREATE TABLE IF NOT EXISTS sales (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cashier_id     INTEGER NOT NULL REFERENCES users(id)    ON DELETE RESTRICT,
    shift_id       INTEGER REFERENCES shifts(id)            ON DELETE RESTRICT,
    session_id     INTEGER NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
    client_id      INTEGER NOT NULL REFERENCES clients(id)  ON DELETE RESTRICT,
    payment_method TEXT CHECK (payment_method IS NULL OR payment_method IN ('cash', 'card')),
    total          REAL    NOT NULL CHECK (total >= 0),
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sales_cashier ON sales (cashier_id, created_at);

-- Заказ покупателя: один заказ = один сеанс, один покупатель, несколько билетов. Платёж тестовый (данные карты
-- не сохраняются). Статус заказа не хранится: он вычисляется по билетам (оформлен / частично возвращён / возвращён).
CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id)    ON DELETE RESTRICT,
    client_id      INTEGER NOT NULL REFERENCES clients(id)  ON DELETE RESTRICT,
    session_id     INTEGER NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
    payment_method TEXT CHECK (payment_method IS NULL OR payment_method IN ('card')),
    total          REAL    NOT NULL CHECK (total >= 0),
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_orders_user ON orders (user_id, created_at);

-- Главная защита от двойной продажи: уникальность (сеанс, место)
-- действует ТОЛЬКО для проданных билетов. Возвращённый билет не мешает
-- продать это же место снова.
CREATE UNIQUE INDEX IF NOT EXISTS ux_tickets_session_seat_sold
    ON tickets (session_id, seat_id) WHERE status = 'sold';

-- Место должно принадлежать залу, в котором идёт сеанс.
CREATE TRIGGER IF NOT EXISTS trg_tickets_seat_in_session_hall
BEFORE INSERT ON tickets
BEGIN
    SELECT RAISE(ABORT, 'Место не относится к залу этого сеанса')
    WHERE (SELECT hall_id FROM seats    WHERE id = NEW.seat_id)
       IS NOT (SELECT hall_id FROM sessions WHERE id = NEW.session_id);
END;

CREATE INDEX IF NOT EXISTS ix_sessions_date   ON sessions (session_date);
CREATE INDEX IF NOT EXISTS ix_tickets_session ON tickets (session_id);
CREATE INDEX IF NOT EXISTS ix_tickets_client  ON tickets (client_id);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Мягкая миграция: докидывает колонки, появившиеся после первых версий схемы,
    в уже существующий файл cinema.db (CREATE TABLE IF NOT EXISTS старую таблицу не меняет)."""
    def columns(table):
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

    if "poster_path" not in columns("movies"):
        conn.execute("ALTER TABLE movies ADD COLUMN poster_path TEXT")
    if "returned_at" not in columns("tickets"):
        conn.execute("ALTER TABLE tickets ADD COLUMN returned_at TEXT")
    if "is_cancelled" not in columns("sessions"):
        conn.execute("ALTER TABLE sessions ADD COLUMN is_cancelled INTEGER NOT NULL DEFAULT 0")
    if "seller_id" not in columns("tickets"):
        conn.execute("ALTER TABLE tickets ADD COLUMN seller_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    if "sale_id" not in columns("tickets"):
        conn.execute("ALTER TABLE tickets ADD COLUMN sale_id INTEGER REFERENCES sales(id) ON DELETE RESTRICT")
    if "refunded_by" not in columns("tickets"):
        conn.execute("ALTER TABLE tickets ADD COLUMN refunded_by INTEGER REFERENCES users(id) ON DELETE SET NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_tickets_sale ON tickets (sale_id)")
    if "order_id" not in columns("tickets"):
        conn.execute("ALTER TABLE tickets ADD COLUMN order_id INTEGER REFERENCES orders(id) ON DELETE RESTRICT")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_tickets_order ON tickets (order_id)")
    # дата регистрации учётной записи: у старых записей неизвестна (NULL), у новых ставится триггером
    if "created_at" not in columns("users"):
        conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS trg_users_created_at AFTER INSERT ON users WHEN NEW.created_at IS NULL "
        "BEGIN UPDATE users SET created_at = datetime('now', 'localtime') WHERE id = NEW.id; END")
    # индексы для отчётов по датам (создаются здесь, когда колонки точно есть)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_tickets_purchase_date ON tickets (purchase_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_tickets_returned_at ON tickets (returned_at)")


def _backfill_sales(conn: sqlite3.Connection) -> None:
    """Один раз, при появлении таблицы sales: билеты, ранее проданные кассирами, объединяются в продажи
    (кассир, сеанс, клиент, момент покупки), чтобы они попали в «Историю продаж» кассира.
    Способ оплаты у таких продаж неизвестен (NULL), смены нет."""
    groups = conn.execute(
        "SELECT t.seller_id, t.session_id, t.client_id, t.purchase_date, SUM(s.price) AS total, "
        "       GROUP_CONCAT(t.id) AS ids "
        "FROM tickets t JOIN sessions s ON s.id = t.session_id JOIN users u ON u.id = t.seller_id "
        "WHERE t.sale_id IS NULL AND u.role = 'cashier' "
        "GROUP BY t.seller_id, t.session_id, t.client_id, t.purchase_date").fetchall()
    for seller_id, session_id, client_id, purchase_date, total, ids in groups:
        sale_id = conn.execute(
            "INSERT INTO sales (cashier_id, shift_id, session_id, client_id, payment_method, total, created_at) "
            "VALUES (?, NULL, ?, ?, NULL, ?, ?)",
            (seller_id, session_id, client_id, total, purchase_date)).lastrowid
        conn.execute(f"UPDATE tickets SET sale_id = ? WHERE id IN ({ids})", (sale_id,))


def _backfill_orders(conn: sqlite3.Connection) -> None:
    """Один раз, при появлении таблицы orders: билеты, ранее купленные самими покупателями (продавец — учётная запись
    с ролью viewer), объединяются в заказы (покупатель, сеанс, момент покупки), чтобы попасть в «Историю покупок».
    Способ оплаты у таких заказов неизвестен (NULL)."""
    groups = conn.execute(
        "SELECT t.seller_id, t.client_id, t.session_id, t.purchase_date, SUM(s.price) AS total, "
        "       GROUP_CONCAT(t.id) AS ids "
        "FROM tickets t JOIN sessions s ON s.id = t.session_id JOIN users u ON u.id = t.seller_id "
        "WHERE t.order_id IS NULL AND u.role = 'viewer' "
        "GROUP BY t.seller_id, t.client_id, t.session_id, t.purchase_date").fetchall()
    for seller_id, client_id, session_id, purchase_date, total, ids in groups:
        order_id = conn.execute(
            "INSERT INTO orders (user_id, client_id, session_id, payment_method, total, created_at) "
            "VALUES (?, ?, ?, NULL, ?, ?)", (seller_id, client_id, session_id, total, purchase_date)).lastrowid
        conn.execute(f"UPDATE tickets SET order_id = ? WHERE id IN ({ids})", (order_id,))


def create_schema(conn: sqlite3.Connection) -> None:
    """Создаёт все таблицы, индексы и триггер (безопасно вызывать повторно)."""
    had_sales = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sales'").fetchone()
    had_orders = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'orders'").fetchone()
    conn.executescript(SCHEMA_SQL)
    _migrate(conn)
    if not had_sales:
        _backfill_sales(conn)
    if not had_orders:
        _backfill_orders(conn)
    conn.commit()


def init_db(db_path=None) -> None:
    """Открывает БД (создаёт файл, если его нет) и создаёт схему."""
    conn = get_connection(db_path)
    try:
        create_schema(conn)
    finally:
        conn.close()
