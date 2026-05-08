# Матрица проверок деплоя (core + platform через `hc`)

Цель: быстро прогонять **минимальный smoke** после изменений деплой-контракта (health URL, db/cache, плагины, platform sync).

## Общие инварианты

- **Health URL**: `http://localhost:8000/api/v1/monitor/health`
- **Core API prefix**: `/...` (например: `/admin/v1/...`)
- **Плагины**:
  - **volume mode (dev)**: compose монтирует `core-runtime-service/plugins` → `/app/plugins`, `RUNTIME_PLUGINS_DIR=/app/plugins`
  - **baked-in mode (image)**: плагины в image (в `core-runtime-service/Dockerfile` `COPY . .` уже включает `plugins/`)

## Matrix

### 1) Local / dev / sqlite / redis / volume-plugins

- **rollout**
  - `hc deploy core rollout --mode dev --db sqlite --cache redis --no-wait`
- **wait**
  - `hc deploy core wait --mode dev --health-url http://localhost:8000/api/v1/monitor/health`
- **ручной sanity**
  - `curl -fsS http://localhost:18000/api/v1/monitor/health`

### 2) Local / dev / sqlite / memory / volume-plugins

- `hc deploy core rollout --mode dev --db sqlite --cache memory --no-wait`
- `hc deploy core wait --mode dev`

Ожидание: core работает без зависимости от redis (redis сервис может быть поднят, но backend = memory).

### 3) Local / image / sqlite / redis / baked-in plugins

- `hc deploy core rollout --mode image --tag latest --db sqlite --cache redis --no-wait`
- `hc deploy core wait --mode image`

Ожидание: core поднимается без монтирования `plugins/` (используются плагины из image).

### 4) Remote / image / postgres / redis / baked-in plugins

Предусловие: на remote есть `core-runtime-service` с `deploy/dev/docker-compose.image.yml` и корректные секреты/DSN в `.env`.

- `hc deploy core rollout --mode image --ssh user@host --path /srv/core-runtime-service --db postgres --cache redis --tag <tag> --no-wait`
- `hc deploy core wait --mode image --ssh user@host --path /srv/core-runtime-service`

### 5) Platform sync (local → local core dev stage)

- `hc deploy platform --mode dev --build --start`

Ожидание: файлы из `platform-home-console/apps/web/dist` попадают в `core-runtime-service/deploy/dev/frontend/`, UI открывается на `http://localhost/`.

### 6) Platform sync (local → remote core dev stage)

- `hc deploy platform --mode dev --build --ssh user@host --path /srv/core-runtime-service --restart-remote`

Ожидание: dist прилетает в `deploy/dev/frontend/` на remote и `caddy` перезапускается.

## Минимальный smoke (рекомендуемый “быстрый прогон”)

Локально:

- `hc deploy core rollout --mode dev --db sqlite --cache redis --no-wait`
- `hc deploy core wait --mode dev`
- `hc deploy platform --mode dev --build --start`

Remote (image):

- `hc deploy core rollout --mode image --ssh user@host --path /srv/core-runtime-service --tag <tag> --db postgres --cache redis --no-wait`
- `hc deploy core wait --mode image --ssh user@host --path /srv/core-runtime-service`
- `hc deploy platform --mode dev --build --ssh user@host --path /srv/core-runtime-service --restart-remote`

