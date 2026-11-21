"""Отчёты по выручке и посещаемости + экспорт в CSV (только администратор).

Структура любого отчёта одинакова, поэтому GUI может рисовать его одним кодом:
    {"type": "revenue" | "attendance",
     "title": "...",
     "period": {"date_from": "2026-10-01", "date_to": "2026-10-31"},
     "summary": {...},                                   # итоговые показатели
     "tables": {"имя": {"title": "...",
                        "columns": [("ключ", "Заголовок"), ...],
                        "rows": [{"ключ": значение, ...}, ...],
                        "totals": {...} или None}}}      # строка «Итого»
"""
import csv
import io
from datetime import datetime, timedelta

from database import admin_queries, crud, report_queries
from database.connection import connection

from . import clock
from .errors import ValidationError
from .permissions import CurrentUser, Permission
from .validators import parse_date

MAX_PERIOD_DAYS = 366
TOP_SESSIONS = 10

_MONEY_COLUMNS = [("tickets_sold", "Продано, шт."), ("sales_amount", "Продажи, ₽"),
                  ("tickets_returned", "Возвращено, шт."), ("refund_amount", "Возвраты, ₽"),
                  ("net_revenue", "Выручка, ₽")]


# ------------------------------------------------------------------ вспомогательное

def _parse_period(date_from, date_to):
    start = parse_date(date_from, "Дата с")
    end = parse_date(date_to, "Дата по")
    if start > end:
        raise ValidationError("Дата начала периода позже даты окончания.")
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise ValidationError(f"Период не должен превышать {MAX_PERIOD_DAYS} дн.")
    return start, end


def _money(value) -> float:
    return round(float(value or 0), 2)


def _percent(part, whole) -> float:
    return round(part * 100 / whole, 1) if whole else 0.0


def _session_started(row) -> bool:
    start = datetime.strptime(f"{row['session_date']} {row['session_time']}", "%Y-%m-%d %H:%M")
    return clock.now() >= start


def _table(title, columns, rows, totals=None) -> dict:
    return {"title": title, "columns": columns, "rows": rows, "totals": totals}


# ------------------------------------------------------------------ выручка

def revenue_report(actor: CurrentUser, date_from, date_to, db_path=None) -> dict:
    """Выручка за период (кассовый метод).

    Продажи относятся ко дню покупки, возвраты — ко дню возврата.
    Выручка = продажи − возвраты. Поэтому возврат билета, купленного до начала периода,
    уменьшает выручку периода, в котором он оформлен (в отдельный день она может быть < 0).
    """
    actor.require(Permission.VIEW_REPORTS)
    start, end = _parse_period(date_from, date_to)
    f, t = start.isoformat(), end.isoformat()
    with connection(db_path) as conn:
        data = {(kind, group): report_queries.cash_flow(conn, kind, group, f, t)
                for kind in ("sales", "refunds") for group in ("day", "movie", "hall")}

    def merged(group):
        """Склеивает продажи и возвраты по ключу группы."""
        result = {}
        for kind in ("sales", "refunds"):
            for r in data[(kind, group)]:
                row = result.setdefault(r["key"], {
                    "label": r["label"], "tickets_sold": 0, "sales_amount": 0.0,
                    "tickets_returned": 0, "refund_amount": 0.0})
                if kind == "sales":
                    row["tickets_sold"], row["sales_amount"] = r["tickets"], _money(r["amount"])
                else:
                    row["tickets_returned"], row["refund_amount"] = r["tickets"], _money(r["amount"])
        for row in result.values():
            row["net_revenue"] = _money(row["sales_amount"] - row["refund_amount"])
        return result

    def totals_of(rows, label_key):
        total = {label_key: "Итого",
                 "tickets_sold": sum(r["tickets_sold"] for r in rows),
                 "sales_amount": _money(sum(r["sales_amount"] for r in rows)),
                 "tickets_returned": sum(r["tickets_returned"] for r in rows),
                 "refund_amount": _money(sum(r["refund_amount"] for r in rows))}
        total["net_revenue"] = _money(total["sales_amount"] - total["refund_amount"])
        return total

    # по дням — все дни периода, включая дни без операций (удобно для таблицы и графика)
    by_day_data, by_day = merged("day"), []
    for offset in range((end - start).days + 1):
        day = (start + timedelta(days=offset)).isoformat()
        row = by_day_data.get(day, {"tickets_sold": 0, "sales_amount": 0.0, "tickets_returned": 0,
                                    "refund_amount": 0.0, "net_revenue": 0.0})
        by_day.append({"date": day, **{k: v for k, v in row.items() if k != "label"}})

    def grouped(group, label_key):
        rows = [{label_key: r["label"], **{k: v for k, v in r.items() if k != "label"}}
                for r in merged(group).values()]
        return sorted(rows, key=lambda r: (-r["net_revenue"], r[label_key].casefold()))

    by_movie, by_hall = grouped("movie", "movie"), grouped("hall", "hall")
    summary = totals_of(by_day, "label")
    summary.pop("label")

    return {
        "type": "revenue", "title": "Отчёт по выручке",
        "period": {"date_from": f, "date_to": t},
        "summary": summary,
        "tables": {
            "by_day": _table("По дням", [("date", "Дата")] + _MONEY_COLUMNS, by_day,
                             totals_of(by_day, "date")),
            "by_movie": _table("По фильмам", [("movie", "Фильм")] + _MONEY_COLUMNS, by_movie,
                               totals_of(by_movie, "movie")),
            "by_hall": _table("По залам", [("hall", "Зал")] + _MONEY_COLUMNS, by_hall,
                              totals_of(by_hall, "hall")),
        }}


# ------------------------------------------------------------------ посещаемость

def attendance_report(actor: CurrentUser, date_from, date_to, include_upcoming=False,
                      db_path=None) -> dict:
    """Посещаемость сеансов, дата которых попадает в период.

    Зритель = действующий (не возвращённый) билет. По умолчанию учитываются только
    уже начавшиеся сеансы — будущие ещё нельзя считать посещёнными;
    include_upcoming=True добавляет и их (как предварительные продажи).
    Заполняемость = зрители / вместимость зала.
    """
    actor.require(Permission.VIEW_REPORTS)
    start, end = _parse_period(date_from, date_to)
    with connection(db_path) as conn:
        sessions = crud.list_sessions_detailed(conn, start.isoformat(), end.isoformat())
    if not include_upcoming:
        sessions = [s for s in sessions if _session_started(s)]

    by_session = [{
        "session_id": s["id"], "date": s["session_date"], "time": s["session_time"],
        "movie": s["movie_title"], "hall": s["hall_name"], "capacity": s["hall_capacity"],
        "visitors": s["sold_count"],
        "occupancy_percent": _percent(s["sold_count"], s["hall_capacity"])} for s in sessions]

    movies: dict[int, dict] = {}
    for s in sessions:
        m = movies.setdefault(s["movie_id"], {"movie": s["movie_title"], "sessions": 0,
                                              "visitors": 0, "capacity": 0})
        m["sessions"] += 1
        m["visitors"] += s["sold_count"]
        m["capacity"] += s["hall_capacity"]
    by_movie = sorted(
        ({**m, "occupancy_percent": _percent(m["visitors"], m["capacity"])} for m in movies.values()),
        key=lambda m: (-m["visitors"], m["movie"].casefold()))

    visitors = sum(r["visitors"] for r in by_session)
    capacity = sum(r["capacity"] for r in by_session)
    occupancy = _percent(visitors, capacity)

    halls: dict[str, dict] = {}
    for r in by_session:
        h = halls.setdefault(r["hall"], {"hall": r["hall"], "sessions": 0, "visitors": 0, "capacity": 0})
        h["sessions"] += 1
        h["visitors"] += r["visitors"]
        h["capacity"] += r["capacity"]
    by_hall = sorted(({**h, "occupancy_percent": _percent(h["visitors"], h["capacity"])} for h in halls.values()),
                     key=lambda h: (-h["occupancy_percent"], h["hall"].casefold()))
    top_sessions = sorted(by_session, key=lambda r: (-r["visitors"], r["date"], r["time"]))[:TOP_SESSIONS]
    return {
        "type": "attendance", "title": "Отчёт по посещаемости",
        "period": {"date_from": start.isoformat(), "date_to": end.isoformat()},
        "include_upcoming": include_upcoming,
        "summary": {"sessions": len(by_session), "visitors": visitors,
                    "capacity": capacity, "occupancy_percent": occupancy},
        "tables": {
            "by_session": _table(
                "По сеансам",
                [("date", "Дата"), ("time", "Время"), ("movie", "Фильм"), ("hall", "Зал"),
                 ("capacity", "Мест в зале"), ("visitors", "Зрителей"),
                 ("occupancy_percent", "Заполняемость, %")],
                by_session,
                {"date": "Итого", "capacity": capacity, "visitors": visitors,
                 "occupancy_percent": occupancy}),
            "by_movie": _table(
                "По фильмам",
                [("movie", "Фильм"), ("sessions", "Сеансов"), ("capacity", "Мест всего"),
                 ("visitors", "Зрителей"), ("occupancy_percent", "Заполняемость, %")],
                by_movie,
                {"movie": "Итого", "sessions": len(by_session), "capacity": capacity,
                 "visitors": visitors, "occupancy_percent": occupancy}),
            "by_hall": _table(
                "Заполняемость залов",
                [("hall", "Зал"), ("sessions", "Сеансов"), ("capacity", "Мест всего"),
                 ("visitors", "Зрителей"), ("occupancy_percent", "Заполняемость, %")],
                by_hall,
                {"hall": "Итого", "sessions": len(by_session), "capacity": capacity,
                 "visitors": visitors, "occupancy_percent": occupancy}),
            "top_sessions": _table(
                f"Самые посещаемые сеансы (топ {TOP_SESSIONS})",
                [("date", "Дата"), ("time", "Время"), ("movie", "Фильм"), ("hall", "Зал"),
                 ("visitors", "Зрителей"), ("occupancy_percent", "Заполняемость, %")],
                top_sessions, None),
        }}


# ------------------------------------------------------------------ продажи по кассирам

def cashier_report(actor: CurrentUser, date_from, date_to, db_path=None) -> dict:
    """Продажи по сотрудникам, оформившим билеты (по дате продажи).

    В строке — билеты, проданные сотрудником за период; «возвращено» — сколько из них вернули позже.
    Покупатели, купившие билет сами, показываются отдельной строкой «Покупатели (онлайн)». Билеты,
    оформленные до появления учёта продавца, — «Не определён».
    """
    actor.require(Permission.VIEW_REPORTS)
    start, end = _parse_period(date_from, date_to)
    with connection(db_path) as conn:
        data = admin_queries.sales_by_seller(conn, start.isoformat(), end.isoformat())
    merged: dict[str, dict] = {}
    for r in data:
        if r["seller_id"] is None:
            label = "Не определён"
        elif r["role"] == "viewer":
            label = "Покупатели (онлайн)"
        else:
            label = f"{r['full_name']} ({r['username']})"
        row = merged.setdefault(label, {"cashier": label, "tickets_sold": 0, "sales_amount": 0.0,
                                        "tickets_returned": 0, "refund_amount": 0.0})
        row["tickets_sold"] += r["tickets_sold"]
        row["sales_amount"] = _money(row["sales_amount"] + r["sales_amount"])
        row["tickets_returned"] += r["tickets_returned"]
        row["refund_amount"] = _money(row["refund_amount"] + r["refund_amount"])
    rows = sorted(merged.values(), key=lambda r: (-r["sales_amount"], r["cashier"].casefold()))
    for row in rows:
        row["net_revenue"] = _money(row["sales_amount"] - row["refund_amount"])
    totals = {"cashier": "Итого",
              "tickets_sold": sum(r["tickets_sold"] for r in rows),
              "sales_amount": _money(sum(r["sales_amount"] for r in rows)),
              "tickets_returned": sum(r["tickets_returned"] for r in rows),
              "refund_amount": _money(sum(r["refund_amount"] for r in rows))}
    totals["net_revenue"] = _money(totals["sales_amount"] - totals["refund_amount"])
    summary = {k: v for k, v in totals.items() if k != "cashier"}
    return {"type": "cashiers", "title": "Продажи по кассирам",
            "period": {"date_from": start.isoformat(), "date_to": end.isoformat()},
            "summary": summary,
            "tables": {"by_cashier": _table("По кассирам", [("cashier", "Сотрудник")] + _MONEY_COLUMNS, rows, totals)}}


# ------------------------------------------------------------------ экспорт в CSV

def _csv_cell(value):
    """Подготовка значения для CSV, открываемого в Excel (русская локаль)."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}".replace(".", ",")   # десятичная запятая — иначе Excel увидит текст/дату
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value   # защита от формул (CSV-injection): «=...» в названии не выполнится
    return value


def report_to_csv(report: dict, table: str | None = None) -> str:
    """Одна таблица отчёта -> текст CSV (разделитель «;», в конце строка «Итого»)."""
    tables = report["tables"]
    table = table or next(iter(tables))
    if table not in tables:
        raise ValidationError(f"В отчёте нет таблицы «{table}». Доступны: {', '.join(tables)}.")
    spec = tables[table]
    keys = [key for key, _ in spec["columns"]]
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow([header for _, header in spec["columns"]])
    for row in spec["rows"]:
        writer.writerow([_csv_cell(row.get(key)) for key in keys])
    if spec["totals"]:
        writer.writerow([_csv_cell(spec["totals"].get(key)) for key in keys])
    return out.getvalue()


def save_report_csv(actor: CurrentUser, report: dict, path, table: str | None = None) -> None:
    """Сохраняет таблицу отчёта в файл. Кодировка UTF-8 с BOM — Excel открывает без «кракозябр»."""
    actor.require(Permission.VIEW_REPORTS)
    text = report_to_csv(report, table)
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as file:
            file.write(text)
    except OSError as exc:
        raise ValidationError(f"Не удалось сохранить файл: {exc.strerror or exc}.") from exc
