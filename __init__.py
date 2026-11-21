"""Графический интерфейс (Tkinter).

Правило слоя: GUI вызывает ТОЛЬКО services/ — ни SQL, ни database/ напрямую.
Модули formatting, navigation, login_guard не импортируют tkinter,
поэтому их логика проверяется обычными тестами без дисплея.
"""
