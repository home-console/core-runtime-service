# ШАГ 4: Capability-контракты и фасад (без резолва)

**Дата:** 2026-02-02  
**Цель:** разложить зависимости так, чтобы они стали явными и слабыми; подготовить почву к будущему capability-слою.

---

## Сделано

### 1. Явные capability-контракты (без механизма резолва)

- **`plugins/oauth_yandex/capability.py`**  
  - Capability ID: `oauth:yandex`  
  - Операции: `get_access_token()`, `get_status()`, `get_cookies()`  
  - Описание: `typing.Protocol` + константа `CAPABILITY_OAUTH_YANDEX`

- **`docs/capabilities/yandex_session_cookies.md`**  
  - Capability ID: `yandex:session_cookies`  
  - Операции: `get_cookies()`  
  - Описание: документация

### 2. Роли provider / consumer в коде

- **oauth_yandex:** в докстринге класса и в константе указано: **implements capability** `oauth:yandex`; контракт — `plugins/oauth_yandex/capability.py`.
- **yandex_smart_home:** в докстринге модуля и класса указано: **requires capabilities** `oauth:yandex` и `yandex:session_cookies`; все вызовы — через фасад `oauth_provider`.

### 3. Минимальный фасад (не registry)

- **`plugins/yandex_smart_home/oauth_provider.py`**  
  - Единая точка доступа к capability `oauth:yandex` и `yandex:session_cookies`.  
  - Сейчас: тонкая обёртка над `service_registry.call("oauth_yandex.*")` и `yandex_device_auth.get_session` + storage для cookies.  
  - В коде `yandex_smart_home` **нет** разбросанных вызовов `oauth_yandex.*` или `yandex_device_auth.*` вне этого фасада.

### 4. Правило архитектуры

- В **docs/01-ARCHITECTURE.md** добавлена секция **«Capabilities и вызовы через ServiceRegistry»**:
  - что **можно** вызывать через ServiceRegistry (инфраструктура, модули);
  - что **нельзя** для consumer’а (жёсткие вызовы другого плагина по имени из многих мест);
  - что **рекомендуется** (требование capability, один фасад, provider помечен implements);
  - legacy/transitional;
  - таблица **capability → provider → consumers**.

---

## Карта capability → provider → consumers

| Capability ID            | Provider (текущий)        | Consumers         | Операции                           |
|--------------------------|---------------------------|-------------------|------------------------------------|
| `oauth:yandex`           | oauth_yandex              | yandex_smart_home | get_access_token, get_status, get_cookies |
| `yandex:session_cookies` | oauth_yandex, yandex_device_auth | yandex_smart_home | get_cookies (через фасад)          |

---

## Критерий успеха

- Отключение `oauth_yandex` приводит к **предсказуемому** падению (вызовы идут через фасад → вызов к отсутствующему сервису).
- В коде плагина **нет** разбросанных вызовов `oauth_yandex.*`.
- Ментальная модель зафиксирована: «плагин требует capability, а не плагин»; контракты и фасад это отражают.

---

## Запрещено (не делалось)

- Реализация CapabilityRegistry, DI, новый runtime API.
- Изменение ServiceRegistry, переписывание AdminModule.
- Нарушение обратной совместимости.

---

## Следующий шаг (ШАГ 5)

При необходимости — введение реального резолва capabilities (CapabilityRegistry и т.п.); замена внутри фасада станет локальной.
