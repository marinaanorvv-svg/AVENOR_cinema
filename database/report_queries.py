"""Агрегирующие SQL-запросы для отчётов (только чтение).

Деньги считаются по кассовому принципу:
  - продажа — в день покупки билета (tickets.purchase_date);
  - возврат — в день возврата (tickets.returned_at);
  - цена билета = цена сеанса (после первого билета она заблокирована для изменения).
"""

# Все значения подставляются из белых списков ниже, не из пользовательского ввода.
_DATE_COLUMN = {"sales": "t.purchase_date", "refunds": "t.returned_at"}
_GROUPING = {   # (выражение-ключ, выражение-подпись)
    "day": ("date({d})", "date({d})"),
    "movie": ("m.id", "m.title"),
    "hall": ("h.id", "h.name"),
}


def cash_flow(conn, kind, group_by, date_from, date_to):
    """Продажи или возвраты за период, сгруппированные по дню / фильму / залу.

    kind: 'sales' | 'refunds';  group_by: 'day' | 'movie' | 'hall'.
    Даты — строки 'YYYY-MM-DD', границы включительно.
    Возвращает строки с полями key, label, tickets (штук), amount (сумма).
    """
    date_col = _DATE_COLUMN[kind]
    key_expr, label_expr = (e.format(d=date_col) for e in _GROUPING[group_by])
    extra = "AND t.status = 'returned'" if kind == "refunds" else ""
    sql = (
        f"SELECT {key_expr} AS key, {label_expr} AS label, "
        f"       COUNT(*) AS tickets, COALESCE(SUM(s.price), 0) AS amount "
        f"FROM tickets t "
        f"JOIN sessions s ON s.id = t.session_id "
        f"JOIN movies   m ON m.id = s.movie_id "
        f"JOIN halls    h ON h.id = s.hall_id "
        f"WHERE {date_col} IS NOT NULL AND date({date_col}) BETWEEN ? AND ? {extra} "
        f"GROUP BY {key_expr}")
    return conn.execute(sql, (date_from, date_to)).fetchall()
