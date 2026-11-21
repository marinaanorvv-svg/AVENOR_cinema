"""Чистые функции форматирования данных для экранов (без tkinter)."""
import os
import re
from datetime import date, datetime, timedelta

from services import clock
from services.validators import parse_date

ROLE_TITLES = {"admin": "Администратор", "cashier": "Кассир", "viewer": "Покупатель"}
_NBSP = "\u00a0"   # неразрывный пробел: «1 200 ₽» не переносится по строкам


def role_title(role: str) -> str:
    return ROLE_TITLES.get(role, role)


def user_caption(user) -> str:
    """«Анна Кассир · Кассир»; если имя совпадает с названием роли — просто «Администратор»."""
    title = role_title(user.role)
    return user.full_name if user.full_name.strip().casefold() == title.casefold() else f"{user.full_name} · {title}"


def format_price(value) -> str:
    """300 -> «300 ₽», 1200 -> «1 200 ₽», 350.5 -> «350,50 ₽»."""
    value = float(value)
    if value == int(value):
        return f"{int(value):,}".replace(",", _NBSP) + f"{_NBSP}₽"
    return f"{value:,.2f}".replace(",", _NBSP).replace(".", ",") + f"{_NBSP}₽"


def format_duration(minutes: int) -> str:
    """100 -> «1 ч 40 мин», 120 -> «2 ч», 45 -> «45 мин»."""
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours} ч {mins} мин"
    return f"{hours} ч" if hours else f"{mins} мин"


# ------------------------------------------------------------------ даты (в интерфейсе — ДД.ММ.ГГГГ)

def bind_format(var, formatter) -> None:
    """Каждое изменение StringVar сразу приводится к нужному виду (пробелы, «/», заглавные и т. д.)."""
    def _apply(*_):
        current = var.get()
        fixed = formatter(current)
        if fixed != current:
            var.set(fixed)
    var.trace_add("write", _apply)


def format_card_number(text: str) -> str:
    """Ввод номера карты: только цифры, не больше 16, группы по 4 через пробел («4242 4242 4242 4242»)."""
    digits = "".join(ch for ch in (text or "") if ch.isdigit())[:16]
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def format_expiry(text: str) -> str:
    """Срок карты: цифры, после двух цифр сам ставится «/» («1228» -> «12/28»). Месяц 13–99 превращается в 0X."""
    digits = "".join(ch for ch in (text or "") if ch.isdigit())[:4]
    if len(digits) == 1 and digits > "1":
        digits = "0" + digits
    if len(digits) >= 2 and int(digits[:2]) > 12:
        digits = "0" + digits[0] + digits[1:3]
        digits = digits[:4]
    return digits if len(digits) <= 2 else digits[:2] + "/" + digits[2:]     # «/» только перед 3-й цифрой: Backspace не «застревает»


def format_cvc(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isdigit())[:3]


def format_holder(text: str) -> str:
    """Имя владельца карты: латиница заглавными, один пробел между словами."""
    cleaned = "".join(ch for ch in (text or "") if ch.isascii() and (ch.isalpha() or ch == " "))
    return re.sub(r" {2,}", " ", cleaned.lstrip()).upper()[:40]


def format_phone_input(text: str) -> str:
    """Телефон при вводе: «+7 916 903-56-00». Ведущие 8 и 7 считаются кодом страны."""
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    if not digits:
        return ""
    if digits[0] in "78":
        digits = digits[1:]
    digits = digits[:10]
    out = "+7"
    if digits:
        out += " " + digits[:3]
    if len(digits) > 3:
        out += " " + digits[3:6]
    if len(digits) > 6:
        out += "-" + digits[6:8]
    if len(digits) > 8:
        out += "-" + digits[8:10]
    return out


def format_date_ru(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def today_ru() -> str:
    return format_date_ru(clock.now().date())


def normalize_date_input(text: str) -> str:
    """Принимает ДД.ММ.ГГГГ или ГГГГ-ММ-ДД, возвращает ДД.ММ.ГГГГ. Ошибка — ValidationError."""
    return format_date_ru(parse_date(text))


def shift_date(text: str, days: int) -> str:
    return format_date_ru(parse_date(text) + timedelta(days=days))


# ------------------------------------------------------------------ сеансы

def time_range(session: dict) -> str:
    """«18:00–19:40»; если фильм заканчивается после полуночи — «23:00–01:00 (+1 д)»."""
    result = f"{session['session_time']}–{session['end_time']}"
    if session["end_time"] < session["session_time"]:   # время вида ЧЧ:ММ сравнимо как строка
        result += " (+1 д)"
    return result


def upcoming_times(sessions: list[dict], limit: int = 4) -> str:
    """Подпись на постере афиши: «10:00 · 13:30 · 17:00». Уже начавшиеся сеансы не показываются."""
    times = [s["session_time"] for s in sessions if not s.get("started")]
    if not times:
        return "Сеансов больше нет"
    return " · ".join(times[:limit]) + (" …" if len(times) > limit else "")


_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def day_caption(day_iso: str, today: date) -> str:
    """Подпись кнопки дня: «Сегодня», «Завтра» или «30.10 пт»."""
    day = datetime.strptime(day_iso, "%Y-%m-%d").date()
    if day == today:
        return "Сегодня"
    if day == today + timedelta(days=1):
        return "Завтра"
    return f"{day:%d.%m} {_WEEKDAYS[day.weekday()]}"


def short_description(text, limit: int = 230) -> str:
    """Описание фильма для обратной стороны постера: длинное обрезается по слову и заканчивается многоточием."""
    text = " ".join((text or "").split()) or "Описание не указано."
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:-—") + "…"


def end_caption(session: dict) -> str:
    """«до 19:40»; если сеанс заканчивается на следующий день — «до 01:10 (29.10)»."""
    if session.get("end_date") and session["end_date"] != session["session_date"]:
        return f"до {session['end_time']} ({session['end_date'][8:10]}.{session['end_date'][5:7]})"
    return f"до {session['end_time']}"


def session_row(session: dict) -> tuple:
    """Значения строки таблицы расписания (порядок = колонки ScheduleFrame.COLUMNS)."""
    return (time_range(session), session["movie_title"], session["genre_name"],
            session["age_rating"], session["hall_name"], format_price(session["price"]),
            f"{session['seats_free']} из {session['seats_total']}")


def session_tag(session: dict, now: datetime | None = None) -> str:
    """Стиль строки: 'past' — сеанс уже начался, 'soldout' — мест нет, '' — обычный."""
    now = now or clock.now()
    start = datetime.strptime(f"{session['session_date']} {session['session_time']}", "%Y-%m-%d %H:%M")
    if now >= start:
        return "past"
    return "soldout" if session["seats_free"] <= 0 else ""


def session_details(session: dict) -> tuple[str, str, str]:
    """(название, строка с параметрами, описание) для панели справа."""
    info = "\n".join([
        f"{session['genre_name']} · {format_duration(session['duration'])} · {session['age_rating']}",
        f"Сеанс: {session['session_date'][8:10]}.{session['session_date'][5:7]}, {time_range(session)}",
        f"Зал: {session['hall_name']}",
        f"Цена билета: {format_price(session['price'])}",
        f"Свободно мест: {session['seats_free']} из {session['seats_total']}",
    ])
    return session["movie_title"], info, session.get("description") or "Описание не указано."


def poster_path_if_displayable(path) -> str | None:
    """Tkinter без Pillow умеет показывать только PNG и GIF; для остального — заглушка."""
    if path and os.path.splitext(path)[1].lower() in (".png", ".gif") and os.path.isfile(path):
        return path
    return None


# ------------------------------------------------------------------ билеты, продажа

STATUS_TITLES = {"sold": "Продан", "returned": "Возвращён"}


def date_ru_from_iso(text: str) -> str:
    """'2026-11-01' -> '01.11.2026'."""
    return format_date_ru(datetime.strptime(text, "%Y-%m-%d").date())


def datetime_ru(text: str) -> str:
    """'2026-10-16 12:00:00' -> '16.10.2026 12:00'."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")


def ticket_row(ticket: dict) -> tuple:
    """Строка таблицы билетов (порядок = TICKET_COLUMNS в tickets_frame)."""
    return (ticket["id"], ticket["movie_title"], date_ru_from_iso(ticket["session_date"]),
            ticket["session_time"], ticket["hall_name"], ticket["seat_label"],
            ticket["client_name"], format_price(ticket["price"]),
            STATUS_TITLES.get(ticket["status"], ticket["status"]), datetime_ru(ticket["purchase_date"]))


def ticket_tag(ticket: dict) -> str:
    if ticket["status"] == "returned":
        return "returned"
    return "past" if ticket["session_started"] else ""


def receipt_text(tickets: list[dict]) -> str:
    """Текст чека для списка билетов одной покупки."""
    first = tickets[0]
    total = sum(t["price"] for t in tickets)
    return "\n".join([
        f"Фильм: {first['movie_title']}",
        f"Зал: {first['hall_name']}",
        f"Сеанс: {date_ru_from_iso(first['session_date'])}, {first['session_time']}",
        "Места: " + "; ".join(t["seat_label"] for t in tickets),
        "Билеты №: " + ", ".join(str(t["id"]) for t in tickets),
        f"Клиент: {first['client_name']}",
        f"Итого: {format_price(total)}",
    ])


def client_payload(picked: dict | None, full_name, phone, email):
    """Что передать в sell_tickets как client.

    Если кассир выбрал клиента из поиска и не менял его данные — передаём его id,
    иначе словарь с введёнными данными (сервис сам найдёт клиента по телефону/email
    или создаст нового).
    """
    name, phone, email = (full_name or "").strip(), (phone or "").strip(), (email or "").strip()
    if (picked and name == picked["full_name"] and phone == (picked.get("phone") or "")
            and email == (picked.get("email") or "")):
        return picked["id"]
    return {"full_name": name, "phone": phone, "email": email}


def selection_summary(rows: list[dict], selected_ids, price) -> tuple[list[str], float]:
    """Подписи выбранных мест (в порядке схемы) и общая сумма."""
    labels = [f"ряд {row['row_number']}, место {seat['seat_number']}"
              for row in rows for seat in row["seats"] if seat["id"] in selected_ids]
    return labels, float(price) * len(labels)


def seats_caption(rows: list[dict], selected_ids) -> str:
    """Выбранные места по рядам: «Ряд 3, места 5 и 6; ряд 4, место 1»."""
    parts = []
    for row in rows:
        numbers = [seat["seat_number"] for seat in row["seats"] if seat["id"] in selected_ids]
        if not numbers:
            continue
        if len(numbers) == 1:
            places = f"место {numbers[0]}"
        elif len(numbers) == 2:
            places = f"места {numbers[0]} и {numbers[1]}"
        else:
            places = "места " + ", ".join(map(str, numbers[:-1])) + f" и {numbers[-1]}"
        parts.append(f"ряд {row['row_number']}, {places}")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:]


# ------------------------------------------------------------------ залы, формы

def layout_of_scheme(scheme: dict) -> tuple[int, int, list[int]]:
    """(рядов, мест в ряду, VIP-ряды) по схеме зала — для предзаполнения формы."""
    rows = scheme["rows"]
    per_row = max((len(r["seats"]) for r in rows), default=0)
    vip_rows = [r["row_number"] for r in rows
                if r["seats"] and all(s["seat_type"] == "vip" for s in r["seats"])]
    return len(rows), per_row, vip_rows


def price_input(value) -> str:
    """350.0 -> '350', 350.5 -> '350,5' (для поля ввода)."""
    value = float(value)
    return str(int(value)) if value == int(value) else str(value).replace(".", ",")


# ------------------------------------------------------------------ отчёты

_MONEY_KEYS = ("sales_amount", "refund_amount", "net_revenue")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def format_report_cell(key: str, value) -> str:
    """Значение ячейки таблицы отчёта для показа на экране."""
    if value is None:
        return ""
    if key in _MONEY_KEYS:
        return format_price(value)
    if key.endswith("_percent"):
        return f"{value:.1f}".replace(".", ",") + f"{_NBSP}%"
    if key == "date" and isinstance(value, str) and _ISO_DATE.fullmatch(value):
        return date_ru_from_iso(value)
    return str(value)


def summary_text(report: dict) -> str:
    s = report["summary"]
    if report["type"] in ("revenue", "cashiers"):
        return (f"Продано билетов: {s['tickets_sold']}  ·  Продажи: {format_price(s['sales_amount'])}  ·  "
                f"Возвраты: {s['tickets_returned']} ({format_price(s['refund_amount'])})  ·  "
                f"Выручка: {format_price(s['net_revenue'])}")
    return (f"Сеансов: {s['sessions']}  ·  Зрителей: {s['visitors']}  ·  Мест: {s['capacity']}  ·  "
            f"Заполняемость: {format_report_cell('occupancy_percent', s['occupancy_percent'])}")
