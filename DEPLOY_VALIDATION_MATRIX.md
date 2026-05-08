# Деплой, smoke и операции (core + platform + `hc`)

Этот файл — **единая точка входа**: матрица смоук‑тестов, **runbook прод**, **жизненный цикл секретов** и ориентиры по **плагинам / реестру / фронту**.

## Общие инварианты

- **Health ядра**: `http://<host>:<port>/api/v1/monitor/health`  
  Внутри контейнера: `http://localhost:8000/api/v1/monitor/health`
- **Prod edge (HTTP/HTTPS по умолчанию)**: порты из `HTTP_PORT` / `HTTPS_PORT` в `deploy/prod/docker-compose.image.yml` (часто **80** / **443**).
- **Dev Caddy** (параллельно с прод): по умолчанию **18080** / **18443**, Redis на хосту **6380**, прямое ядро **18000** (`DEV_HTTP_PORT`, …).
- **Плагины**:
  - **volume (dev)**: `plugins/` → `/app/plugins`, `RUNTIME_PLUGINS_DIR=/app/plugins`
  - **baked-in (image)**: `plugins/` внутри образа (`Dockerfile` `COPY`)

---

## 1) Runbook: первый прод на хосте

**Предусловия:** установлены Docker, `hc` из `home-console-cli`, на сервере путь к репо `core-runtime-service` (или только compose + `.env` bootstrap).

1. **Bootstrap мастер‑ключа** (один раз, не класть в git):
   - На хосте выставить **`RUNTIME_MASTER_KEY`** или **`RUNTIME_MASTER_KEY_FILE`** (разблокировка SecretStore).
   - При деплое по SSH `hc deploy` может прокидывать ключ — см. `hc/commands/deploy.py`.

2. **Образы в registry**  
   Собрать и запушить `core-runtime` и `platform-home-console` в Ghcr (или свой registry).  
   Локальный smoke образа: `./scripts/ci_local.sh`.

3. **Поднять прод‑стек**

   ```bash
   hc deploy stack \
     --core-image ghcr.io/home-console/core-runtime --core-tag <tag> \
     --platform-image ghcr.io/home-console/platform-home-console --platform-tag <tag> \
     --domain example.com \
     --ssh user@host --path /srv/core-runtime-service
   ```

   Локально без SSH: тот же вызов без `--ssh`, из монорепы, чтобы подтянулся `deploy/prod/docker-compose.image.yml`.

4. **SecretStore и прикладные секреты**

   ```bash
   hc secrets probe --mode prod --ssh user@host --path /srv/core-runtime-service
   hc secrets init --mode prod --ssh user@host --path /srv/core-runtime-service --source store+env
   ```

   После того как ключи оказались в store, в `.env` можно убрать дубли и перейти на **`RUNTIME_SECRETS_SOURCE=store`** (см. ниже).

5. **Smoke снаружи**

   - Edge: `curl -fsS https://example.com/api/v1/monitor/health` (или `http://localhost:80/...` если так настроен домен).
   - Логи: `hc deploy core logs --mode prod --ssh ...`

6. **Обновление только ядра**

   ```bash
   hc deploy core rollout --mode prod --tag <новый> --ssh user@host --path /srv/core-runtime-service
   ```

   Если образ только локальный без pull: добавить `--no-pull`.

---

## 2) Секреты: что в store, что в env

Цель: **после первого init** ядро получает критичные значения из SecretStore; `.env` минимален (bootstrap + неконфиденциальный конфиг).

Мастер‑ключ (всегда вне store, bootstrap):

- `RUNTIME_MASTER_KEY` или `RUNTIME_MASTER_KEY_FILE`

Прикладные ключи, которые **маппятся в SecretStore** при bootstrap (`app/env_bootstrap.py`):

| Env (legacy чтение)     | Ключ в store                 | Обязателен |
|-------------------------|------------------------------|------------|
| `CSRF_SECRET`           | `runtime.csrf_secret`        | да*        |
| `OAUTH_ENCRYPTION_KEY`  | `runtime.oauth_encryption_key` | да*      |
| `YANDEX_CLIENT_SECRET`  | `yandex.client_secret`       | нет        |

\* если `RUNTIME_CSRF_ENABLED` не отключён для CSRF/OAuth.

Режим **`RUNTIME_SECRETS_SOURCE`**:

- `store+env` — миграция: store приоритетнее, иначе импорт из env в store.
- `store` — только store (генерация при необходимости на первом writable старте).
- `env` — только env (без персистирования в store; больше для отладки).

**Практика после `hc secrets init`:** перевести прод на `store`, убрать из `.env` дубли `CSRF_SECRET` / `OAUTH_ENCRYPTION_KEY` (и опционально секреты OAuth), перезапустить stack, снова `hc secrets probe`.

---

## 3) Матрица smoke (команды)

### A) Local dev / build / sqlite / redis

- Rollout:  
  `hc deploy core rollout --mode dev --db sqlite --cache redis --no-wait`
- Wait:  
  `hc deploy core wait --mode dev --health-url http://localhost:8000/api/v1/monitor/health`
- Ручная проверка API:  
  `curl -fsS http://localhost:18000/api/v1/monitor/health`
- UI через Caddy (dev):  
  `curl -fsS http://localhost:18080/api/v1/monitor/health` (через proxy)

### B) Local dev / sqlite / memory

- `hc deploy core rollout --mode dev --db sqlite --cache memory --no-wait`
- `hc deploy core wait --mode dev`

### C) Local dev-image / sqlite / redis (образ, dev-инфра)

- `hc deploy core rollout --mode dev-image --tag latest --db sqlite --cache redis --no-wait`
- `hc deploy core wait --mode dev-image`

### D) Remote dev-image или prod

Предусловие: на сервере есть репо/каталог с `deploy/dev/` или `deploy/prod/` compose.

- Dev-image:  
  `hc deploy core rollout --mode dev-image --ssh user@host --path /srv/core-runtime-service --tag <tag> ...`
- Prod:  
  `hc deploy core rollout --mode prod --ssh user@host --path /srv/core-runtime-service --tag <tag> ...`

### E) Platform → dev frontend (локально)

```bash
hc deploy platform --mode dev --build --start
```

Ожидание: `dist` в `deploy/dev/frontend/`, UI на **`http://localhost:18080`** (не `:80` если прод уже занял порт).

### F) Platform → remote dev stage

```bash
hc deploy platform --mode dev --build --ssh user@host --path /srv/core-runtime-service --restart-remote
```

### G) Полный локальный CI перед пушем (ядро)

```bash
./scripts/ci_local.sh
```

---

## 4) Минимальный «быстрый прогон»

**Локально (dev):**

- `hc deploy core rollout --mode dev --db sqlite --cache redis --no-wait`
- `hc deploy core wait --mode dev`
- `hc deploy platform --mode dev --build --start`
- Открыть `http://localhost:18080`

**Прод (после того как образы в registry):**

- `hc deploy stack` (или уже поднятый стек)
- `hc secrets probe --mode prod` (+ SSH/path при необходимости)
- `curl` health через edge URL

---

## 5) Плагины и реестр — куда докручивать (без подписи «лишний раз»)

Контекст ядра: контракт плагина и изоляция — `core/kernel/plugin_contract.py`, загрузчик/прокси.  
Отдельно **marketplace-api** — прототип реестра по `TZ_PLUGIN_REGISTRY_CRITICAL_GAPS.md` (в корне монорепы HomeConsole).

**Уже есть в реестре (по ТЗ-документу):** индекс, выдача пакетов, multipart upload как каркас.

**Реально закрыть следующим спринтом (must-have для «доверять реестру»):**

1. **Крипто на сервере:** посчитать SHA256 архива, проверить Ed25519 по стандарту (base64 ключ/подпись), при ошибке **не сохранять** файл — сейчас часть метаданных может быть формальной.
2. **Инспекция архива:** лимиты файлов/размера (archive bomb), валидный `plugin.json` и совпадение версии.
3. **API keys / роли publisher vs admin** вместо одного статического admin token где это требует ТЗ.
4. **Кеш `index.json` + инвалидация** под целевой SLO.

**Подпись плагина на клиенте (ядро):** имеет смысл после того, как сервер гарантированно отдаёт проверенный артефакт; иначе смысл «цепочки доверия» размывается. Порядок: **верификация на registry → затем опционально повторная проверка при установке в core**.

---

## 6) Фронт (platform + prod stack)

| Сценарий | Что использовать |
|---------|-------------------|
| Dev UI за Caddy | `hc deploy platform --mode dev`, открыть **http://localhost:18080** |
| HMR в Docker | `deploy/dev/docker-compose.reload.yml` + profile `frontend`, см. заголовок compose |
| Prod | Образ **`PLATFORM_IMAGE`** в `deploy/prod/docker-compose.image.yml`; edge проксирует на platform-web |

Проверка после деплоя: главная платформы загружается, запросы к `/api/v1/` уходят на core (cookies/CORS см. `.env.example` при прямом `localhost:18000`).

---

## Устаревшие команды (не использовать)

- `--mode image` для core → заменено на **`--mode dev-image`**.
- Ожидание dev UI на `http://localhost/` без указания порта → для параллельного прода использовать **`http://localhost:18080`**.
