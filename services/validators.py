"""Общие функции проверки введённых данных.

GUI передаёт сюда строки из полей ввода, поэтому числа принимаем и как int, и как str.
"""
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from database.errors import DBError

from .errors import ValidationError


def clean_text(value, field, max_len, required=True, collapse=True):
    """Обрезает пробелы по краям (collapse=True — ещё и схлопывает повторные пробелы).

    Пустое значение: ошибка, если required, иначе возвращается None.
    """
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"Поле «{field}» должно быть текстом.")
    value = " ".join(value.split()) if collapse else value.strip()
    if not value:
        if required:
            raise ValidationError(f"Поле «{field}» не должно быть пустым.")
        return None
    if len(value) > max_len:
        raise ValidationError(f"Поле «{field}»: не более {max_len} символов.")
    return value


def parse_int(value, field, min_value=None, max_value=None) -> int:
    """Приводит значение к int и проверяет диапазон. «1.5», «abc», True — ошибки."""
    if isinstance(value, bool):  # bool — подкласс int, но True как «количество» — это ошибка ввода
        raise ValidationError(f"Поле «{field}» должно быть целым числом.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        number = int(value.strip())
    else:
        raise ValidationError(f"Поле «{field}» должно быть целым числом.")

    too_small = min_value is not None and number < min_value
    too_big = max_value is not None and number > max_value
    if too_small or too_big:
        if min_value is not None and max_value is not None:
            raise ValidationError(f"Поле «{field}»: допустимы значения от {min_value} до {max_value}.")
        if min_value is not None:
            raise ValidationError(f"Поле «{field}»: значение не меньше {min_value}.")
        raise ValidationError(f"Поле «{field}»: значение не больше {max_value}.")
    return number


def db_error_to_validation(exc: DBError, unique_message="Такая запись уже существует.") -> ValidationError:
    """Превращает ошибку слоя БД в ошибку, понятную пользователю."""
    if getattr(exc, "kind", "") == "unique":
        return ValidationError(unique_message)
    return ValidationError(str(exc))


def parse_date(value, field="Дата") -> date:
    """Принимает ГГГГ-ММ-ДД или ДД.ММ.ГГГГ (или объект date/datetime)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    raise ValidationError(f"Поле «{field}»: введите существующую дату (ГГГГ-ММ-ДД или ДД.ММ.ГГГГ).")


def parse_time(value, field="Время") -> time:
    """Принимает ЧЧ:ММ (допустимо «9:05»)."""
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%H:%M").time()
        except ValueError:
            pass
    raise ValidationError(f"Поле «{field}»: введите время в формате ЧЧ:ММ.")


def parse_price(value, field="Цена", max_value=100_000) -> float:
    """Цена в рублях: «350», «350,50», 350.5. Округляется до копеек."""
    if isinstance(value, bool):
        raise ValidationError(f"Поле «{field}» должно быть числом.")
    try:
        if isinstance(value, (int, float)):
            number = Decimal(str(value))
        elif isinstance(value, str):
            number = Decimal(value.strip().replace(",", "."))
        else:
            raise InvalidOperation
    except InvalidOperation:
        raise ValidationError(f"Поле «{field}» должно быть числом.") from None
    if not number.is_finite():  # отсекаем NaN и бесконечность
        raise ValidationError(f"Поле «{field}» должно быть числом.")
    if number < 0 or number > max_value:
        raise ValidationError(f"Поле «{field}»: допустимы значения от 0 до {max_value}.")
    return round(float(number), 2)


def normalize_phone(value):
    """Приводит телефон к виду +79991234567. Пусто -> None.

    Понимает «8 (999) 123-45-67», «+7 999 123 45 67», «9991234567».
    Номера других стран принимаются только с «+» (10–15 цифр).
    """
    text = (value or "").strip() if isinstance(value, str) or value is None else str(value).strip()
    if not text:
        return None
    error = ValidationError("Телефон: введите номер, например +7 999 123-45-67.")
    if not re.fullmatch(r"\+?[\d\s\-()]+", text):
        raise error
    digits = re.sub(r"\D", "", text)
    if text.startswith("+"):
        if not 10 <= len(digits) <= 15:
            raise error
        return "+" + digits
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    raise error


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value):
    """Проверяет email и приводит к нижнему регистру. Пусто -> None."""
    text = (value or "").strip() if isinstance(value, str) or value is None else ""
    if not text:
        return None
    if len(text) > 100 or not _EMAIL_RE.match(text):
        raise ValidationError("Email: введите адрес вида name@example.com.")
    return text.lower()
