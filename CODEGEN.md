# API Schema & Codegen

## Архитектура типизации

```
core-runtime-service          platform-home-console
─────────────────────         ──────────────────────────────────
modules/api/schemas/*.py  →   openapi.json  →  packages/types/src/generated.ts
    (Pydantic DTO)             (export)          (openapi-typescript)
         │
         ↓
    HttpEndpoint(
      response_model=...,    ← единый контракт для runtime + HTTP + OpenAPI
      request_model=...,
    )
         │
         ↓
    bind_routes → FastAPI → /openapi.json (автоматически)
```

## Правила (обязательные)

### 1. Каждый HTTP endpoint ОБЯЗАН иметь response_model

```python
# ✅ правильно
HttpEndpoint(
    method="GET",
    path="/api/v1/devices",
    service="...",
    response_model=ApiResponse[List[DeviceDto]],
)

# ❌ запрещено
HttpEndpoint(
    method="GET",
    path="/api/v1/devices",
    service="...",
)
```

### 2. POST/PUT/PATCH ОБЯЗАНЫ иметь request_model

```python
# ✅ правильно
HttpEndpoint(
    method="POST",
    path="/api/v1/devices/{id}/state",
    request_model=SetDeviceStateRequest,
    response_model=OkErrorResponse,
)
```

### 3. DTO-схемы только в modules/api/schemas/

```python
# ✅ правильно — без импортов из core.*
from pydantic import BaseModel

class DeviceDto(BaseModel):
    id: str
    ...

# ❌ запрещено
from core.runtime.models import Device  # нельзя!
```

### 4. Все ответы через ApiResponse[T]

```python
# ✅ обычный payload
response_model=ApiResponse[DeviceDto]         # → {"ok": true, "result": {...}}
response_model=ApiResponse[List[DeviceDto]]   # → {"ok": true, "result": [...]}

# ✅ для "ok"-only ответов
response_model=OkResponse                     # → {"ok": true}
response_model=OkErrorResponse               # → {"ok": bool, "error"?: str}
response_model=DeletedResponse               # → {"ok": true, "deleted": true}
```

## Как обновить OpenAPI schema

### Шаг 1 — Запустить backend и экспортировать

```bash
# Запустить core-runtime-service
cd core-runtime-service

# Экспортировать схему (runtime должен быть запущен)
# Вариант A: из живого сервера
curl http://localhost:18000/openapi.json > openapi.json

# Вариант B: через скрипт (не требует запущенного сервера)
python scripts/export_openapi.py --out openapi.json
```

### Шаг 2 — Сгенерировать TypeScript типы

```bash
cd platform-home-console
pnpm api:gen
# → packages/types/src/generated.ts
```

### Шаг 3 — Использовать в коде

```typescript
// Импортировать типы из generated.ts через @platform/types
import type { components } from '@platform/types/generated'
type Device = components['schemas']['DeviceDto']
```

## Добавление нового endpoint

1. Создать Pydantic DTO в `modules/api/schemas/<domain>.py`
2. Добавить экспорт в `modules/api/schemas/__init__.py`
3. Зарегистрировать `HttpEndpoint` с `response_model` и `request_model`
4. Запустить `pnpm api:gen` на платформе

## Структура schemas/

```
modules/api/schemas/
├── __init__.py      # центральный экспорт
├── common.py        # ApiResponse[T], OkResponse, OkErrorResponse, DeletedResponse
├── auth.py          # UserDto, SessionDto, ApiKeyDto + request models
├── devices.py       # DeviceDto, DeviceStateDto + request models
├── plugins.py       # PluginDto, PluginDetailsDto + request models
├── operations.py    # OperationDto, ExecutionDto, ExecutionScheduleDto + request models
├── inspector.py     # DashboardSummaryDto, RuntimeInfoDto, ServiceDto ...
├── agents.py        # AgentDto, DeploymentStatusDto + request models
├── credentials.py   # CredentialDto + request models
├── ssh.py           # SshSessionDto + request models
├── storage.py       # StorageNamespaceDto ...
├── marketplace.py   # MarketplaceCatalogEntryDto + request models
├── integrations.py  # IntegrationDto, IntegrationFlowDto
└── presence.py      # PresenceStatusDto
```

## TypeScript HTTP client (orval)

Platform web codegen for typed fetch client:

```bash
cd ../platform-home-console
pnpm api:gen:client      # or pnpm api:gen:all
```

Output: `packages/api-client/src/generated/`. See `platform-home-console/docs/API_CODEGEN.md`.

