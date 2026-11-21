"""SQL личного кабинета покупателя: заказы, популярность фильмов, профиль. Только работа с БД, без бизнес-правил."""


def popularity(conn) -> dict:
    """Фильм -> число действующих (не возвращённых) проданных билетов. Основа раздела «Популярное»."""
    rows = conn.execute("SELECT s.movie_id, COUNT(*) AS n FROM tickets t JOIN sessions s ON s.id = t.session_id "
                        "WHERE t.status = 'sold' GROUP BY s.movie_id").fetchall()
    return {r["movie_id"]: r["n"] for r in rows}


def posters_for_sessions(conn, session_ids) -> dict:
    """Сеанс -> (id фильма, путь к постеру): для карточек билетов."""
    ids = list(dict.fromkeys(session_ids))
    if not ids:
        return {}
    rows = conn.execute("SELECT s.id, m.id AS movie_id, m.poster_path FROM sessions s JOIN movies m ON m.id = s.movie_id "
                        f"WHERE s.id IN ({','.join('?' for _ in ids)})", ids).fetchall()
    return {r["id"]: (r["movie_id"], r["poster_path"]) for r in rows}


def list_orders(conn, user_id, order_id=None, date_from=None, date_to=None):
    """Заказы ТОЛЬКО указанного покупателя с фильмом, сеансом и числом проданных/возвращённых билетов."""
    conditions, params = ["o.user_id = ?"], [user_id]
    for clause, value in (("o.id = ?", order_id), ("date(o.created_at) >= ?", date_from),
                          ("date(o.created_at) <= ?", date_to)):
        if value is not None:
            conditions.append(clause)
            params.append(value)
    return conn.execute(
        "SELECT o.id, o.created_at, o.total, o.payment_method, o.session_id, "
        "       m.id AS movie_id, m.title AS movie_title, m.poster_path, s.session_date, s.session_time, "
        "       h.name AS hall_name, COUNT(t.id) AS tickets_total, "
        "       COALESCE(SUM(CASE WHEN t.status = 'sold' THEN 1 ELSE 0 END), 0) AS tickets_sold, "
        "       COALESCE(SUM(CASE WHEN t.status = 'returned' THEN 1 ELSE 0 END), 0) AS tickets_returned "
        "FROM orders o JOIN sessions s ON s.id = o.session_id JOIN movies m ON m.id = s.movie_id "
        "JOIN halls h ON h.id = s.hall_id LEFT JOIN tickets t ON t.order_id = o.id "
        f"WHERE {' AND '.join(conditions)} GROUP BY o.id ORDER BY o.id DESC", params).fetchall()


def order_ticket_ids(conn, order_id):
    return [r["id"] for r in conn.execute("SELECT id FROM tickets WHERE order_id = ? ORDER BY id", (order_id,))]


def profile_row(conn, user_id):
    return conn.execute("SELECT u.id, u.username, u.full_name, u.created_at, u.client_id, c.phone, c.email "
                        "FROM users u LEFT JOIN clients c ON c.id = u.client_id WHERE u.id = ?", (user_id,)).fetchone()
