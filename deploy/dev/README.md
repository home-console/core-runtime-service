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

### 1. Собрать фронт

```bash
cd ../platform-home-console
pnpm install
pnpm build:web
cp -r apps/web/dist ../../core-runtime-service/deploy/dev/frontend/
```

### 2. Запустить

```bash
./deploy/dev/start.sh
```

Открой **http://localhost** — фронт и API на одном origin, cookies работают из коробки.

### Только бэкенд (без фронта)

```bash
./deploy/dev/start.sh --no-ui
# → http://localhost:8000
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
