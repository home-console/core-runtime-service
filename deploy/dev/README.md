# Dev Stage Deployment

## Архитектура

```
                    ┌─────────────────────────────────┐
  http://localhost  │  Caddy (:80)                    │
                    │  ┌───────────┐  ┌────────────┐ │
  /api/*            │  │           │  │ Frontend   │ │
  /admin/*          │  │ reverse   │  │ static     │ │
  /auth/*           │  │ proxy ────┼─▶│ files /srv │ │
  /presence/*       │  │           │  │            │ │
  /media/*          │  └─────┬─────┘  └────────────┘ │
  /oauth/*          │        │                        │
  /yandex/*         │        │ port 8000              │
                    │        ▼                        │
                    │  ┌─────────────────┐            │
                    │  │ core-runtime    │            │
                    │  │ (FastAPI)       │            │
                    │  └─────────────────┘            │
                    └─────────────────────────────────┘
```

## Быстрый старт

### 1. Запустить demo-скрипт

```bash
./deploy/dev/start.sh
```

Скрипт сам:

- создаст `.env`, если его ещё нет
- соберёт `platform-home-console` через `pnpm build:web`
- синхронизирует `apps/web/dist` в `deploy/dev/frontend`
- поднимет Docker Compose

Открой **http://localhost:18080** — фронт и API на одном origin, cookies работают из коробки.

### Только бэкенд (без фронта)

```bash
./deploy/dev/start.sh --no-ui
# → http://localhost:18000
```

### Если фронт уже собран

```bash
./deploy/dev/start.sh --skip-build
```

### Остановить

```bash
docker compose -f deploy/dev/docker-compose.yml down
```

## Конфигурация

`.env` в корне проекта — тот же файл, что для локальной разработки.
Минимум: `RUNTIME_MASTER_KEY` (всё остальное core положит в SecretStore при первом старте).

## Production заметки

Для production:
- Замени `localhost` на реальный домен в `Caddyfile` → Caddy автоматически получит TLS через Let's Encrypt
- Вынеси `.env` secrets в secure vault
- Добавь resource limits в docker-compose
- Добавь backup для `/data` volume
