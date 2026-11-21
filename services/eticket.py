"""Электронный билет покупателя: печатная форма (HTML) с постером. Без tkinter — проверяется обычными тестами.

HTML открывается в любом браузере: оттуда билет печатается или сохраняется в PDF («Печать» -> «Сохранить как PDF»).
Каждый билет строится по реальной записи из БД; код проверки — тот же, что и на кассе (ticket_print.ticket_code).
"""
import base64
import mimetypes
from html import escape

from . import movie_service, ticket_print
from .errors import ValidationError


def poster_data_uri(poster_path) -> str | None:
    """Постер, вшитый в страницу (data:-адрес), чтобы файл билета был самодостаточным. Нет постера -> None."""
    path = movie_service.poster_file(poster_path)
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def eticket_html(tickets: list[dict]) -> str:
    if not tickets:
        raise ValidationError("Нет билетов для печати.")
    cards = []
    for t in tickets:
        rows = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in ticket_print.ticket_lines(t))
        uri = poster_data_uri(t.get("poster_path"))
        poster = f'<img class="poster" src="{uri}" alt="">' if uri else ""
        status = "" if t["status"] == "sold" else '<div class="void">БИЛЕТ ВОЗВРАЩЁН — НЕДЕЙСТВИТЕЛЕН</div>'
        cards.append(
            f'<section class="ticket"><header><span class="logo">{ticket_print.CINEMA_NAME}</span>'
            f'<span class="num">Электронный билет № {t["id"]}</span></header>{status}'
            f'<div class="body">{poster}<table>{rows}</table></div>'
            f'<footer>Код проверки: <b>{escape(ticket_print.ticket_code(t))}</b> · предъявите код на входе</footer></section>')
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Электронный билет {ticket_print.CINEMA_NAME}</title>
<style>
body {{ font-family: "Segoe UI", Arial, sans-serif; background: #130a2b; margin: 0; padding: 24px; color: #1c1033; }}
.ticket {{ width: 640px; margin: 0 auto 24px; background: #fff; border: 3px solid #7c3aed; border-radius: 18px;
          padding: 20px 28px; page-break-after: always; }}
header {{ display: flex; justify-content: space-between; align-items: baseline; border-bottom: 2px dashed #c4a5f5;
         padding-bottom: 10px; margin-bottom: 12px; }}
.logo {{ font-size: 30px; font-weight: 700; letter-spacing: 7px; color: #7c3aed; }}
.num {{ font-size: 17px; font-weight: 600; }}
.body {{ display: flex; gap: 20px; align-items: flex-start; }}
.poster {{ width: 150px; border-radius: 10px; }}
table {{ flex: 1; border-collapse: collapse; }}
th {{ text-align: left; width: 40%; color: #6b5a8f; font-weight: 500; padding: 5px 0; }}
td {{ font-weight: 600; padding: 5px 0; }}
.void {{ background: #ffe3e3; color: #b00020; font-weight: 700; text-align: center; padding: 6px; border-radius: 8px; margin-bottom: 10px; }}
footer {{ margin-top: 14px; padding-top: 10px; border-top: 2px dashed #c4a5f5; font-size: 14px; color: #6b5a8f; }}
button {{ display: block; margin: 0 auto 20px; padding: 10px 28px; font-size: 16px; border: 0; border-radius: 20px;
         background: #7c3aed; color: #fff; cursor: pointer; }}
@media print {{ body {{ background: #fff; padding: 0; }} button {{ display: none; }} }}
</style></head><body>
<button onclick="window.print()">Печать / сохранить в PDF</button>
{''.join(cards)}
</body></html>"""


def save_eticket_html(path, tickets: list[dict]) -> None:
    html = eticket_html(tickets)
    try:
        with open(path, "w", encoding="utf-8") as file:
            file.write(html)
    except OSError as exc:
        raise ValidationError(f"Не удалось сохранить файл: {exc.strerror or exc}.") from exc
