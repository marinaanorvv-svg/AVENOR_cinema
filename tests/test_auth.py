"""Проверка аутентификации и ролей. Запуск:  python -m unittest tests.test_auth -v"""
import tempfile
import unittest
from pathlib import Path

from database import crud
from database.connection import get_connection
from services import auth_service as auth
from services.errors import AuthenticationError, PermissionDenied, ValidationError
from services.permissions import Permission, Role


class AuthTests(unittest.TestCase):
    def setUp(self):
        # Файловая БД во временной папке: сервисы сами открывают соединения
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"
        auth.ensure_default_admin(self.db)
        self.admin = auth.login("admin", "admin123", self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def _make(self, username, role, password="secret1"):
        return auth.create_user_account(self.admin, username, password, role,
                                        f"Тест {username}", db_path=self.db)

    # --- хеши
    def test_hash_is_salted_and_verifiable(self):
        h1, h2 = auth.hash_password("qwerty1"), auth.hash_password("qwerty1")
        self.assertNotEqual(h1, h2)
        self.assertNotIn("qwerty1", h1)
        self.assertTrue(auth.verify_password("qwerty1", h1))
        self.assertFalse(auth.verify_password("qwerty2", h1))
        self.assertFalse(auth.verify_password("x", "битый-хеш"))

    def test_password_not_stored_in_plain_text(self):
        conn = get_connection(self.db)
        stored = crud.get_user_by_username(conn, "admin")["password_hash"]
        conn.close()
        self.assertNotEqual(stored, "admin123")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))

    def test_default_admin_created_only_once(self):
        self.assertFalse(auth.ensure_default_admin(self.db))

    def test_demo_accounts_for_every_role(self):
        self.assertEqual(auth.ensure_demo_accounts(self.db), 2)
        self.assertEqual(auth.ensure_demo_accounts(self.db), 0)               # повторно ничего не создаёт
        for role, (username, password) in auth.DEMO_ACCOUNTS.items():
            self.assertEqual(auth.login(username, password, self.db).role, role)
        self.assertIsNotNone(auth.login("buyer", "buyer123", self.db).client_id)   # у покупателя есть клиентская карточка

    # --- вход
    def test_login_ok(self):
        self.assertEqual(self.admin.role, Role.ADMIN)

    def test_login_wrong_password_and_unknown_user_same_message(self):
        with self.assertRaises(AuthenticationError) as a:
            auth.login("admin", "wrong", self.db)
        with self.assertRaises(AuthenticationError) as b:
            auth.login("nobody", "wrong", self.db)
        self.assertEqual(str(a.exception), str(b.exception))

    def test_login_empty_fields(self):
        with self.assertRaises(AuthenticationError):
            auth.login("", "", self.db)

    def test_blocked_user_cannot_login(self):
        uid = self._make("cashier1", Role.CASHIER)
        auth.set_user_active(self.admin, uid, False, self.db)
        with self.assertRaises(AuthenticationError):
            auth.login("cashier1", "secret1", self.db)
        auth.set_user_active(self.admin, uid, True, self.db)
        self.assertEqual(auth.login("cashier1", "secret1", self.db).role, Role.CASHIER)

    # --- права
    def test_permission_matrix(self):
        self._make("cash", Role.CASHIER)
        self._make("view", Role.VIEWER)
        cashier = auth.login("cash", "secret1", self.db)
        viewer = auth.login("view", "secret1", self.db)
        self.assertTrue(cashier.has_permission(Permission.SELL_TICKET))
        self.assertFalse(cashier.has_permission(Permission.MANAGE_USERS))
        self.assertFalse(cashier.has_permission(Permission.VIEW_REPORTS))
        self.assertTrue(viewer.has_permission(Permission.VIEW_OWN_TICKETS))
        self.assertFalse(viewer.has_permission(Permission.SELL_TICKET))
        self.assertTrue(self.admin.has_permission(Permission.VIEW_REPORTS))

    def test_non_admin_cannot_manage_users(self):
        self._make("cash", Role.CASHIER)
        cashier = auth.login("cash", "secret1", self.db)
        with self.assertRaises(PermissionDenied):
            auth.create_user_account(cashier, "evil", "secret1", Role.ADMIN, "Хакер", db_path=self.db)
        with self.assertRaises(PermissionDenied):
            auth.list_user_accounts(cashier, self.db)

    # --- создание пользователей
    def test_viewer_gets_linked_client(self):
        self._make("view", Role.VIEWER)
        viewer = auth.login("view", "secret1", self.db)
        self.assertIsNotNone(viewer.client_id)

    def test_duplicate_username_rejected(self):
        self._make("dup", Role.CASHIER)
        with self.assertRaises(ValidationError):
            self._make("dup", Role.CASHIER)

    def test_validation_errors(self):
        bad = [("ab", "secret1", Role.CASHIER),        # короткий логин
               ("good_name", "123", Role.CASHIER),      # короткий пароль
               ("good_name", "secret1", "superuser")]   # несуществующая роль
        for username, password, role in bad:
            with self.assertRaises(ValidationError):
                auth.create_user_account(self.admin, username, password, role, "ФИО", db_path=self.db)

    def test_failed_viewer_creation_leaves_no_orphan_client(self):
        self._make("view", Role.VIEWER)
        with self.assertRaises(ValidationError):
            self._make("view", Role.VIEWER)  # дубликат логина -> откат транзакции
        conn = get_connection(self.db)
        n = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        conn.close()
        self.assertEqual(n, 1)

    # --- защита администратора
    def test_cannot_block_self_or_last_admin(self):
        with self.assertRaises(ValidationError):
            auth.set_user_active(self.admin, self.admin.id, False, self.db)
        with self.assertRaises(ValidationError):
            auth.set_user_role(self.admin, self.admin.id, Role.CASHIER, self.db)

    def test_cannot_demote_last_admin_via_another_admin(self):
        second = self._make("admin2", Role.ADMIN)
        auth.set_user_role(self.admin, second, Role.CASHIER, self.db)  # можно: есть другой админ
        self._make("admin3", Role.ADMIN)
        admin2_as_cashier = auth.login("admin2", "secret1", self.db)
        with self.assertRaises(PermissionDenied):
            auth.set_user_role(admin2_as_cashier, self.admin.id, Role.VIEWER, self.db)

    # --- пароли
    def test_change_own_password(self):
        with self.assertRaises(AuthenticationError):
            auth.change_own_password(self.admin, "wrong", "newpass1", self.db)
        auth.change_own_password(self.admin, "admin123", "newpass1", self.db)
        with self.assertRaises(AuthenticationError):
            auth.login("admin", "admin123", self.db)
        auth.login("admin", "newpass1", self.db)

    def test_admin_resets_password(self):
        uid = self._make("cash", Role.CASHIER)
        auth.reset_password(self.admin, uid, "brandnew1", self.db)
        auth.login("cash", "brandnew1", self.db)

    def test_user_list_has_no_hashes(self):
        for u in auth.list_user_accounts(self.admin, self.db):
            self.assertNotIn("password_hash", u)


if __name__ == "__main__":
    unittest.main()
