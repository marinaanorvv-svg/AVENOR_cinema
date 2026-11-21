"""Исключения слоя бизнес-логики. GUI показывает str(exc) пользователю."""


class ServiceError(Exception):
    """Базовая ошибка бизнес-логики."""


class ValidationError(ServiceError):
    """Некорректный ввод или нарушено бизнес-правило."""


class AuthenticationError(ServiceError):
    """Неверный логин/пароль или учётная запись заблокирована."""


class PermissionDenied(ServiceError):
    """У пользователя нет права на это действие."""
