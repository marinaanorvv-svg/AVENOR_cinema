"""SQL для административных разделов (только чтение): главная панель, билеты с фильтрами, отчёты по кассирам.

Работа с БД остаётся в этом слое; сервисы (services/admin_service.py, report_service.py) только вызывают функции.
"""


def count_rows(conn, table) -> int:
    allowed = {"movies", "halls", "users", "genres"}
    if table not in allowed:
        raise ValueError(table)
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def count_users_by_role(conn, role) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE role = ?", (role,)).fetchone()[0]


def tickets_bought_on(conn, day_iso) -> int:
    """Сколько билетов оформлено в указанный день (включая позже возвращённые)."""
    return conn.execute("SELECT COUNT(*) FROM tickets WHERE date(purchase_date) = ?", (day_iso,)).fetchone()[0]


def tickets_returned_on(conn, day_iso) -> int:
    return conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'returned' AND date(returned_at) = ?",
                        (day_iso,)).fetchone()[0]


def recent_tickets(conn, limit=8):
    """Последние оформленные билеты (новые первыми)."""
    return conn.execute(
        "SELECT t.id, t.status, t.purchase_date, s.price, s.session_date, s.session_time, "
        "       m.title AS movie_title, c.full_name AS client_name, st.row_number, st.seat_number "
        "FROM tickets t JOIN sessions s ON s.id = t.session_id JOIN movies m ON m.id = s.movie_id "
        "JOIN clients c ON c.id = t.client_id JOIN seats st ON st.id = t.seat_id "
        "ORDER BY t.purchase_date DESC, t.id DESC LIMIT ?", (limit,)).fetchall()


_ADMIN_TICKET_SQL = (
    "SELECT t.*, c.full_name AS client_name, c.phone AS client_phone, c.email AS client_email, "
    "       s.session_date, s.session_time, s.price, s.hall_id, s.movie_id, s.is_cancelled, "
    "       m.title AS movie_title, m.duration AS duration, h.name AS hall_name, "
    "       st.row_number, st.seat_number, st.seat_type, "
    "       u.username AS seller_username, u.full_name AS seller_name, u.role AS seller_role "
    "FROM tickets t "
    "JOIN clients  c  ON c.id  = t.client_id "
    "JOIN sessions s  ON s.id  = t.session_id "
    "JOIN movies   m  ON m.id  = s.movie_id "
    "JOIN halls    h  ON h.id  = s.hall_id "
    "JOIN seats    st ON st.id = t.seat_id "
    "LEFT JOIN users u ON u.id = t.seller_id")


def list_tickets_admin(conn, ticket_id=None, movie_id=None, status=None, session_from=None, session_to=None,
                       bought_from=None, bought_to=None):
    """Все билеты с данными клиента, сеанса, зала, места и продавца. Все условия необязательны (И)."""
    conditions, params = [], []
    for clause, value in (("t.id = ?", ticket_id), ("s.movie_id = ?", movie_id), ("t.status = ?", status),
                          ("s.session_date >= ?", session_from), ("s.session_date <= ?", session_to),
                          ("date(t.purchase_date) >= ?", bought_from), ("date(t.purchase_date) <= ?", bought_to)):
        if value is not None:
            conditions.append(clause)
            params.append(value)
    sql = _ADMIN_TICKET_SQL + (" WHERE " + " AND ".join(conditions) if conditions else "")
    return conn.execute(sql + " ORDER BY t.id DESC", params).fetchall()


def sold_tickets_of_session(conn, session_id):
    """Действующие билеты сеанса вместе с ценой (для отмены сеанса)."""
    return conn.execute(
        "SELECT t.id, s.price FROM tickets t JOIN sessions s ON s.id = t.session_id "
        "WHERE t.session_id = ? AND t.status = 'sold'", (session_id,)).fetchall()


def genre_movie_counts(conn):
    """{id жанра: число фильмов}."""
    return {r[0]: r[1] for r in conn.execute("SELECT genre_id, COUNT(*) FROM movies GROUP BY genre_id")}


def sales_by_seller(conn, date_from, date_to):
    """Продажи по оформившим их сотрудникам за период (по дате покупки), включая возвращённые позже.

    Билеты без продавца (оформлены до появления поля) попадают в строку с seller_id NULL.
    """
    return conn.execute(
        "SELECT t.seller_id AS seller_id, u.username AS username, u.full_name AS full_name, u.role AS role, "
        "       COUNT(*) AS tickets_sold, COALESCE(SUM(s.price), 0) AS sales_amount, "
        "       SUM(CASE WHEN t.status = 'returned' THEN 1 ELSE 0 END) AS tickets_returned, "
        "       COALESCE(SUM(CASE WHEN t.status = 'returned' THEN s.price ELSE 0 END), 0) AS refund_amount "
        "FROM tickets t JOIN sessions s ON s.id = t.session_id LEFT JOIN users u ON u.id = t.seller_id "
        "WHERE date(t.purchase_date) BETWEEN ? AND ? GROUP BY t.seller_id", (date_from, date_to)).fetchall()
