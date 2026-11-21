"""Базовые CRUD-функции для всех таблиц.

Каждая функция первым аргументом принимает соединение `conn`.
Так сервисы смогут выполнить несколько операций в ОДНОЙ транзакции
(см. connection.transaction). Здесь нет бизнес-правил — только доступ к данным.
Все нарушения ограничений превращаются в ConstraintError, отсутствие записи —
в NotFoundError.
"""
import sqlite3

from .errors import ConstraintError, NotFoundError

# Белый список колонок для каждой таблицы. Имена колонок подставляются в SQL
# строкой (параметризовать их нельзя), поэтому принимаем только известные.
_COLUMNS = {
    "users": ("username", "password_hash", "role", "full_name", "client_id", "is_active"),
    "genres": ("name",),
    "movies": ("title", "genre_id", "duration", "age_rating", "description", "poster_path"),
    "halls": ("name", "capacity"),
    "seats": ("hall_id", "row_number", "seat_number", "seat_type"),
    "sessions": ("movie_id", "hall_id", "session_date", "session_time", "price", "is_cancelled"),
    "clients": ("full_name", "phone", "email"),
    "tickets": ("session_id", "seat_id", "client_id", "purchase_date", "status", "returned_at", "seller_id",
                "sale_id", "refunded_by", "order_id"),
    "shifts": ("cashier_id", "opened_at", "closed_at"),
    "orders": ("user_id", "client_id", "session_id", "payment_method", "total", "created_at"),
    "sales": ("cashier_id", "shift_id", "session_id", "client_id", "payment_method", "total", "created_at"),
}


# ---------------------------------------------------------------- внутренние помощники

def _to_constraint_error(exc: sqlite3.IntegrityError) -> ConstraintError:
    """Переводит ошибку SQLite в понятное сообщение."""
    msg = str(exc)
    if msg.startswith("UNIQUE"):
        return ConstraintError("Такая запись уже существует.", "unique", msg)
    if msg.startswith("FOREIGN KEY"):
        return ConstraintError(
            "Операция невозможна: запись связана с другими данными "
            "или ссылается на несуществующую запись.", "foreign_key", msg)
    if msg.startswith("NOT NULL"):
        return ConstraintError("Не заполнено обязательное поле.", "not_null", msg)
    if msg.startswith("CHECK"):
        return ConstraintError("Недопустимое значение поля.", "check", msg)
    # сюда попадают, например, ошибки триггера RAISE(ABORT, '...')
    return ConstraintError(msg, "other", msg)


def _execute(conn, sql, params=()):
    try:
        return conn.execute(sql, params)
    except sqlite3.IntegrityError as exc:
        raise _to_constraint_error(exc) from exc


def _check_columns(table, fields):
    unknown = set(fields) - set(_COLUMNS[table])
    if unknown:
        raise ValueError(f"Неизвестные поля для {table}: {', '.join(sorted(unknown))}")


def _insert(conn, table, **fields) -> int:
    _check_columns(table, fields)
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    cur = _execute(conn, f"INSERT INTO {table} ({cols}) VALUES ({marks})",
                   tuple(fields.values()))
    return cur.lastrowid


def _get(conn, table, row_id):
    return conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()


def _list(conn, table, order_by="id"):
    # order_by передаётся только из этого модуля (константы), не от пользователя
    return conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()


def _update(conn, table, row_id, **fields) -> None:
    if not fields:
        return
    _check_columns(table, fields)
    sets = ", ".join(f"{col} = ?" for col in fields)
    cur = _execute(conn, f"UPDATE {table} SET {sets} WHERE id = ?",
                   (*fields.values(), row_id))
    if cur.rowcount == 0:
        raise NotFoundError(f"Запись №{row_id} не найдена ({table}).")


def _delete(conn, table, row_id) -> None:
    cur = _execute(conn, f"DELETE FROM {table} WHERE id = ?", (row_id,))
    if cur.rowcount == 0:
        raise NotFoundError(f"Запись №{row_id} не найдена ({table}).")


# ---------------------------------------------------------------- genres

def create_genre(conn, name):
    return _insert(conn, "genres", name=name)

def get_genre(conn, genre_id):
    return _get(conn, "genres", genre_id)

def list_genres(conn):
    return _list(conn, "genres", "name")

def update_genre(conn, genre_id, **fields):
    _update(conn, "genres", genre_id, **fields)

def delete_genre(conn, genre_id):
    _delete(conn, "genres", genre_id)


# ---------------------------------------------------------------- movies

def create_movie(conn, title, genre_id, duration, age_rating="0+",
                 description=None, poster_path=None):
    return _insert(conn, "movies", title=title, genre_id=genre_id, duration=duration,
                   age_rating=age_rating, description=description, poster_path=poster_path)

def get_movie(conn, movie_id):
    return _get(conn, "movies", movie_id)

def list_movies(conn):
    return _list(conn, "movies", "title")

def update_movie(conn, movie_id, **fields):
    _update(conn, "movies", movie_id, **fields)

def delete_movie(conn, movie_id):
    _delete(conn, "movies", movie_id)


# ---------------------------------------------------------------- halls

def create_hall(conn, name, capacity):
    return _insert(conn, "halls", name=name, capacity=capacity)

def get_hall(conn, hall_id):
    return _get(conn, "halls", hall_id)

def list_halls(conn):
    return _list(conn, "halls", "name")

def update_hall(conn, hall_id, **fields):
    _update(conn, "halls", hall_id, **fields)

def delete_hall(conn, hall_id):
    _delete(conn, "halls", hall_id)


# ---------------------------------------------------------------- seats

def create_seat(conn, hall_id, row_number, seat_number, seat_type="regular"):
    return _insert(conn, "seats", hall_id=hall_id, row_number=row_number,
                   seat_number=seat_number, seat_type=seat_type)

def get_seat(conn, seat_id):
    return _get(conn, "seats", seat_id)

def list_seats(conn):
    return _list(conn, "seats", "hall_id, row_number, seat_number")

def list_seats_by_hall(conn, hall_id):
    """Все места зала в порядке ряд -> место (нужно для схемы зала)."""
    return conn.execute(
        "SELECT * FROM seats WHERE hall_id = ? ORDER BY row_number, seat_number",
        (hall_id,)).fetchall()

def update_seat(conn, seat_id, **fields):
    _update(conn, "seats", seat_id, **fields)

def delete_seat(conn, seat_id):
    _delete(conn, "seats", seat_id)


# ---------------------------------------------------------------- sessions

def create_session(conn, movie_id, hall_id, session_date, session_time, price):
    return _insert(conn, "sessions", movie_id=movie_id, hall_id=hall_id,
                   session_date=session_date, session_time=session_time, price=price)

def get_session(conn, session_id):
    return _get(conn, "sessions", session_id)

def list_sessions(conn):
    return _list(conn, "sessions", "session_date, session_time")

def update_session(conn, session_id, **fields):
    _update(conn, "sessions", session_id, **fields)

def delete_session(conn, session_id):
    _delete(conn, "sessions", session_id)


# ---------------------------------------------------------------- clients

def create_client(conn, full_name, phone=None, email=None):
    return _insert(conn, "clients", full_name=full_name, phone=phone, email=email)

def get_client(conn, client_id):
    return _get(conn, "clients", client_id)

def list_clients(conn):
    return _list(conn, "clients", "full_name")

def update_client(conn, client_id, **fields):
    _update(conn, "clients", client_id, **fields)

def delete_client(conn, client_id):
    _delete(conn, "clients", client_id)


# ---------------------------------------------------------------- users
# password_hash сюда приходит УЖЕ готовым: хеширование — задача модуля аутентификации.

def create_user(conn, username, password_hash, role, full_name, client_id=None, is_active=1):
    return _insert(conn, "users", username=username, password_hash=password_hash,
                   role=role, full_name=full_name, client_id=client_id, is_active=is_active)

def get_user(conn, user_id):
    return _get(conn, "users", user_id)

def get_user_by_username(conn, username):
    """Поиск для входа в систему; None, если такого логина нет."""
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

def list_users(conn):
    return _list(conn, "users", "username")

def update_user(conn, user_id, **fields):
    _update(conn, "users", user_id, **fields)

def delete_user(conn, user_id):
    _delete(conn, "users", user_id)


# ---------------------------------------------------------------- tickets
# Здесь только «голый» доступ к данным. Продажа и возврат с проверками —
# в services (шаг 5).

def create_ticket(conn, session_id, seat_id, client_id, status="sold", purchase_date=None, seller_id=None):
    fields = dict(session_id=session_id, seat_id=seat_id, client_id=client_id, status=status)
    if purchase_date is not None:       # иначе БД проставит текущее время сама
        fields["purchase_date"] = purchase_date
    if seller_id is not None:           # кто оформил продажу (нужно для отчёта по кассирам)
        fields["seller_id"] = seller_id
    return _insert(conn, "tickets", **fields)

def get_ticket(conn, ticket_id):
    return _get(conn, "tickets", ticket_id)

def list_tickets(conn):
    return _list(conn, "tickets", "id DESC")

def update_ticket(conn, ticket_id, **fields):
    _update(conn, "tickets", ticket_id, **fields)

def delete_ticket(conn, ticket_id):
    _delete(conn, "tickets", ticket_id)


# ---------------------------------------------------------------- дополнительные запросы
# Нужны сервисам справочников: выборки с JOIN, подсчёт связанных записей, массовые операции.
# Сортировку по тексту (кириллица, регистр) сервисы делают в Python:
# SQLite сортирует не-ASCII символы по кодам и «ё»/заглавные буквы оказываются не на месте.

def list_movies_with_genre(conn):
    """Фильмы вместе с названием жанра (поле genre_name)."""
    return conn.execute(
        "SELECT m.*, g.name AS genre_name FROM movies m "
        "JOIN genres g ON g.id = m.genre_id").fetchall()

def get_movie_with_genre(conn, movie_id):
    return conn.execute(
        "SELECT m.*, g.name AS genre_name FROM movies m "
        "JOIN genres g ON g.id = m.genre_id WHERE m.id = ?", (movie_id,)).fetchone()

def count_movies_by_genre(conn, genre_id):
    return conn.execute("SELECT COUNT(*) FROM movies WHERE genre_id = ?", (genre_id,)).fetchone()[0]

def count_sessions_by_movie(conn, movie_id):
    return conn.execute("SELECT COUNT(*) FROM sessions WHERE movie_id = ?", (movie_id,)).fetchone()[0]

def count_sessions_by_hall(conn, hall_id):
    return conn.execute("SELECT COUNT(*) FROM sessions WHERE hall_id = ?", (hall_id,)).fetchone()[0]

def count_tickets_for_seats(conn, seat_ids):
    """Сколько билетов (в любом статусе) оформлено на перечисленные места."""
    seat_ids = list(seat_ids)
    if not seat_ids:
        return 0
    marks = ", ".join("?" for _ in seat_ids)
    return conn.execute(f"SELECT COUNT(*) FROM tickets WHERE seat_id IN ({marks})",
                        seat_ids).fetchone()[0]

def create_seats_bulk(conn, hall_id, seats):
    """Массово добавляет места. seats — итерируемое из (ряд, место, тип)."""
    try:
        conn.executemany(
            "INSERT INTO seats (hall_id, row_number, seat_number, seat_type) VALUES (?, ?, ?, ?)",
            [(hall_id, row, number, seat_type) for row, number, seat_type in seats])
    except sqlite3.IntegrityError as exc:
        raise _to_constraint_error(exc) from exc

def delete_seats_by_hall(conn, hall_id):
    _execute(conn, "DELETE FROM seats WHERE hall_id = ?", (hall_id,))


# ---------------------------------------------------------------- сеансы: расширенные запросы

def list_sessions_detailed(conn, date_from=None, date_to=None, hall_id=None,
                           movie_id=None, session_id=None, include_cancelled=False):
    """Сеансы с данными фильма, жанра и зала + число проданных билетов.

    Отменённые администратором сеансы по умолчанию скрыты (их нет ни в афише, ни в продаже);
    include_cancelled=True показывает и их (раздел «Сеансы» администратора).

    Даты — строки 'YYYY-MM-DD' (сравниваются как текст, формат это позволяет).
    Результат отсортирован по дате и времени.
    """
    sql = (
        "SELECT s.*, m.title AS movie_title, m.duration AS duration, "
        "       m.age_rating AS age_rating, m.description AS description, "
        "       m.poster_path AS poster_path, g.name AS genre_name, "
        "       h.name AS hall_name, h.capacity AS hall_capacity, "
        "       (SELECT COUNT(*) FROM tickets t "
        "         WHERE t.session_id = s.id AND t.status = 'sold') AS sold_count "
        "FROM sessions s "
        "JOIN movies m ON m.id = s.movie_id "
        "JOIN genres g ON g.id = m.genre_id "
        "JOIN halls  h ON h.id = s.hall_id")
    conditions, params = [], []
    if not include_cancelled:
        conditions.append("s.is_cancelled = 0")
    for clause, value in (("s.session_date >= ?", date_from), ("s.session_date <= ?", date_to),
                          ("s.hall_id = ?", hall_id), ("s.movie_id = ?", movie_id),
                          ("s.id = ?", session_id)):
        if value is not None:
            conditions.append(clause)
            params.append(value)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY s.session_date, s.session_time"
    return conn.execute(sql, params).fetchall()

def get_session_detailed(conn, session_id):
    rows = list_sessions_detailed(conn, session_id=session_id)
    return rows[0] if rows else None

def count_tickets_by_session(conn, session_id, status=None):
    """Билеты сеанса; status='sold'/'returned' или None — любые."""
    if status is None:
        return conn.execute("SELECT COUNT(*) FROM tickets WHERE session_id = ?",
                            (session_id,)).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM tickets WHERE session_id = ? AND status = ?",
                        (session_id, status)).fetchone()[0]


# ---------------------------------------------------------------- билеты и клиенты: запросы

def get_client_by_phone(conn, phone):
    return conn.execute("SELECT * FROM clients WHERE phone = ?", (phone,)).fetchone()

def get_client_by_email(conn, email):
    return conn.execute("SELECT * FROM clients WHERE email = ?", (email,)).fetchone()

def get_sold_ticket(conn, session_id, seat_id):
    """Действующий (не возвращённый) билет на место сеанса или None."""
    return conn.execute(
        "SELECT * FROM tickets WHERE session_id = ? AND seat_id = ? AND status = 'sold'",
        (session_id, seat_id)).fetchone()

def list_sold_tickets_by_session(conn, session_id):
    return conn.execute(
        "SELECT id, seat_id FROM tickets WHERE session_id = ? AND status = 'sold'",
        (session_id,)).fetchall()

_TICKET_DETAILED_SQL = (
    "SELECT t.*, c.full_name AS client_name, c.phone AS client_phone, c.email AS client_email, "
    "       s.session_date, s.session_time, s.price, s.hall_id, "
    "       m.title AS movie_title, m.duration AS duration, h.name AS hall_name, "
    "       st.row_number, st.seat_number, st.seat_type "
    "FROM tickets t "
    "JOIN clients  c  ON c.id  = t.client_id "
    "JOIN sessions s  ON s.id  = t.session_id "
    "JOIN movies   m  ON m.id  = s.movie_id "
    "JOIN halls    h  ON h.id  = s.hall_id "
    "JOIN seats    st ON st.id = t.seat_id")

def list_tickets_detailed(conn, ticket_id=None, session_id=None, client_id=None,
                          status=None, date_from=None, date_to=None):
    """Билеты со всеми данными для отображения (клиент, сеанс, фильм, зал, место).
    Даты — по дате СЕАНСА, формат 'YYYY-MM-DD'. Новые билеты — первыми."""
    conditions, params = [], []
    for clause, value in (("t.id = ?", ticket_id), ("t.session_id = ?", session_id),
                          ("t.client_id = ?", client_id), ("t.status = ?", status),
                          ("s.session_date >= ?", date_from), ("s.session_date <= ?", date_to)):
        if value is not None:
            conditions.append(clause)
            params.append(value)
    sql = _TICKET_DETAILED_SQL
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    return conn.execute(sql + " ORDER BY t.id DESC", params).fetchall()

def get_ticket_detailed(conn, ticket_id):
    rows = list_tickets_detailed(conn, ticket_id=ticket_id)
    return rows[0] if rows else None


# ---------------------------------------------------------------- смены и продажи (касса)

def create_shift(conn, cashier_id, opened_at):
    return _insert(conn, "shifts", cashier_id=cashier_id, opened_at=opened_at)

def get_shift(conn, shift_id):
    return _get(conn, "shifts", shift_id)

def update_shift(conn, shift_id, **fields):
    _update(conn, "shifts", shift_id, **fields)

def create_sale(conn, cashier_id, shift_id, session_id, client_id, payment_method, total, created_at):
    return _insert(conn, "sales", cashier_id=cashier_id, shift_id=shift_id, session_id=session_id,
                   client_id=client_id, payment_method=payment_method, total=total, created_at=created_at)

def get_sale(conn, sale_id):
    return _get(conn, "sales", sale_id)


# ---------------------------------------------------------------- заказы покупателей

def create_order(conn, user_id, client_id, session_id, payment_method, total, created_at):
    return _insert(conn, "orders", user_id=user_id, client_id=client_id, session_id=session_id,
                   payment_method=payment_method, total=total, created_at=created_at)

def get_order(conn, order_id):
    return _get(conn, "orders", order_id)
