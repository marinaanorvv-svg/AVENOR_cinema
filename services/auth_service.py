"""Аутентификация и управление учётными записями.

Пароли хранятся только как PBKDF2-хеш (hashlib, без внешних библиотек)
с уникальной солью на каждый пароль. Формат строки в БД:
    pbkdf2_sha256$<итерации>$<соль hex>$<хеш hex>
"""
import hashlib
import hmac
import re
import secrets

from database import crud
from database.connection import get_connection, transaction
from database.errors import DBError
from database.schema import init_db

from .errors import AuthenticationError, ValidationError
from .permissions import CurrentUser, Permission, Role

PBKDF2_ITERATIONS = 200_000
MIN_PASSWORD_LENGTH = 6
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,32}$")

# Данные первого запуска: после входа пароль нужно сменить.
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

# Демонстрационные учётные записи для защиты проекта: по одной на роль (логин, пароль).
DEMO_ACCOUNTS = {Role.ADMIN: (DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD),
                 Role.CASHIER: ("kassa", "kassa123"), Role.VIEWER: ("buyer", "buyer123")}
_DEMO_NAMES = {Role.CASHIER: "Анна Кассир", Role.VIEWER: "Пётр Покупатель"}


# ------------------------------------------------------------------ хеширование

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """True, если пароль совпадает с хешем. Битый формат хеша -> False, а не падение."""
    try:
        algo, iterations, salt_hex, hash_hex = stored_hash.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     bytes.fromhex(salt_hex), int(iterations))
        # compare_digest сравнивает за постоянное время (защита от timing-атак)
        return hmac.compare_digest(digest, bytes.fromhex(hash_hex))
    except (ValueError, AttributeError):
        return False


# Хеш-пустышка: если логина нет в БД, всё равно считаем PBKDF2, чтобы по времени
# ответа нельзя было отличить «нет такого пользователя» от «неверный пароль».
_DUMMY_HASH = hash_password("dummy-password")


# ------------------------------------------------------------------ валидация

def _clean_required(value, field_name: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValidationError(f"Поле «{field_name}» не должно быть пустым.")
    return value


def _validate_username(username) -> str:
    username = _clean_required(username, "Логин")
    if not _USERNAME_RE.match(username):
        raise ValidationError("Логин: 3–32 символа, только латинские буквы, цифры, «_» и «.».")
    return username


def _validate_password(password) -> str:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Пароль должен содержать не менее {MIN_PASSWORD_LENGTH} символов.")
    return password


def _validate_role(role) -> str:
    if role not in Role.ALL:
        raise ValidationError("Недопустимая роль. Допустимо: admin, cashier, viewer.")
    return role


def _db_error_to_validation(exc: DBError) -> ValidationError:
    if getattr(exc, "kind", "") == "unique":
        return ValidationError("Пользователь с таким логином уже существует.")
    return ValidationError(str(exc))


def _to_current_user(row) -> CurrentUser:
    return CurrentUser(id=row["id"], username=row["username"], full_name=row["full_name"],
                       role=row["role"], client_id=row["client_id"])


def _get_user_or_fail(conn, user_id):
    row = crud.get_user(conn, user_id)
    if row is None:
        raise ValidationError("Пользователь не найден.")
    return row


def _ensure_not_last_admin(conn, user_row) -> None:
    """Нельзя лишить систему последнего активного администратора."""
    if user_row["role"] == Role.ADMIN and user_row["is_active"]:
        others = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1 AND id != ?",
            (user_row["id"],)).fetchone()[0]
        if others == 0:
            raise ValidationError("Нельзя отключить или понизить последнего администратора.")


# ------------------------------------------------------------------ вход

def login(username: str, password: str, db_path=None) -> CurrentUser:
    """Проверяет логин/пароль и возвращает CurrentUser.

    Сообщение об ошибке одинаковое для «нет такого логина» и «неверный пароль» —
    чтобы нельзя было подбирать существующие логины.
    """
    username = (username or "").strip()
    if not username or not password:
        raise AuthenticationError("Введите логин и пароль.")

    conn = get_connection(db_path)
    try:
        row = crud.get_user_by_username(conn, username)
    finally:
        conn.close()

    stored_hash = row["password_hash"] if row else _DUMMY_HASH
    password_ok = verify_password(password, stored_hash)
    if row is None or not password_ok:
        raise AuthenticationError("Неверный логин или пароль.")
    if not row["is_active"]:  # про блокировку сообщаем только после верного пароля
        raise AuthenticationError("Учётная запись заблокирована. Обратитесь к администратору.")
    return _to_current_user(row)


# ------------------------------------------------------------------ первый запуск

def ensure_default_admin(db_path=None) -> bool:
    """Если в системе нет ни одного пользователя, создаёт admin/admin123.

    Возвращает True, если учётка была создана. Вызывается из main.py при старте.
    """
    init_db(db_path)
    with transaction(db_path) as conn:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return False
        crud.create_user(conn, DEFAULT_ADMIN_USERNAME, hash_password(DEFAULT_ADMIN_PASSWORD),
                         Role.ADMIN, "Администратор")
    return True


def ensure_demo_accounts(db_path=None) -> int:
    """Создаёт демо-кассира и демо-пользователя, если их ещё нет. Возвращает число созданных.

    Чтобы войти под любой из трёх ролей без ручной настройки. Перед реальным использованием
    отключите (DEMO_MODE в main.py) и смените пароли.
    """
    init_db(db_path)
    created = 0
    with transaction(db_path) as conn:
        for role in (Role.CASHIER, Role.VIEWER):
            username, password = DEMO_ACCOUNTS[role]
            if crud.get_user_by_username(conn, username) is not None:
                continue
            client_id = crud.create_client(conn, _DEMO_NAMES[role]) if role == Role.VIEWER else None
            crud.create_user(conn, username, hash_password(password), role, _DEMO_NAMES[role], client_id)
            created += 1
    return created


# ------------------------------------------------------------------ управление пользователями

def create_user_account(actor: CurrentUser, username, password, role, full_name,
                        client_id=None, db_path=None) -> int:
    """Создаёт учётную запись (только администратор). Возвращает id пользователя.

    Для роли viewer, если client_id не передан, автоматически создаётся запись
    в clients и связывается с пользователем — так «Покупатель» увидит свои билеты.
    """
    actor.require(Permission.MANAGE_USERS)
    username = _validate_username(username)
    _validate_password(password)
    _validate_role(role)
    full_name = _clean_required(full_name, "ФИО")
    password_hash = hash_password(password)
    try:
        with transaction(db_path) as conn:  # при ошибке откатится и созданный клиент
            if role == Role.VIEWER and client_id is None:
                client_id = crud.create_client(conn, full_name)
            return crud.create_user(conn, username, password_hash, role, full_name, client_id)
    except DBError as exc:
        raise _db_error_to_validation(exc) from exc


def list_user_accounts(actor: CurrentUser, db_path=None) -> list[dict]:
    """Список пользователей для экрана администратора (без хешей паролей)."""
    actor.require(Permission.MANAGE_USERS)
    conn = get_connection(db_path)
    try:
        users = []
        for row in crud.list_users(conn):
            item = dict(row)
            item.pop("password_hash", None)
            users.append(item)
        return users
    finally:
        conn.close()


def set_user_active(actor: CurrentUser, user_id: int, is_active: bool, db_path=None) -> None:
    """Блокировка / разблокировка учётной записи."""
    actor.require(Permission.MANAGE_USERS)
    try:
        with transaction(db_path) as conn:
            user = _get_user_or_fail(conn, user_id)
            if not is_active:
                if user_id == actor.id:
                    raise ValidationError("Нельзя заблокировать самого себя.")
                _ensure_not_last_admin(conn, user)
            crud.update_user(conn, user_id, is_active=int(bool(is_active)))
    except DBError as exc:
        raise _db_error_to_validation(exc) from exc


def set_user_role(actor: CurrentUser, user_id: int, new_role: str, db_path=None) -> None:
    """Назначение роли."""
    actor.require(Permission.MANAGE_USERS)
    _validate_role(new_role)
    try:
        with transaction(db_path) as conn:
            user = _get_user_or_fail(conn, user_id)
            if user_id == actor.id and new_role != user["role"]:
                raise ValidationError("Нельзя изменить собственную роль.")
            if new_role != Role.ADMIN:
                _ensure_not_last_admin(conn, user)
            crud.update_user(conn, user_id, role=new_role)
    except DBError as exc:
        raise _db_error_to_validation(exc) from exc


def reset_password(actor: CurrentUser, user_id: int, new_password: str, db_path=None) -> None:
    """Сброс пароля любому пользователю (только администратор)."""
    actor.require(Permission.MANAGE_USERS)
    _validate_password(new_password)
    new_hash = hash_password(new_password)
    try:
        with transaction(db_path) as conn:
            _get_user_or_fail(conn, user_id)
            crud.update_user(conn, user_id, password_hash=new_hash)
    except DBError as exc:
        raise _db_error_to_validation(exc) from exc


def change_own_password(actor: CurrentUser, old_password: str, new_password: str,
                        db_path=None) -> None:
    """Смена собственного пароля (доступна любой роли) с проверкой старого."""
    _validate_password(new_password)
    new_hash = hash_password(new_password)
    try:
        with transaction(db_path) as conn:
            row = _get_user_or_fail(conn, actor.id)
            if not verify_password(old_password or "", row["password_hash"]):
                raise AuthenticationError("Неверный текущий пароль.")
            crud.update_user(conn, actor.id, password_hash=new_hash)
    except DBError as exc:
        raise _db_error_to_validation(exc) from exc
