# Capability: yandex:session_cookies

**ID:** `yandex:session_cookies`

Cookies сессии для Quasar API (iot.quasar.yandex.ru). Quasar не использует OAuth token.

**Операции контракта:**
- `get_cookies() -> dict | None` — словарь cookies (Session_id, yandexuid, ...)

**Провайдеры (текущие):** oauth_yandex (get_cookies), yandex_device_auth (session → storage).

**Consumers:** yandex_smart_home (через фасад oauth_provider).

Consumer знает capability только по ID (строка); контракт — для документации и тестов.
