# Yandex Device/QR Authorization Plugin

## Описание

Server-side авторизация Яндекса через **device/QR-flow** без browser OAuth и WebView.

**Назначение:**
- Получение session cookies (`Session_id`, `yandexuid`) для Quasar WebSocket
- Альтернатива OAuth для internal API Яндекса
- Подходит для headless-серверов, IoT-устройств, CLI

**Отличия от OAuth:**
- OAuth → публичные API, browser redirect, OAuth tokens
- Device Auth → internal API, QR/code, session cookies

---

## Архитектура

### Модули

```
plugins/yandex_device_auth/
├── plugin.py                   # BasePlugin, регистрация сервисов
├── device_auth_service.py      # YandexDeviceAuthService (entrypoint)
├── auth_methods.py             # AuthMethod (abstract), QRAuthMethod, OneTimeCodeAuthMethod
├── device_session.py           # YandexDeviceSession, YandexAccountSession, AuthResult
├── yandex_api_client.py        # HTTP-клиент к Yandex API
└── README.md
```

### Компоненты

- **YandexDeviceAuthService**: единый entrypoint, управление lifecycle сессий, polling
- **AuthMethod**: абстракция методов авторизации (QR, code, email)
- **YandexDeviceSession**: временное состояние device-сессии
- **YandexAccountSession**: persistent состояние привязанного аккаунта
- **YandexAPIClient**: HTTP-клиент к internal Yandex API (reverse-engineered)

---

## Методы авторизации

### 1. QR-код (рекомендуется)
- Backend генерирует QR-код
- Пользователь сканирует в приложении Яндекс
- Backend poll'ит статус подтверждения
- UX: наиболее простой для пользователя

### 2. Одноразовый код (6 цифр)
- Backend генерирует код типа `123-456`
- Пользователь вводит на yandex.ru/auth/verify
- Backend poll'ит статус

### 3. Email-ссылка
- Пользователь указывает email
- Backend отправляет ссылку через Yandex API
- Пользователь кликает в письме
- Backend poll'ит статус

---

## HTTP API

### POST `/yandex/auth/device/start`
**Описание:** Инициировать device-авторизацию

**Request:**
```json
{
  "method": "qr",
  "options": {}
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
  "expires_at": 1737734400.0,
  "poll_interval": 5
}
```

### GET `/yandex/auth/device/status?device_id=dev_abc123`
**Описание:** Получить статус device-сессии

**Response (200, pending):**
```json
{
  "device_id": "dev_abc123",
  "state": "pending",
  "quasar_ready": false,
  "expires_at": 1737734400.0
}
```

**Response (200, approved):**
```json
{
  "device_id": "dev_abc123",
  "state": "approved",
  "quasar_ready": true,
  "linked_at": 1737733800.0
}
```

### POST `/yandex/auth/device/cancel`
**Request:**
```json
{
  "device_id": "dev_abc123"
}
```

**Response:**
```json
{
  "status": "cancelled"
}
```

### GET `/yandex/auth/device/session`
**Описание:** Статус привязанного аккаунта

**Response (linked):**
```json
{
  "linked": true,
  "quasar_ready": true,
  "linked_at": 1737733800.0,
  "method": "qr",
  "cookies_present": true
}
```

---

## События

### `yandex.device_auth.linked`
Публикуется при успешной привязке аккаунта.

**Payload:**
```json
{
  "method": "qr",
  "linked_at": 1737733800.0,
  "quasar_ready": true
}
```

**Подписчики:**
- `yandex_smart_home` плагин → автоматически стартует Quasar WS

---

## Storage

### `yandex/device_auth/session`
Привязанный аккаунт (persistent):
```json
{
  "cookies": {"Session_id": "...", "yandexuid": "..."},
  "quasar_ready": true,
  "linked_at": 1737733800.0,
  "method": "qr"
}
```

### `yandex/cookies`
Cookies для совместимости с Quasar:
```json
{
  "Session_id": "...",
  "yandexuid": "...",
  "sessionid2": "..."
}
```

---

## Workflow (QR-метод)

1. **Frontend:** Пользователь нажимает "Войти с Яндекс"
2. **Frontend → Backend:** `POST /yandex/auth/device/start {"method":"qr"}`
3. **Backend:** Запрашивает device-сессию у Yandex API
4. **Backend → Frontend:** Возвращает `qr_url`, `device_id`, `poll_interval`
5. **Frontend:** Отображает QR-код (`<img src="{qr_url}">`)
6. **Frontend:** Начинает polling `GET /yandex/auth/device/status?device_id=...` каждые 5 сек
7. **Пользователь:** Сканирует QR в приложении Яндекс → подтверждает
8. **Backend:** Получает подтверждение от Yandex → извлекает cookies → сохраняет в storage → публикует `yandex.device_auth.linked`
9. **Backend:** `yandex_smart_home` плагин автоматически стартует Quasar WS
10. **Frontend:** Получает `state:"approved"` в polling → показывает "Успешно привязано"

---

## Интеграция с Quasar

### Автозапуск Quasar WS

В `yandex_smart_home/plugin.py`:

```python
async def on_start(self):
    # Подписываемся на событие
    self.runtime.event_bus.subscribe(
        "yandex.device_auth.linked",
        self._on_device_linked
    )
    
    # Проверяем существующую сессию
    cookies = await self._get_cookies()
    if cookies and self._is_real_api_enabled():
        await self.quasar_ws.start()

async def _on_device_linked(self, event):
    if event.get("quasar_ready"):
        await self.quasar_ws.start()
```

### Приоритет cookies

В `yandex_quasar_ws.py`:

```python
async def _load_cookies(self):
    # 1. Проверяем device_auth
    try:
        session = await self.runtime.storage.get("yandex", "device_auth/session")
        if session and session.get("cookies"):
            return session["cookies"]
    except: pass
    
    # 2. Fallback на oauth_yandex
    try:
        if await self.runtime.service_registry.has_service("oauth_yandex.get_cookies"):
            cookies = await self.runtime.service_registry.call("oauth_yandex.get_cookies")
            if cookies:
                return cookies
    except: pass
    
    return None
```

---

## Совместимость с OAuth

**Device Auth** и **OAuth** НЕ конфликтуют и могут работать одновременно:

- **OAuth (`oauth_yandex`)**: публичные REST API, OAuth tokens
- **Device Auth (`yandex_device_auth`)**: internal API (Quasar), session cookies

**Рекомендуемая настройка:**
- OAuth → для вызовов Yandex REST API (получение списка устройств)
- Device Auth → для Quasar WebSocket (realtime updates)

---

## Безопасность

### Что НЕ передается на frontend:
- ❌ `device_code` (internal, используется только для polling)
- ❌ Cookies (`Session_id`, `yandexuid`)

### Что передается на frontend:
- ✅ `qr_url` (публичный URL картинки)
- ✅ `user_code` (одноразовый код, безопасен)
- ✅ `device_id` (ID сессии, безопасен)
- ✅ `state` (статус сессии)

### Таймауты:
- Device-сессия: 5-10 минут (задается Yandex API)
- Polling interval: 5 секунд
- Account-сессия: бессрочная, пока cookies валидны

---

## Расширяемость

### Добавление нового метода авторизации

1. Создать класс в `auth_methods.py`:
```python
class PasswordAuthMethod(AuthMethod):
    async def start(self, options):
        # Логика инициации
        pass
    
    async def poll(self, session):
        # Логика проверки
        pass
```

2. Зарегистрировать в `device_auth_service.py`:
```python
self.methods["password"] = PasswordAuthMethod(runtime, api_client)
```

3. UI автоматически получит новый метод через API

---

## Ограничения текущей реализации

### Заглушки (TODO):

1. **Yandex API endpoints** — используются mock-ответы
   - Требуется reverse-engineering YandexStation / mobile app
   - Найти real endpoints и форматы запросов/ответов

2. **Polling** — всегда возвращает `state:"pending"`
   - Требуется реализация real HTTP calls к Yandex API

3. **Cookie extraction** — не реализован
   - Требуется парсинг ответа Yandex API для извлечения cookies

### Следующие шаги:

1. ✅ Архитектура и каркас плагина
2. 🔄 Reverse-engineering Yandex API (снифинг YandexStation)
3. 🔄 Реализация real API calls в `yandex_api_client.py`
4. 🔄 Реализация cookie extraction в `auth_methods.py`
5. 🔄 End-to-end тестирование с real Yandex API
6. 🔄 UI-компонент для отображения QR-кода

---

## UI Пример (React)

```tsx
function YandexDeviceAuth() {
  const [session, setSession] = useState(null);
  const [status, setStatus] = useState('idle');

  const startAuth = async () => {
    const res = await fetch('/yandex/auth/device/start', {
      method: 'POST',
      body: JSON.stringify({ method: 'qr' }),
    });
    const data = await res.json();
    setSession(data);
    setStatus('pending');
    pollStatus(data.device_id);
  };

  const pollStatus = async (deviceId) => {
    const interval = setInterval(async () => {
      const res = await fetch(`/yandex/auth/device/status?device_id=${deviceId}`);
      const data = await res.json();
      
      if (data.state === 'approved') {
        setStatus('approved');
        clearInterval(interval);
      } else if (data.state in ['expired', 'rejected']) {
        setStatus(data.state);
        clearInterval(interval);
      }
    }, 5000);
  };

  return (
    <div>
      {status === 'idle' && (
        <button onClick={startAuth}>Войти с Яндекс</button>
      )}
      {status === 'pending' && session && (
        <div>
          <img src={session.qr_url} alt="QR Code" />
          <p>Отсканируйте QR-код в приложении Яндекс</p>
        </div>
      )}
      {status === 'approved' && (
        <div>✅ Аккаунт успешно привязан!</div>
      )}
    </div>
  );
}
```

---

## Заключение

**Yandex Device Auth** — это **правильный** способ получить server-side session для Quasar:

- ✅ Работает без WebView
- ✅ Работает без browser extensions
- ✅ Подходит для headless-серверов
- ✅ Простой UX (QR-код или одноразовый код)
- ✅ Расширяемая архитектура
- ✅ Безопасное хранение cookies на backend
- ✅ Не конфликтует с OAuth

Плагин готов к интеграции после реализации real Yandex API calls (требуется reverse-engineering).
