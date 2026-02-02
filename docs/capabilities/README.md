# Capability-контракты (документация)

Capability — это **обещание наличия поведения**, а не способ его вызова.

Контракты здесь — только для **документации и типизации**. Consumer знает capability по **ID (строка)** и не импортирует контракты. Вызовы идут через фасад и ServiceRegistry.

- Контракт провайдера (типизация): `plugins/<provider>/capability.py` (например `plugins/oauth_yandex/capability.py`).
- Описание capability: файлы в этой папке (например `yandex_session_cookies.md`).

**CapabilityRegistry** (core) — только метаданные: кто какой capability предоставляет и кто какой требует. Нет `call` / `resolve` / `invoke`. Диагностика: `plugin_manager.get_plugin_block_reason(plugin_name)` — причина, по которой плагин не стартовал (например `{"missing_capabilities": ["oauth:yandex"]}`).
