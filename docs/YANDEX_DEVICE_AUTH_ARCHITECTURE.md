# Yandex Device/QR Authorization Plugin

**Плагин:** `yandex_device_auth`  
**Цель:** Server-side авторизация Яндекса через device/QR-flow без browser OAuth и WebView

---

## Проблема

OAuth плагин (`oauth_yandex`) работает через browser redirect и дает OAuth токены для **публичных API**.  
Однако:
- **OAuth токены НЕ работают с Quasar WebSocket** (внутренний API)
- Quasar требует **server-side session cookies** (`Session_id`, `yandexuid`, `sessionid2`)
- Browser OAuth **не дает доступа к server-side cookies** (они живут в браузере пользователя)
- Embedded WebView **сложен в реализации** и требует GUI-зависимости (PyQt6/WebEngine)

---

## Решение: Device/QR Authorization

Используем **device-style authorization flow**, как в:
- YandexStation (умные колонки)
- Google Device Flow (TV, IoT устройства)
- GitHub Device Flow (CLI-инструменты)

### Ключевые отличия от OAuth:

| Характеристика | Browser OAuth | Device/QR Auth |
|----------------|---------------|----------------|
| Где происходит логин | Browser пользователя | Мобильное приложение / веб |
| Что получает backend | OAuth token (публичный API) | Session cookies (internal API) |
| Требует WebView | Да (для cookies) | **Нет** |
| User flow | Redirect → callback | QR scan → polling |
| Подходит для | Web-приложения | IoT, CLI, backend |
| Работает с Quasar | ❌ Нет | ✅ Да |

---

## Архитектура плагина

```
plugins/yandex_device_auth/
├── plugin.py                   # BasePlugin, регистрация сервисов
├── device_auth_service.py      # YandexDeviceAuthService (entrypoint)
├── auth_methods.py             # AuthMethod (abstract), QRAuthMethod, OneTimeCodeAuthMethod, etc.
├── device_session.py           # YandexDeviceSession (состояние device-сессии)
├── account_session.py          # YandexAccountSession (cookies, quasar_ready)
├── yandex_api_client.py        # HTTP-клиент к внутренним API Яндекса
└── README.md
```

### Модули и роли:

#### 1. `YandexDeviceAuthService`
- **Единый entrypoint** для всех методов авторизации
- Выбор `AuthMethod` (QR, code, email, token)
- Управление lifecycle device-сессии
- Polling статуса подтверждения
- Сохранение cookies → `YandexAccountSession`

#### 2. `AuthMethod` (абстракция)
```python
class AuthMethod(ABC):
    """Абстрактный метод авторизации."""
    
    @abstractmethod
    async def start(self) -> Dict[str, Any]:
        """Инициирует сессию, возвращает данные для UI."""
        pass
    
    @abstractmethod
    async def poll(self, session: YandexDeviceSession) -> AuthResult:
        """Проверяет статус подтверждения."""
        pass
    
    @abstractmethod
    async def finalize(self, result: AuthResult) -> YandexAccountSession:
        """Завершает сессию, извлекает cookies."""
        pass
```

Реализации:
- **`QRAuthMethod`**: генерирует QR-код, poll'ит подтверждение
- **`OneTimeCodeAuthMethod`**: выдает 6-значный код, poll'ит
- **`EmailLinkAuthMethod`**: отправляет ссылку на email, poll'ит
- **`TokenAuthMethod`** (future): прямой обмен токена на cookies

#### 3. `YandexDeviceSession`
```python
@dataclass
class YandexDeviceSession:
    device_id: str              # Уникальный ID сессии
    method: str                 # "qr" | "code" | "email"
    state: str                  # "pending" | "approved" | "expired" | "rejected"
    device_code: str            # Device code от Яндекса
    user_code: Optional[str]    # Код для ввода (если method=code)
    qr_url: Optional[str]       # URL QR-кода (если method=qr)
    verification_url: str       # URL для подтверждения
    expires_at: float           # Timestamp истечения
    poll_interval: int          # Интервал polling (секунды)
    created_at: float
```

#### 4. `YandexAccountSession`
```python
@dataclass
class YandexAccountSession:
    cookies: Dict[str, str]     # Session_id, yandexuid, sessionid2
    quasar_ready: bool          # Готовность к Quasar WS
    linked_at: float            # Timestamp привязки
    device_info: Optional[Dict] # Информация об устройстве (optional)
```

#### 5. `YandexAPIClient`
- HTTP-клиент к внутренним API Яндекса
- Endpoints:
  - `POST /device/auth/start` — инициация device-сессии
  - `POST /device/auth/poll` — проверка статуса
  - `POST /device/auth/token` — обмен device_code → cookies
- Логирование через `request_logger`

---

## Device/QR Flow (детальная последовательность)

### Sequence Diagram

```
User        Admin UI       Backend (DeviceAuthService)    Yandex API       User Mobile App
 |             |                     |                         |                   |
 |  Click "Link Yandex"             |                         |                   |
 |------------>|                     |                         |                   |
 |             | POST /yandex/auth/device/start {"method":"qr"}                    |
 |             |-------------------->| start_auth()            |                   |
 |             |                     |------ POST /device/auth/start ------------>|
 |             |                     |<------ device_code, qr_url, interval ------|
 |             |                     | save YandexDeviceSession                    |
 |             |<--------------------| { state:"pending", qr_url, device_id }      |
 |             | Display QR code     |                         |                   |
 |             |                     |                         |                   |
 |             |                     |      Poll loop starts   |                   |
 |             |                     |                         |                   |
 | Scan QR with Yandex app          |                         |                   |
 |----------------------------------------------------------------------------->|
 |             |                     |                         |     Confirm auth   |
 |             |                     |                         |<-------------------|
 |             |                     |                         |                   |
 |             | GET /yandex/auth/device/status?device_id=...  |                   |
 |             |-------------------->| poll()                  |                   |
 |             |                     |------ POST /device/auth/poll -------------->|
 |             |                     |<------ state: approved, session_token -----|
 |             |                     | finalize()              |                   |
 |             |                     | extract cookies         |                   |
 |             |                     | save to storage         |                   |
 |             |                     | publish yandex.device_auth.linked event    |
 |             |<--------------------| { state:"approved", quasar_ready:true }     |
 |             | Show success        |                         |                   |
 |             |                     | Start Quasar WS         |                   |
```

### Шаги:

1. **Старт сессии** (`/yandex/auth/device/start`)
   - Backend → Yandex API: запрос device-сессии
   - Yandex возвращает: `device_code`, `qr_url`, `user_code`, `verification_url`, `interval`, `expires_in`
   - Backend создает `YandexDeviceSession`, сохраняет в memory/storage
   - Backend → UI: возвращает `qr_url` (или `user_code` для code-метода)

2. **Отображение QR** (UI)
   - UI показывает QR-код (через `<img src="{qr_url}">` или генерирует локально)
   - UI показывает инструкцию: "Отсканируйте QR в приложении Яндекс"

3. **Polling статуса** (`/yandex/auth/device/status`)
   - UI poll'ит каждые `interval` секунд (обычно 5-10 сек)
   - Backend → Yandex API: проверка статуса `device_code`
   - Возможные ответы:
     - `pending` — ожидает подтверждения
     - `approved` — подтверждено, получены cookies
     - `expired` — время истекло
     - `rejected` — пользователь отказал

4. **Финализация** (при `approved`)
   - Backend извлекает session cookies из ответа Yandex
   - Создает `YandexAccountSession` с cookies
   - Сохраняет в storage: `yandex/device_auth/session`
   - Также сохраняет в `yandex/cookies` для совместимости с Quasar
   - Публикует событие: `yandex.device_auth.linked`
   - Quasar WS автоматически стартует (если `use_real_api=true`)

5. **Обработка таймаута/отмены**
   - Если `expires_at` прошел → автоматически `expired`
   - Если пользователь нажал "Отмена" → вызов `/yandex/auth/device/cancel`
   - Backend удаляет `YandexDeviceSession` из памяти

---

## HTTP API Контракты

### POST `/yandex/auth/device/start`
**Описание:** Инициирует device-авторизацию  
**Body:**
```json
{
  "method": "qr" | "code" | "email",
  "options": {
    "email": "user@example.com"  // для method=email
  }
}
```
**Response (200):**
```json
{
  "device_id": "dev_abc123",
  "state": "pending",
  "method": "qr",
  "qr_url": "https://yandex.ru/auth/qr?token=...",
  "verification_url": "https://yandex.ru/auth/verify",
  "user_code": "123-456",  // только для method=code
  "expires_at": 1737734400.0,
  "poll_interval": 5
}
```

### GET `/yandex/auth/device/status?device_id=dev_abc123`
**Описание:** Получить статус device-сессии  
**Response (200):**
```json
{
  "device_id": "dev_abc123",
  "state": "pending" | "approved" | "expired" | "rejected",
  "quasar_ready": false,
  "expires_at": 1737734400.0
}
```
**Response (approved):**
```json
{
  "device_id": "dev_abc123",
  "state": "approved",
  "quasar_ready": true,
  "linked_at": 1737733800.0
}
```

### POST `/yandex/auth/device/cancel`
**Описание:** Отменить device-сессию  
**Body:**
```json
{
  "device_id": "dev_abc123"
}
```
**Response (200):**
```json
{
  "status": "cancelled"
}
```

### GET `/yandex/auth/device/session`
**Описание:** Получить текущий статус привязанного аккаунта  
**Response (200):**
```json
{
  "linked": true,
  "quasar_ready": true,
  "linked_at": 1737733800.0,
  "cookies_present": true
}
```
**Response (not linked):**
```json
{
  "linked": false,
  "quasar_ready": false
}
```

---

## Расширяемость

### Добавление нового метода авторизации

1. Создать класс, наследующий `AuthMethod`:
```python
class PasswordAuthMethod(AuthMethod):
    async def start(self) -> Dict[str, Any]:
        # Возвращаем форму для ввода логина/пароля
        return {"method": "password", "fields": ["username", "password"]}
    
    async def poll(self, session: YandexDeviceSession) -> AuthResult:
        # Для password нет polling — сразу проверяем
        pass
    
    async def finalize(self, result: AuthResult) -> YandexAccountSession:
        # Извлекаем cookies из ответа
        pass
```

2. Зарегистрировать в `YandexDeviceAuthService`:
```python
self.methods = {
    "qr": QRAuthMethod(self.runtime),
    "code": OneTimeCodeAuthMethod(self.runtime),
    "email": EmailLinkAuthMethod(self.runtime),
    "password": PasswordAuthMethod(self.runtime),  # Новый метод
}
```

3. UI автоматически получит новый метод через API

### Переиспользование общей логики

Базовый класс `AuthMethod` содержит:
- Общий polling loop с таймаутом
- Обработку ошибок и retry
- Логирование
- Интеграцию с `YandexDeviceSession`

Подклассы реализуют только специфичную логику:
- Формирование запроса к Yandex API
- Парсинг ответа
- Извлечение cookies

---

## Интеграция с существующим backend

### 1. Хранение данных

**Device-сессии** (временные, in-memory или Redis):
```
yandex_device_auth/sessions/{device_id} → YandexDeviceSession
```

**Account-сессия** (persistent, storage):
```
yandex/device_auth/session → YandexAccountSession
yandex/cookies → Dict[str, str]  # Для совместимости с Quasar
```

### 2. События

После успешной привязки:
```python
await runtime.event_bus.publish("yandex.device_auth.linked", {
    "method": "qr",
    "linked_at": time.time(),
    "quasar_ready": True,
})
```

Подписчики:
- `yandex_smart_home` плагин → стартует Quasar WS
- Admin UI → обновляет статус аккаунта

### 3. Взаимодействие с OAuth плагином

**Device Auth** и **OAuth** НЕ конфликтуют:
- OAuth: публичные API (token в `oauth_yandex/tokens`)
- Device Auth: internal API (cookies в `yandex/cookies`)

Оба могут быть активны одновременно:
- OAuth → для вызовов Yandex REST API (списки устройств, управление через REST)
- Device Auth → для Quasar WebSocket (realtime updates)

**Приоритет для Quasar:**
1. Проверяем `yandex/cookies` (Device Auth)
2. Если нет → проверяем `oauth_yandex.get_cookies()` (OAuth fallback)

### 4. Автозапуск Quasar WS

В `yandex_smart_home` плагине:
```python
async def on_start(self):
    # Подписываемся на событие Device Auth
    self.runtime.event_bus.subscribe(
        "yandex.device_auth.linked",
        self._on_device_linked
    )
    
    # Проверяем существующую сессию
    cookies = await self._get_cookies()
    if cookies and self._is_real_api_enabled():
        await self.quasar_ws.start()

async def _on_device_linked(self, event: Dict[str, Any]):
    # Автоматически стартуем Quasar при успешной привязке
    if event.get("quasar_ready"):
        await self.quasar_ws.start()
```

---

## Безопасность и UX

### Таймауты

- **Device-сессия:** 5-10 минут (задается Yandex API)
- **Polling interval:** 5 секунд (не чаще, чтобы не DDoS'ить Yandex)
- **Account-сессия:** бессрочная, пока cookies валидны

### Отмена пользователем

- Кнопка "Отмена" в UI → `POST /yandex/auth/device/cancel`
- Backend прекращает polling
- Удаляет `YandexDeviceSession` из памяти
- Yandex API автоматически аннулирует `device_code` по таймауту

### Повторный старт

- Можно вызвать `/yandex/auth/device/start` повторно
- Предыдущая сессия автоматически отменяется
- Генерируется новый `device_id` и `device_code`

### Логирование без утечек секретов

```python
await logger.log(
    level="info",
    message="Device auth started",
    plugin="yandex_device_auth",
    context={
        "device_id": device_id,
        "method": method,
        "expires_in": expires_in,
        # НЕ логируем: device_code, cookies
    }
)
```

### Отсутствие cookies на фронте

- Cookies **НЕ передаются** в HTTP-ответах
- UI видит только:
  - `qr_url` (публичный URL картинки)
  - `user_code` (одноразовый код)
  - `state` (статус сессии)
- Cookies хранятся **только на backend** в `storage`

---

## Почему это работает без WebView

### Проблема WebView-подхода:
- Требует GUI-зависимости (PyQt6, QtWebEngine)
- Сложная настройка cookie-store
- Проблемы с macOS sandbox
- Не подходит для headless-серверов

### Device/QR Flow:
1. **Backend инициирует сессию** у Yandex API
2. **Yandex генерирует device_code** (server-side)
3. **Пользователь подтверждает** на **своем устройстве** (мобильное приложение, веб)
4. **Yandex напрямую дает backend** session cookies (не через браузер)

**Ключевое отличие:**
- WebView: backend пытается "перехватить" браузерную сессию
- Device Flow: backend **создает свою собственную** server-side сессию

Аналогия:
- **OAuth (WebView):** "Дай мне доступ к твоему аккаунту через браузер"
- **Device Flow:** "Создай мне новую сессию как для IoT-устройства"

---

## Отличия от OAuth

| Характеристика | OAuth (`oauth_yandex`) | Device Auth (`yandex_device_auth`) |
|----------------|------------------------|-------------------------------------|
| **Назначение** | Публичные API | Internal API (Quasar) |
| **Протокол** | OAuth 2.0 (RFC 6749) | Device Authorization Grant (RFC 8628) + proprietary |
| **Что получаем** | `access_token`, `refresh_token` | Session cookies (`Session_id`, `yandexuid`) |
| **Где логин** | Browser redirect | Мобильное приложение / веб |
| **Backend участие** | Только callback | Polling статуса |
| **Cookies** | ❌ Не доступны | ✅ Доступны |
| **Quasar WS** | ❌ Не работает | ✅ Работает |
| **UI сложность** | Средняя (redirect) | Низкая (QR-код) |
| **Headless-сервер** | ❌ Проблемы | ✅ Подходит |

### Когда использовать что:

**OAuth (`oauth_yandex`):**
- Вызовы публичных REST API Яндекса
- Получение списка устройств через REST
- Управление аккаунтом через REST

**Device Auth (`yandex_device_auth`):**
- Quasar WebSocket (realtime updates)
- Internal API Яндекса
- IoT-устройства, CLI, headless-сервера

**Оба вместе:**
- Лучший DX: REST через OAuth, WebSocket через Device Auth
- Fallback: если OAuth дал cookies → использовать для Quasar

---

## Псевдокод backend-логики

### Старт сессии

```python
async def start_device_auth(method: str, options: Dict) -> Dict[str, Any]:
    # 1. Выбираем метод
    auth_method = self.methods[method]
    
    # 2. Инициируем сессию у Яндекса
    yandex_response = await auth_method.start()
    # -> {device_code, qr_url, verification_url, expires_in, interval}
    
    # 3. Создаем локальную сессию
    device_id = f"dev_{uuid4().hex[:12]}"
    session = YandexDeviceSession(
        device_id=device_id,
        method=method,
        state="pending",
        device_code=yandex_response["device_code"],
        qr_url=yandex_response.get("qr_url"),
        user_code=yandex_response.get("user_code"),
        verification_url=yandex_response["verification_url"],
        expires_at=time.time() + yandex_response["expires_in"],
        poll_interval=yandex_response.get("interval", 5),
        created_at=time.time(),
    )
    
    # 4. Сохраняем в памяти (or Redis)
    self.sessions[device_id] = session
    
    # 5. Запускаем фоновый polling
    asyncio.create_task(self._poll_loop(device_id))
    
    # 6. Возвращаем UI
    return {
        "device_id": device_id,
        "state": "pending",
        "method": method,
        "qr_url": session.qr_url,
        "user_code": session.user_code,
        "verification_url": session.verification_url,
        "expires_at": session.expires_at,
        "poll_interval": session.poll_interval,
    }
```

### Polling loop

```python
async def _poll_loop(self, device_id: str):
    session = self.sessions.get(device_id)
    if not session:
        return
    
    auth_method = self.methods[session.method]
    
    while time.time() < session.expires_at:
        if session.state != "pending":
            break
        
        # Poll Yandex API
        try:
            result = await auth_method.poll(session)
            
            if result.state == "approved":
                # Финализируем: извлекаем cookies
                account_session = await auth_method.finalize(result)
                
                # Сохраняем
                await self.runtime.storage.set(
                    "yandex", "device_auth/session", account_session
                )
                await self.runtime.storage.set(
                    "yandex", "cookies", account_session.cookies
                )
                
                # Публикуем событие
                await self.runtime.event_bus.publish(
                    "yandex.device_auth.linked",
                    {"quasar_ready": True, "method": session.method}
                )
                
                # Обновляем сессию
                session.state = "approved"
                break
            
            elif result.state in ("rejected", "expired"):
                session.state = result.state
                break
        
        except Exception as e:
            await logger.error(f"Polling error: {e}")
        
        await asyncio.sleep(session.poll_interval)
    
    # Таймаут
    if session.state == "pending":
        session.state = "expired"
    
    # Удаляем из памяти через 1 минуту
    await asyncio.sleep(60)
    self.sessions.pop(device_id, None)
```

### Проверка статуса

```python
async def get_device_status(device_id: str) -> Dict[str, Any]:
    session = self.sessions.get(device_id)
    
    if not session:
        # Проверяем storage: может уже завершено
        account = await self.runtime.storage.get("yandex", "device_auth/session")
        if account:
            return {
                "state": "approved",
                "quasar_ready": True,
                "linked_at": account.linked_at,
            }
        return {"error": "session_not_found"}
    
    return {
        "device_id": device_id,
        "state": session.state,
        "expires_at": session.expires_at,
        "quasar_ready": session.state == "approved",
    }
```

---

## Следующие шаги

1. ✅ Архитектура определена
2. 🔄 Реализовать каркас плагина (`plugin.py`, `device_auth_service.py`)
3. 🔄 Реализовать `QRAuthMethod` (базовая реализация)
4. 🔄 Добавить HTTP API endpoints
5. 🔄 Интегрировать с `yandex_smart_home` плагином
6. 🔄 Создать UI-компонент для отображения QR-кода
7. 🔄 Протестировать end-to-end flow

---

## Примечания по реализации

### Yandex API endpoints (reverse-engineered)

**Важно:** Официального публичного Device Flow API у Яндекса нет.  
Используются **внутренние endpoints**, найденные через reverse engineering:

Возможные варианты:
1. **YandexStation API** (используется умными колонками)
2. **Mobile App API** (используется мобильным приложением)
3. **PassportAPI** (внутренний auth API)

**Для production:** потребуется:
- Снифить трафик YandexStation или мобильного приложения
- Найти endpoints для device auth
- Извлечь формат запросов/ответов
- Реализовать в `YandexAPIClient`

**Для прототипа:** можно эмулировать через:
- Mock Yandex API (для тестов)
- Или использовать cookie-exchange через OAuth + browser automation (как временный workaround)

---

## Заключение

**Device/QR Authorization** — это **правильный** способ получить server-side session для Quasar:
- ✅ Работает без WebView
- ✅ Работает без browser extensions
- ✅ Подходит для headless-серверов
- ✅ Простой UX (QR-код)
- ✅ Расширяемая архитектура
- ✅ Безопасное хранение cookies на backend

Отдельный плагин `yandex_device_auth` не конфликтует с `oauth_yandex` и дополняет его:
- OAuth → публичные API
- Device Auth → internal API (Quasar)
