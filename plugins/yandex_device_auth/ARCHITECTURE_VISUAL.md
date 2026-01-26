# 🎯 PWL Implementation - Visual Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     YandexDeviceAuthService                      │
│                   (device_auth_service.py)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  start_auth()              check_qr_status()    unlink_account() │
│      │                           │                      │        │
│      ▼                           ▼                      ▼        │
│  ┌─────────────┐          ┌──────────────┐      ┌────────────┐  │
│  │  YandexPass │          │  YandexPass  │      │  Storage   │  │
│  │  portClient │◄─────────│  portClient  │      │  (account  │  │
│  │             │          │              │      │   session) │  │
│  │get_qr_url() │          │check_qr_stat │      └────────────┘  │
│  │             │          │us()          │                      │
│  └─────────────┘          └──────────────┘                      │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                        ▲
                        │
                        ▼
        ┌───────────────────────────────────┐
        │   aiohttp.ClientSession           │
        │   (persistent cookie jar)         │
        │                                   │
        │ └─ auth_session: DeviceAuthSession│
        │    ├─ client_session (HTTP)       │
        │    ├─ device_id                   │
        │    ├─ pwl_params                  │
        │    └─ cookie_jar (auto-filled)    │
        └───────────────────────────────────┘
```

---

## Request/Response Flow

### 1️⃣ Start Auth - Request QR

```
USER BROWSER
    │
    ├─► POST /yandex/auth/start
    │
    └◄─ { qr_url: "https://...", track_id: "device_id" }
```

### 2️⃣ Backend: Get QR URL

```
YandexPassportClient.get_qr_url()
    │
    ├─ Step 1: POST /auth/device/start
    │  Endpoint: https://passport.yandex.ru/auth/device/start
    │  Params:   device_name, device_type, retpath
    │  Response: { status: "ok", device_id: "xxx" }
    │
    ├─ Step 2: GET /pwl-yandex/auth/add
    │  Endpoint: https://passport.yandex.ru/pwl-yandex/auth/add
    │  Params:   retpath
    │  Response: HTML (verify no noPWL:true)
    │
    └─ Step 3: Return QR URL
       URL: https://passport.yandex.ru/pwl-yandex/auth/add?retpath=...
```

### 3️⃣ User: Scan & Confirm

```
┌──────────────────────────────┐
│  YANDEX APP (on user phone)  │
├──────────────────────────────┤
│                              │
│ 1. User scans QR code       │
│    ↓                        │
│ 2. QR decoded: retpath URL  │
│    ↓                        │
│ 3. Open: /pwl-yandex/...   │
│    ↓                        │
│ 4. Auto-confirm auth        │
│    ↓                        │
│ 5. Set cookies in request   │
│    ↓                        │
│ 6. Redirect to retpath      │
│    ↓                        │
│ [SUCCESS - User authorized] │
│                              │
└──────────────────────────────┘
          │
          │ (Cookies set by Yandex)
          ▼
    ┌──────────────────────────┐
    │ Backend Session Cookie   │
    │ Jar (aiohttp)            │
    │ ├─ Session_id            │
    │ ├─ yandexuid             │
    │ └─ sessionid2             │
    └──────────────────────────┘
```

### 4️⃣ Check Status - Poll for Confirmation

```
USER BROWSER (poll every 2 sec)
    │
    ├─► GET /yandex/auth/status
    │
    └◄─ { status: "pending" }  (if not confirmed yet)

    (User confirms in app...)

    ├─► GET /yandex/auth/status
    │
    └◄─ { status: "approved", x_token: "..." }
```

### 5️⃣ Backend: Check QR Status

```
YandexPassportClient.check_qr_status()
    │
    ├─ Check session.cookie_jar
    │  └─ Look for Session_id, yandexuid, etc.
    │
    ├─ If cookies exist:
    │  ├─ POST /mobileproxy.../token_by_sessionid
    │  │  └─ Exchange cookies for x_token
    │  │
    │  ├─ GET /mobileproxy.../account/short_info
    │  │  └─ Get account details (login, uid, etc.)
    │  │
    │  └─ Return { x_token, display_login, uid }
    │
    └─ If no cookies yet:
       └─ Return None (not confirmed)
```

---

## Data Structures

### DeviceAuthSession (Persistent)

```python
class DeviceAuthSession:
    client_session: aiohttp.ClientSession  # HTTP client with cookie jar
    device_id: str = None                 # From bootstrap
    pwl_params: Dict[str, str] = {        # PWL flow params
        "device_id": "...",
        "retpath": "https://..."
    }
    created_at: float = time.time()       # For timeout checking
```

### Account Session (Stored)

```python
{
    "x_token": "access_token_from_yandex",
    "display_login": "user@yandex.ru",
    "uid": "123456789",
    "linked_at": 1234567890.0,
    "method": "qr"
}
```

---

## Error Handling Decision Tree

```
┌─ start_auth() ─────────────────────────────────────┐
│                                                     │
│  get_qr_url(auth_session)                          │
│  │                                                 │
│  ├─ Bootstrap device ────────────────┐            │
│  │ │                                 │            │
│  │ └─► HTTP Error? ─────────────┐   │            │
│  │     │                         │   │            │
│  │     ├─► YES ──► Return None ◄┤   │            │
│  │     │           (Log error)  │   │            │
│  │     └─► NO ──┬───────────────┘   │            │
│  │             │                     │            │
│  │     ├─ Get device_id              │            │
│  │     │                             │            │
│  │     └─ Check response structure   │            │
│  │        │                          │            │
│  │        ├─► status != "ok" ───┐   │            │
│  │        │                     │   │            │
│  │        │ Return None ◄──────┤   │            │
│  │        │ (Log error)         │   │            │
│  │        │                     │   │            │
│  │        └─► status == "ok" ──┤   │            │
│  │             │                │   │            │
│  │             ├─ no device_id ─┘   │            │
│  │             │   Return None      │            │
│  │             │                     │            │
│  │             └─ has device_id ─┐  │            │
│  │                                │  │            │
│  │         Store device_id ◄─────┤  │            │
│  │         Continue...             │  │            │
│  │                                 │  │            │
│  ├─ Get PWL page ────────────────┐ │  │            │
│  │ │                             │ │  │            │
│  │ └─► HTTP Error? ─────┐       │ │  │            │
│  │     │                 │       │ │  │            │
│  │     ├─► YES ──────────┤───┐   │ │  │            │
│  │     │                 │   │   │ │  │            │
│  │     └─► NO ──┬────────┘   │   │ │  │            │
│  │             │             │   │ │  │            │
│  │     Check noPWL flag      │   │ │  │            │
│  │     │                     │   │ │  │            │
│  │     ├─► noPWL:true ───┐   │   │ │  │            │
│  │     │                 │   │   │ │  │            │
│  │     │ Return None ◄───┤───┴───┘ │  │            │
│  │     │ (Log: Bootstrap   │       │  │            │
│  │     │  failed)          │       │  │            │
│  │     │                   │       │  │            │
│  │     └─► noPWL:false ───┤       │  │            │
│  │         Continue...      │       │  │            │
│  │                          │       │  │            │
│  └─ Build QR URL ──────────┤       │  │            │
│    │                        │       │  │            │
│    └─► SUCCESS ◄───────────┴───────┴──┤            │
│        Return QR URL & device_id      │            │
│                                       │            │
└───────────────────────────────────────┘            │
                                                      │
└──────────────────────────────────────────────────────┘
```

---

## Bootstrap Endpoint Comparison

### ✅ CORRECT (Current)
```
POST https://passport.yandex.ru/auth/device/start
```
- Returns device_id
- Sets proper session state
- Enables PWL (noPWL:false)

### ❌ WRONG (Previous)
```
POST https://passport.yandex.ru/registration-validations/auth/device/start
```
- Might not set proper state
- PWL disabled (noPWL:true)
- Not recommended by Yandex

---

## Session Lifecycle

```
CREATE                           DESTROY
┌────────────┐                  ┌────────┐
│ start_auth │──────────────────│ cleanup│
└───────┬────┘                  └────────┘
        │                             ▲
        │                             │
        ▼                             │
┌──────────────────────────────────────────┐
│   DeviceAuthSession (persistent)          │
│                                           │
│  Created: When start_auth() called       │
│  Timeout: 10 minutes (600 sec)           │
│  Destroyed: On cleanup() or expiry       │
│                                           │
│  ├─ aiohttp.ClientSession                │
│  │  └─ Cookie jar (auto-populated)       │
│  │     ├─ Empty initially                │
│  │     ├─ Filled when user confirms      │
│  │     └─ Used to get x_token            │
│  │                                        │
│  ├─ device_id (from bootstrap)           │
│  │  └─ Used in logging & tracking        │
│  │                                        │
│  └─ pwl_params (QR flow params)          │
│     ├─ device_id                         │
│     └─ retpath                           │
│                                           │
└──────────────────────────────────────────┘
        │
        │ (user confirms QR)
        ▼
┌──────────────────────────────────────────┐
│   Cookies in Session Jar                  │
│   (auto-added by aiohttp)                 │
│                                           │
│  ├─ Session_id (main session cookie)     │
│  ├─ yandexuid (user identifier)          │
│  └─ sessionid2 (backup)                  │
│                                           │
└──────────────────────────────────────────┘
        │
        │ (check_qr_status called)
        ▼
┌──────────────────────────────────────────┐
│   x_token Extracted                       │
│                                           │
│  ├─ Cookies → POST token_by_sessionid    │
│  ├─ Get x_token (OAuth access token)     │
│  ├─ Validate with short_info endpoint    │
│  └─ Return to user                       │
│                                           │
└──────────────────────────────────────────┘
        │
        │ (successful auth)
        ▼
┌──────────────────────────────────────────┐
│   Account Saved                           │
│                                           │
│  ├─ Store x_token in runtime.storage     │
│  ├─ Store display_login & uid            │
│  └─ Mark quasar_ready: true              │
│                                           │
└──────────────────────────────────────────┘
        │
        │ (cleanup or expiry)
        ▼
┌────────────┐
│ Session    │
│ destroyed  │
└────────────┘
```

---

## Status: Ready for Testing ✅

All architecture validated and implemented!
