# Yandex Device Auth: Sequence Diagrams

## QR-Login Flow (детальная последовательность)

```
┌──────────┐     ┌──────────┐     ┌─────────────────────┐     ┌────────────┐     ┌──────────────┐
│  User    │     │ Admin UI │     │ Backend             │     │ Yandex API │     │ User Mobile  │
│          │     │          │     │ (DeviceAuthService) │     │            │     │ App          │
└──────────┘     └──────────┘     └─────────────────────┘     └────────────┘     └──────────────┘
     │                 │                      │                       │                    │
     │  Click "Link    │                      │                       │                    │
     │  Yandex"        │                      │                       │                    │
     ├────────────────>│                      │                       │                    │
     │                 │                      │                       │                    │
     │                 │ POST /yandex/auth/device/start               │                    │
     │                 │      {"method": "qr"}│                       │                    │
     │                 ├─────────────────────>│                       │                    │
     │                 │                      │                       │                    │
     │                 │                      │ start_auth()          │                    │
     │                 │                      │ ├──────────────┐      │                    │
     │                 │                      │ │ Generate     │      │                    │
     │                 │                      │ │ device_id    │      │                    │
     │                 │                      │ └──────────────┘      │                    │
     │                 │                      │                       │                    │
     │                 │                      │ POST /device/auth/code│                    │
     │                 │                      ├──────────────────────>│                    │
     │                 │                      │                       │                    │
     │                 │                      │ {device_code, qr_url, │                    │
     │                 │                      │  verification_url,     │                    │
     │                 │                      │  expires_in, interval} │                    │
     │                 │                      │<──────────────────────┤                    │
     │                 │                      │                       │                    │
     │                 │                      │ Save YandexDeviceSession                   │
     │                 │                      │ ├──────────────┐      │                    │
     │                 │                      │ │ state:pending│      │                    │
     │                 │                      │ └──────────────┘      │                    │
     │                 │                      │                       │                    │
     │                 │                      │ Start polling task    │                    │
     │                 │                      │ (async background)    │                    │
     │                 │                      │ ╔═════════════╗       │                    │
     │                 │                      │ ║ Polling     ║       │                    │
     │                 │                      │ ║ Loop        ║       │                    │
     │                 │                      │ ╚═════════════╝       │                    │
     │                 │                      │      │                │                    │
     │                 │ {device_id, state,   │      │                │                    │
     │                 │  qr_url, expires_at} │      │                │                    │
     │                 │<─────────────────────┤      │                │                    │
     │                 │                      │      │                │                    │
     │                 │ Display QR code      │      │                │                    │
     │<────────────────┤ <img src=qr_url>     │      │                │                    │
     │                 │                      │      │                │                    │
     │                 │ Start polling:       │      │                │                    │
     │                 │ GET /status?device_id│      │                │                    │
     │                 │ every 5 sec          │      │                │                    │
     │                 │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ >│      │                │                    │
     │                 │                      │      │                │                    │
     │  Scan QR with   │                      │      │                │                    │
     │  Yandex app     │                      │      │                │                    │
     ├─────────────────┼──────────────────────┼──────┼────────────────┼───────────────────>│
     │                 │                      │      │                │                    │
     │                 │                      │      │                │  User confirms     │
     │                 │                      │      │                │  authorization     │
     │                 │                      │      │                │<───────────────────┤
     │                 │                      │      │                │                    │
     │                 │                      │      │                │  Notify Yandex     │
     │                 │                      │      │                │<───────────────────┤
     │                 │                      │      │                │                    │
     │                 │                      │      │ [Polling Loop] │                    │
     │                 │                      │      │ POST /device/  │                    │
     │                 │                      │      │ auth/token     │                    │
     │                 │                      │      ├───────────────>│                    │
     │                 │                      │      │                │                    │
     │                 │                      │      │ {state:approved│                    │
     │                 │                      │      │  cookies: {...}}│                   │
     │                 │                      │      │<───────────────┤                    │
     │                 │                      │      │                │                    │
     │                 │                      │ finalize()            │                    │
     │                 │                      │ ├──────────────┐      │                    │
     │                 │                      │ │ Extract      │      │                    │
     │                 │                      │ │ cookies      │      │                    │
     │                 │                      │ └──────────────┘      │                    │
     │                 │                      │                       │                    │
     │                 │                      │ Save to storage:      │                    │
     │                 │                      │ yandex/device_auth/   │                    │
     │                 │                      │ session               │                    │
     │                 │                      │ yandex/cookies        │                    │
     │                 │                      │ ├──────────────┐      │                    │
     │                 │                      │ │ Atomic write │      │                    │
     │                 │                      │ └──────────────┘      │                    │
     │                 │                      │                       │                    │
     │                 │                      │ Publish event:        │                    │
     │                 │                      │ yandex.device_auth.   │                    │
     │                 │                      │ linked                │                    │
     │                 │                      │ ├──────────────┐      │                    │
     │                 │                      │ │ EventBus     │      │                    │
     │                 │                      │ └──────────────┘      │                    │
     │                 │                      │                       │                    │
     │                 │                      │ Update session.state  │                    │
     │                 │                      │ = "approved"          │                    │
     │                 │                      │ ╚═════════════╝       │                    │
     │                 │                      │                       │                    │
     │                 │ [UI Polling]         │                       │                    │
     │                 │ GET /yandex/auth/    │                       │                    │
     │                 │ device/status        │                       │                    │
     │                 ├─────────────────────>│                       │                    │
     │                 │                      │                       │                    │
     │                 │ {state: "approved",  │                       │                    │
     │                 │  quasar_ready: true} │                       │                    │
     │                 │<─────────────────────┤                       │                    │
     │                 │                      │                       │                    │
     │                 │ Show success ✅      │                       │                    │
     │<────────────────┤                      │                       │                    │
     │                 │                      │                       │                    │
     │                 │                      │ [Meanwhile]           │                    │
     │                 │                      │ yandex_smart_home     │                    │
     │                 │                      │ plugin receives event │                    │
     │                 │                      │ → starts Quasar WS    │                    │
     │                 │                      │                       │                    │
```

---

## Архитектура модулей

```
┌─────────────────────────────────────────────────────────────────┐
│                    YandexDeviceAuthPlugin                        │
│                    (BasePlugin)                                  │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        │ creates
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│              YandexDeviceAuthService                             │
│              (единый entrypoint)                                 │
│                                                                  │
│  • start_auth(method, options)                                  │
│  • get_status(device_id)                                        │
│  • cancel(device_id)                                            │
│  • get_account_session()                                        │
│  • _poll_loop(device_id) [background]                           │
└───────┬─────────────────┬───────────────────┬───────────────────┘
        │                 │                   │
        │ uses            │ manages           │ uses
        ▼                 ▼                   ▼
┌──────────────┐  ┌───────────────────┐  ┌──────────────────┐
│ AuthMethod   │  │ YandexDeviceSession│  │ YandexAPIClient  │
│ (abstract)   │  │ (in-memory)        │  │                  │
└──────┬───────┘  └───────────────────┘  └──────────────────┘
       │
       │ implementations
       ▼
┌────────────────────────────────────────────────────────────────┐
│  QRAuthMethod                                                   │
│  • start() → device_code, qr_url                               │
│  • poll(session) → AuthResult                                  │
│  • finalize(result) → YandexAccountSession                     │
└────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────┐
│  OneTimeCodeAuthMethod                                          │
│  • start() → device_code, user_code                            │
│  • poll(session) → AuthResult                                  │
│  • finalize(result) → YandexAccountSession                     │
└────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────┐
│  EmailLinkAuthMethod                                            │
│  • start(options) → device_code, verification_url              │
│  • poll(session) → AuthResult                                  │
│  • finalize(result) → YandexAccountSession                     │
└────────────────────────────────────────────────────────────────┘
```

---

## Data Flow: Device Session → Account Session → Quasar WS

```
┌─────────────────┐
│ User initiates  │
│ device auth     │
└────────┬────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ YandexDeviceSession                  │
│ ┌──────────────────────────────────┐ │
│ │ device_id: "dev_abc123"          │ │
│ │ method: "qr"                     │ │
│ │ state: "pending"                 │ │
│ │ device_code: "dc_xyz..."         │ │
│ │ qr_url: "https://..."            │ │
│ │ expires_at: timestamp            │ │
│ │ poll_interval: 5                 │ │
│ └──────────────────────────────────┘ │
│ (in-memory, temporary)               │
└────────┬─────────────────────────────┘
         │
         │ polling loop
         │ (background task)
         ▼
┌──────────────────────────────────────┐
│ Yandex API Response                  │
│ ┌──────────────────────────────────┐ │
│ │ state: "approved"                │ │
│ │ cookies: {                       │ │
│ │   Session_id: "...",             │ │
│ │   yandexuid: "...",              │ │
│ │   sessionid2: "..."              │ │
│ │ }                                │ │
│ └──────────────────────────────────┘ │
└────────┬─────────────────────────────┘
         │
         │ finalize()
         ▼
┌──────────────────────────────────────┐
│ YandexAccountSession                 │
│ ┌──────────────────────────────────┐ │
│ │ cookies: {...}                   │ │
│ │ quasar_ready: true               │ │
│ │ linked_at: timestamp             │ │
│ │ method: "qr"                     │ │
│ └──────────────────────────────────┘ │
│ (persistent, storage)                │
└────────┬─────────────────────────────┘
         │
         │ save to storage
         ▼
┌──────────────────────────────────────┐
│ Storage                              │
│ ┌──────────────────────────────────┐ │
│ │ yandex/device_auth/session       │ │
│ │ yandex/cookies                   │ │
│ └──────────────────────────────────┘ │
└────────┬─────────────────────────────┘
         │
         │ publish event
         ▼
┌──────────────────────────────────────┐
│ EventBus                             │
│ yandex.device_auth.linked            │
└────────┬─────────────────────────────┘
         │
         │ subscriber
         ▼
┌──────────────────────────────────────┐
│ yandex_smart_home Plugin             │
│ ┌──────────────────────────────────┐ │
│ │ _on_device_linked(event)         │ │
│ │   → quasar_ws.start()            │ │
│ └──────────────────────────────────┘ │
└────────┬─────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ YandexQuasarWS                       │
│ ┌──────────────────────────────────┐ │
│ │ Load cookies from storage        │ │
│ │ Connect to iot.quasar.yandex.ru  │ │
│ │ Subscribe to device updates      │ │
│ │ Publish external.device_state_   │ │
│ │ reported events                  │ │
│ └──────────────────────────────────┘ │
└──────────────────────────────────────┘
```

---

## State Transitions

```
┌─────────┐
│  idle   │ (no active session)
└────┬────┘
     │
     │ start_auth()
     ▼
┌─────────┐
│ pending │ (waiting for user confirmation)
└────┬────┘
     │
     ├───────────────────────┬─────────────────┬──────────────┐
     │                       │                 │              │
     │ user confirms         │ timeout         │ user rejects │ cancel()
     ▼                       ▼                 ▼              ▼
┌──────────┐          ┌─────────┐        ┌──────────┐  ┌───────────┐
│ approved │          │ expired │        │ rejected │  │ cancelled │
└────┬─────┘          └─────────┘        └──────────┘  └───────────┘
     │
     │ save cookies
     │ publish event
     ▼
┌─────────┐
│ linked  │ (persistent account session)
└─────────┘
```

---

## Comparison: OAuth vs Device Auth

```
┌────────────────────────────────────────────────────────────────────────┐
│                     OAuth Flow                                          │
├────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  User → Browser → yandex.ru/authorize                                  │
│                     ↓                                                   │
│                   Login                                                 │
│                     ↓                                                   │
│                   Redirect → redirect_uri?code=...                      │
│                     ↓                                                   │
│  Backend ← code                                                         │
│         → exchange code → access_token, refresh_token                   │
│                                                                         │
│  Result: OAuth tokens (for public API)                                 │
│  ❌ No session cookies                                                  │
│  ❌ Quasar WS doesn't work                                              │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                   Device/QR Flow                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Backend → Yandex API → device_code, qr_url                            │
│         → Display QR to user                                            │
│                     ↓                                                   │
│  User → Mobile app → Scan QR                                           │
│                     ↓                                                   │
│                   Confirm                                               │
│                     ↓                                                   │
│  Backend ← poll → state: approved, cookies                             │
│         → save cookies                                                  │
│                                                                         │
│  Result: Session cookies (Session_id, yandexuid)                       │
│  ✅ Cookies available on backend                                       │
│  ✅ Quasar WS works                                                     │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Extensibility: Adding New Auth Method

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. Create new class in auth_methods.py                           │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   class PasswordAuthMethod(AuthMethod):                          │
│       async def start(self, options):                            │
│           # Custom logic for password auth                       │
│           return {                                               │
│               "device_code": ...,                                │
│               "verification_url": ...,                           │
│           }                                                       │
│                                                                   │
│       async def poll(self, session):                             │
│           # Custom polling logic                                 │
│           # (for password, might be instant)                     │
│           return AuthResult(state="approved", cookies=...)       │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│ 2. Register in device_auth_service.py                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   def __init__(self, runtime, api_client):                       │
│       self.methods = {                                           │
│           "qr": QRAuthMethod(...),                               │
│           "code": OneTimeCodeAuthMethod(...),                    │
│           "email": EmailLinkAuthMethod(...),                     │
│           "password": PasswordAuthMethod(...),  # NEW            │
│       }                                                           │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│ 3. Use via API                                                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   POST /yandex/auth/device/start                                 │
│   {                                                               │
│     "method": "password",                                        │
│     "options": {                                                 │
│       "username": "user@example.com",                            │
│       "password": "secret"                                       │
│     }                                                             │
│   }                                                               │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

Все остальные компоненты (polling, storage, events) работают автоматически!
