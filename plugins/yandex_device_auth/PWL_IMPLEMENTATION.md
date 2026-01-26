# Yandex PWL Implementation

## 컨트롤 플레인

### device_session.py

**PWLLoginSession**
- Per-session `aiohttp.ClientSession` с `CookieJar`
- Хранит track_id, process_uuid, magic, state, cookies_dict
- `lock` для идемпотентного finalize

**CookieSessionStore**
- Сохранение/загрузка cookies через runtime.storage
- Никогда не возвращает cookies во фронтенд

### yandex_api_client.py

**YandexPWLClient**
- `pwl_init()`: POST /auth/add/addapp → extract track_id, process_uuid, magic
- `pwl_check()`: POST /auth/add/checktoken → check status (pending|approved|rejected|expired)
- `pwl_finalize()`: POST /auth/add/finalize + follow redirects → extract Session_id, yandexuid
- Tolerant parsing (JSON, HTML meta, redirects)

### auth_methods.py

**QRAuthMethod.start()**
- Calls `api_client.pwl_init()`
- Returns device_code, qr_url, verification_url, expires_in, interval

**QRAuthMethod.poll()**
- Calls `api_client.pwl_check(device_code)`
- Returns status: pending|approved|rejected|expired
- If approved, includes cookies from CookieJar

### device_auth_service.py

**YandexDeviceAuthService**
- `start_auth()`: Init PWL session, start polling loop
- `_poll_loop()`: Background polling, finalize on approved
- `get_status()`: Return current state
- `cancel()`: Stop polling, cleanup
- `force_approve()`: Dev-mode force approval with test cookies
- Cookie storage via runtime.storage

### plugin.py

**HTTP Endpoints**
- POST /yandex/auth/device/start → start_auth()
- GET /yandex/auth/device/status?device_id=... → get_status()
- POST /yandex/auth/device/cancel → cancel()
- GET /yandex/auth/device/session → get_account_session()
- POST /yandex/auth/device/approve → force_approve() [DEV ONLY]

## Flow

### INIT
```
POST /yandex/auth/device/start {method: "qr"}
↓
→ pwl_init() → https://passport.yandex.ru/auth/add/addapp
← track_id, process_uuid, magic, expires_in, interval
← QR URL: https://passport.yandex.ru/pwl-yandex/auth/add?track_id=...&process_uuid=...&magic=...
```

### POLL
```
GET /yandex/auth/device/status?device_id=dev_...
↓
→ pwl_check(device_code) → https://passport.yandex.ru/auth/add/checktoken
← status: pending|approved|rejected|expired
← if approved: Session_id, yandexuid from CookieJar
```

### FINALIZE
```
pwl_finalize(track_id, process_uuid, magic)
↓
→ POST /auth/add/finalize + allow_redirects=True
← Extract Session_id, yandexuid from CookieJar
← Save to runtime.storage under yandex/cookies
```

## Edge Cases

- **Idempotent finalize**: Use lock per device_id
- **Expired**: Timeout check in _poll_loop
- **Rejected**: Detect from status response
- **Failed**: Graceful error handling in polling
- **Rate-limit**: Respect interval from API

## DEV MODE

**force_approve endpoint** (DEBUG only):
```
POST /yandex/auth/device/approve
{
    device_id: "dev_...",
    cookies: {
        Session_id: "...",
        yandexuid: "..."
    }
}
```

Saves fake cookies to storage for testing.

## Storage

- **yandex/device_auth/session**: Account session metadata
- **yandex/cookies**: Extracted Session_id, yandexuid
- **yandex/pwl_cookies/{device_id}**: Per-session cookies (fallback)

## No Breaking Changes

- Existing endpoints compatible
- Device/Code/Email methods unified in PWL flow
- Frontend no changes required
- Runtime integration unchanged

## Compatibility

- Python 3.11+
- aiohttp with SSL=False (dev mode)
- No external OAuth/WebView deps
- Runtime event_bus, storage, service_registry integration
