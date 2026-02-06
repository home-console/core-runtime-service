"""
Lifecycle плагина — когда что делать.

Только документация. Без кода (кроме комментариев).
"""

# --- on_load ---
# - регистрация сервисов (runtime.service_registry)
# - регистрация capabilities (через metadata; Core читает после on_load)
# - регистрация operations handlers (runtime.operations.register_handler)
#
# --- on_start ---
# - запуск фоновых задач
# - подписки на события (runtime.event_bus.subscribe)
#
# --- on_stop ---
# - отмена фоновых задач
# - отписка от событий (если нужно явно)
#
# --- on_unload ---
# - очистка ресурсов
# - НЕ регистрировать ничего
#
# --- Явные ограничения ---
# - плагин НЕ регистрирует HTTP endpoints (это делает модуль/адаптер по HttpRegistry)
# - плагин НЕ трогает admin / inspector
# - плагин НЕ вызывает другие плагины напрямую (только через runtime.service_registry или capability)
# - плагин не управляет своим lifecycle (только реагирует на вызовы Core)
