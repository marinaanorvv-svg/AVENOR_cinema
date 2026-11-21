"""SQL рабочего места кассира: смены, продажи (чеки), собственные операции. Только работа с БД, без бизнес-правил."""
from . import crud

GUEST_NAME = "Гость (касса)"   # общий клиент для продаж без указания покупателя


def get_or_create_guest(conn) -> int:
    row = conn.execute("SELECT id FROM clients WHERE full_name = ? AND phone IS NULL AND email IS NULL ORDER BY id",
                       (GUEST_NAME,)).fetchone()
    return row["id"] if row else crud.create_client(conn, GUEST_NAME)


# ------------------------------------------------------------------ смены

def get_open_shift(conn, cashier_id):
    return conn.execute("SELECT * FROM shifts WHERE cashier_id = ? AND closed_at IS NULL", (cashier_id,)).fetchone()


def list_shifts(conn, cashier_id, limit=30):
    return conn.execute("SELECT * FROM shifts WHERE cashier_id = ? ORDER BY id DESC LIMIT ?",
                        (cashier_id, limit)).fetchall()


def sales_totals(conn, shift_id):
    """Продажи смены по способам оплаты: [(способ, продаж, билетов, сумма)]."""
    return conn.execute(
        "SELECT COALESCE(sa.payment_method, 'unknown') AS method, COUNT(DISTINCT sa.id) AS sales, "
        "       COUNT(t.id) AS tickets, COALESCE(SUM(s.price), 0) AS amount "
        "FROM sales sa JOIN sessions s ON s.id = sa.session_id LEFT JOIN tickets t ON t.sale_id = sa.id "
        "WHERE sa.shift_id = ? GROUP BY method", (shift_id,)).fetchall()


def refund_totals(conn, cashier_id, start, end):
    """Возвраты, оформленные кассиром за период: [(способ оплаты исходной продажи, билетов, сумма)]."""
    return conn.execute(
        "SELECT COALESCE(sa.payment_method, 'unknown') AS method, COUNT(*) AS tickets, "
        "       COALESCE(SUM(s.price), 0) AS amount "
        "FROM tickets t JOIN sessions s ON s.id = t.session_id LEFT JOIN sales sa ON sa.id = t.sale_id "
        "WHERE t.status = 'returned' AND t.refunded_by = ? AND t.returned_at >= ? AND t.returned_at <= ? "
        "GROUP BY method", (cashier_id, start, end)).fetchall()


# ------------------------------------------------------------------ продажи и операции

def list_sales(conn, cashier_id, sale_id=None, date_from=None, date_to=None, movie_id=None):
    """Продажи ТОЛЬКО указанного кассира: с фильмом, сеансом и числом проданных/возвращённых билетов."""
    conditions, params = ["sa.cashier_id = ?"], [cashier_id]
    for clause, value in (("sa.id = ?", sale_id), ("date(sa.created_at) >= ?", date_from),
                          ("date(sa.created_at) <= ?", date_to), ("s.movie_id = ?", movie_id)):
        if value is not None:
            conditions.append(clause)
            params.append(value)
    return conn.execute(
        "SELECT sa.id, sa.created_at, sa.total, sa.payment_method, sa.session_id, sa.shift_id, "
        "       m.title AS movie_title, s.session_date, s.session_time, h.name AS hall_name, c.full_name AS client_name, "
        "       COUNT(t.id) AS tickets_total, "
        "       COALESCE(SUM(CASE WHEN t.status = 'sold' THEN 1 ELSE 0 END), 0) AS tickets_sold, "
        "       COALESCE(SUM(CASE WHEN t.status = 'returned' THEN 1 ELSE 0 END), 0) AS tickets_returned "
        "FROM sales sa JOIN sessions s ON s.id = sa.session_id JOIN movies m ON m.id = s.movie_id "
        "JOIN halls h ON h.id = s.hall_id JOIN clients c ON c.id = sa.client_id "
        "LEFT JOIN tickets t ON t.sale_id = sa.id "
        f"WHERE {' AND '.join(conditions)} GROUP BY sa.id ORDER BY sa.id DESC", params).fetchall()


def tickets_of_sale(conn, sale_id):
    return conn.execute("SELECT id FROM tickets WHERE sale_id = ? ORDER BY id", (sale_id,)).fetchall()


def recent_returns(conn, cashier_id, limit):
    return conn.execute(
        "SELECT t.id, t.returned_at, s.price, m.title AS movie_title FROM tickets t "
        "JOIN sessions s ON s.id = t.session_id JOIN movies m ON m.id = s.movie_id "
        "WHERE t.status = 'returned' AND t.refunded_by = ? ORDER BY t.returned_at DESC, t.id DESC LIMIT ?",
        (cashier_id, limit)).fetchall()
