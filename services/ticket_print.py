"""Готовый билет: уникальный код и печатная форма (HTML). Без tkinter — проверяется обычными тестами.

Каждый билет строится по реальной записи из БД (ticket_service). HTML открывается в любом браузере:
оттуда его можно напечатать или сохранить в PDF («Печать» -> «Сохранить как PDF»).
"""
import hashlib
from html import escape

from .errors import ValidationError

CINEMA_NAME = "AVENOR"
PAYMENT_TITLES = {"cash": "Наличные", "card": "Банковская карта", "unknown": "Не указан", None: "Не указан"}


def ticket_code(ticket: dict) -> str:
    """Уникальный идентификатор билета: номер + контрольная часть от данных билета (AVN-000123-9F2A4C).

    Контрольная часть считается от номера, сеанса, места и времени покупки, поэтому подделать номер
    без пересчёта нельзя, а на кассе код можно сверить с базой.
    """
    raw = f"{ticket['id']}|{ticket['session_id']}|{ticket['seat_id']}|{ticket['purchase_date']}"
    return f"AVN-{int(ticket['id']):06d}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:6].upper()}"


def _date_ru(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}"


def ticket_lines(ticket: dict) -> list[tuple[str, str]]:
    """Подписи и значения полей билета в порядке показа (и на экране, и в печатной форме)."""
    price = float(ticket["price"])
    price_text = (f"{int(price)} ₽" if price == int(price) else f"{price:.2f}".replace(".", ",") + " ₽")
    category = "VIP" if ticket.get("seat_type") == "vip" else "Обычное"
    purchased = ticket["purchase_date"]
    return [("Фильм", ticket["movie_title"]),
            ("Дата просмотра", _date_ru(ticket["session_date"])),
            ("Начало сеанса", ticket["session_time"]),
            ("Зал", ticket["hall_name"]),
            ("Ряд", str(ticket["row_number"])),
            ("Место", f"{ticket['seat_number']} ({category})"),
            ("Стоимость", price_text),
            ("Дата покупки", f"{_date_ru(purchased[:10])} {purchased[11:16]}")]


def tickets_html(tickets: list[dict]) -> str:
    """Самодостаточная HTML-страница: по билету на странице, кнопка «Печать» не попадает на бумагу."""
    if not tickets:
        raise ValidationError("Нет билетов для печати.")
    cards = []
    for ticket in tickets:
        rows = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in ticket_lines(ticket))
        cards.append(
            f'<section class="ticket"><header><span class="logo">{CINEMA_NAME}</span>'
            f'<span class="num">Билет № {ticket["id"]}</span></header><table>{rows}</table>'
            f'<footer>Код билета: <b>{escape(ticket_code(ticket))}</b></footer></section>')
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Билеты {CINEMA_NAME}</title>
<style>
body {{ font-family: "Segoe UI", Arial, sans-serif; background: #f3eefc; margin: 0; padding: 24px; color: #1c1033; }}
.ticket {{ width: 560px; margin: 0 auto 24px; background: #fff; border: 2px solid #7c3aed; border-radius: 16px;
          padding: 20px 28px; page-break-after: always; }}
header {{ display: flex; justify-content: space-between; align-items: baseline; border-bottom: 2px dashed #c4a5f5;
         padding-bottom: 10px; margin-bottom: 10px; }}
.logo {{ font-size: 28px; font-weight: 700; letter-spacing: 6px; color: #7c3aed; }}
.num {{ font-size: 18px; font-weight: 600; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ text-align: left; width: 38%; color: #6b5a8f; font-weight: 500; padding: 5px 0; }}
td {{ font-weight: 600; padding: 5px 0; }}
footer {{ margin-top: 12px; padding-top: 10px; border-top: 2px dashed #c4a5f5; font-size: 14px; color: #6b5a8f; }}
button {{ display: block; margin: 0 auto 20px; padding: 10px 28px; font-size: 16px; border: 0; border-radius: 20px;
         background: #7c3aed; color: #fff; cursor: pointer; }}
@media print {{ body {{ background: #fff; padding: 0; }} button {{ display: none; }} }}
</style></head><body>
<button onclick="window.print()">Печать / сохранить в PDF</button>
{''.join(cards)}
</body></html>"""


def save_tickets_html(path, tickets: list[dict]) -> None:
    html = tickets_html(tickets)
    try:
        with open(path, "w", encoding="utf-8") as file:
            file.write(html)
    except OSError as exc:
        raise ValidationError(f"Не удалось сохранить файл: {exc.strerror or exc}.") from exc
