# Почему Яндекс — не OAuth Flow и как правильно подключить авторизацию

## Контекст

В системе действует архитектурное правило:

- **UI не знает провайдеров**
- **UI не знает OAuth**
- **UI работает только через Inspector (READ) и Operations (WRITE)**
- Авторизация и интеграции описываются как **state + actions**, а не как «экраны и URL»

Яндекс поддерживает два разных механизма авторизации, и **ни один из них не является классическим OAuth flow для UI**:

1. **Device Authorization Flow** (QR / код на yandex.ru/device)
2. **Service / Account binding** (через backend, cookies, x_token)

Из-за этого Яндекс **нельзя** подключать как обычный OAuth UI-flow (WebView, redirect, callback).  
UI не управляет OAuth, он только отражает состояние и запускает операции по кнопкам.

---

## Почему Яндекс НЕ является OAuth flow в UI

### 1. Нет user-driven redirect flow

| Классический OAuth | Яндекс (device flow) |
|--------------------|----------------------|
| UI открывает WebView | UI **не** открывает OAuth-страницу |
| Пользователь логинится в WebView | Backend генерирует user_code / QR |
| Redirect → callback → token | Пользователь сам идёт на yandex.ru/device или сканирует QR |
| UI получает code/token | UI только **показывает статус** и кнопки «Проверить» |

**Вывод:** UI не управляет OAuth, он только отражает состояние и вызывает операции.

### 2. Токены живут и обновляются в backend

- `refresh_token`, `access_token`, `expiration`, cookies/sessions — всё на backend.
- UI **не должен**: хранить токены, обновлять их, понимать refresh.
- Это нарушает инварианты безопасности и архитектуры.

### 3. Один провайдер — несколько механизмов

У Яндекса:

- OAuth device flow
- account binding (cookies, x_token)
- cookie session
- smart home permissions

Это не «один OAuth flow», а **набор состояний**, управляемых backend'ом.

---

## Правильная модель: Яндекс как Auth State Machine

**Базовый принцип:** Яндекс — это не OAuth flow, а **Auth Integration с состояниями и действиями**.

| UI | Backend (плагин) |
|----|------------------|
| Не знает OAuth | Управляет OAuth/device flow |
| Не знает Яндекс | Управляет токенами и сессией |
| Не знает URL | Пишет состояние в `runtime.state["auth_inspector.flows"]` |
| Читает **Inspector.auth_flows** | Inspector только читает state |
| Рисует карточки по state + actions | Регистрирует операции (`yandex_device_auth.start`, `.status`, `.unlink`) |
| Вызывает **Operations** по type из flow | Обрабатывает операции |

---

## Архитектурная модель (обязательная)

### Backend (плагин)

Плагин Яндекса (например `yandex_device_auth`):

- Управляет device flow (QR, код, cookies).
- Управляет токенами/сессией в storage.
- **Пишет** состояние в `runtime.state["auth_inspector.flows"]`:

```python
runtime.state["auth_inspector.flows"] = [
  {
    "id": "yandex-device",
    "state": "pending_code",  # или not_started, authorized
    "message": "Введите код на странице yandex.ru/device или отсканируйте QR. Затем нажмите «Проверить статус».",
    "actions": [
      {"type": "yandex_device_auth.start", "label": "Начать авторизацию", "params": {}},
      {"type": "yandex_device_auth.status", "label": "Проверить статус", "params": {}},
    ]
  }
]
```

Типы действий могут быть провайдер-специфичными (`yandex_device_auth.*`) или универсальными (`auth.device.start`, `auth.device.poll`) — UI не различает, только подставляет `type` из flow в POST /admin/v1/operations.

### Inspector (READ)

- **Не** вызывает сервисы.
- **Не** знает OAuth и Яндекс.
- Только: `return runtime.state.get("auth_inspector.flows", [])`.

### UI (Flutter / Web / Expo)

- Запрашивает **GET /admin/v1/inspector/auth** → получает `auth_flows[]`.
- Рендерит карточки: id, state, message, кнопки из `actions`.
- По нажатию кнопки: **POST /admin/v1/operations** с `{ "type": "<action.type>", "params": {} }`.

**Запрещено в UI:**

- OAuth WebView
- Redirect / callback URL
- Хранить access_token
- Отдельный «YandexLoginScreen» или ветвление `if (provider === 'yandex')`

---

## Полный lifecycle (как должно работать)

1. UI открывает Admin → Auth.
2. Inspector отдаёт: `state = not_started`, `action = yandex_device_auth.start`.
3. Пользователь нажимает «Начать авторизацию».
4. Backend: начинает device flow, обновляет state → `pending_code`, пишет в `auth_inspector.flows`.
5. UI обновляется по Inspector (перезапрос или pull).
6. Пользователь вводит код / сканирует QR вне приложения.
7. Пользователь нажимает «Проверить статус».
8. Backend: выполняет poll; либо `authorized`, либо `expired`.
9. Inspector снова отдаёт актуальное состояние.
10. UI просто отображает его.

---

## Что строго запрещено

- OAuth WebView во Flutter/Web.
- Redirect / callback URL в UI.
- Хранить access_token в UI.
- Делать «YandexLoginScreen» с прямыми вызовами `/yandex/auth/device/*`.
- Ветвление по провайдерам в UI (`if (provider === 'yandex')`).

---

## Почему это решение правильное

| Критерий | Результат |
|----------|-----------|
| UI независим от провайдера | ✅ |
| Можно добавить второй OAuth / другого провайдера | ✅ |
| Можно добавить non-OAuth (cookie, API key) | ✅ |
| Можно поменять Яндекс API без правок UI | ✅ |
| Безопасность: токены только в backend | ✅ |

---

## Реализация в коде

- **Плагин** `yandex_device_auth`: в `plugin.py` метод `_sync_auth_inspector_flows()` строит один flow с `id: "yandex-device"`, состояниями `not_started` / `pending_code` / `authorized` и actions `yandex_device_auth.start`, `yandex_device_auth.status`, `yandex_device_auth.cancel`, `yandex_device_auth.unlink`. Вызывается после каждой операции и в `on_load`.
- **Inspector**: `list_auth_flows(runtime)` в `modules/admin/services/introspection.py` возвращает `runtime.state.get("auth_inspector.flows", [])`.
- **Flutter** `AdminAuthScreen`: только `GET /admin/v1/inspector/auth` и `POST /admin/v1/operations` по type из actions — без имён провайдеров и URL.

---

## Краткая формулировка (для себя)

**Яндекс — это не OAuth UI-flow.**  
Это backend-managed auth integration с состояниями и действиями: UI только отображает состояние (Inspector) и запускает действия (Operations). Никакого WebView, redirect, хранения токенов и ветвления по провайдерам в UI.
