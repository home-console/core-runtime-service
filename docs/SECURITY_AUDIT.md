# Security Audit: OWASP Top 10 (2021)

**Дата актуализации:** 27 января 2026  
**Версия проекта:** 0.2.0  
**Статус:** � ТРЕБУЕТ СРОЧНЫХ ИСПРАВЛЕНИЙ  
**Тип:** Comprehensive Deep-Dive Audit v2.0  
**Проверил:** GitHub Copilot (Claude Haiku 4.5)

**⚠️ ВАЖНО:** Этот документ - обзорный аудит. Более подробная информация:
- 📋 [SECURITY_DEEP_DIVE_AUDIT.md](./SECURITY_DEEP_DIVE_AUDIT.md) — 18 дополнительных уязвимостей
- 🛠️ [SECURITY_IMPLEMENTATION_GUIDE.md](./SECURITY_IMPLEMENTATION_GUIDE.md) — Код и примеры исправлений
- ✅ [SECURITY_IMPLEMENTATION_CHECKLIST.md](./SECURITY_IMPLEMENTATION_CHECKLIST.md) — День-за-днём план работ

---

## 🔴 Критичные находки (от аудита 27 января 2026)

| # | Риск | Проблема | Сложность | Приоритет |
|---|------|---------|-----------|-----------|
| 1 | 🔴 CRITICAL | SSRF в RemotePluginProxy (no URL validation) | Средняя | P0 |
| 2 | 🔴 HIGH | Нет Idempotency-Key поддержки (race conditions) | Низкая | P1 |
| 3 | 🟠 MEDIUM | Нет JWT key rotation | Высокая | P1 |
| 4 | 🟠 MEDIUM | Нет автоматического dependency scanning | Низкая | P2 |
| 5 | 🟡 LOW | Нет jti (JWT ID) для tracking revocation | Средняя | P2 |

---



Аудит **нельзя считать закрытым**, пока не выполнены минимум:
- A01: ownership/ACL enforcement **на уровне данных/сервисов**, не только на HTTP boundary
- A02: JWT secret >= 256 бит (энтропии) + ротация ключей
- A08: replay/integrity модель (nonce/TTL и т.п.)
- A10: URL allowlist/validation для всех внешних запросов, где URL может прийти извне

---

## OWASP Top 10 (2021) — актуальная оценка

### A01:2021 – Broken Access Control

**Статус:** 🟡 Частично

**Сделано (факт):**
- Есть policy layer `modules/api/authz.py` и scope checks
- Для `devices.get` / `devices.set_state` есть ACL проверка на HTTP boundary (через resource owner/shared)
- Админ-доступ ограничен приватной сетью: `modules/api/admin_access_middleware.py`

**Нужно сделать, чтобы закрыть:**
- Внедрить ownership/ACL enforcement **в сервисный слой** (или отдельный secure service interface), иначе плагины/модули могут обойти HTTP-layer проверки
- Унифицировать поведение “403 vs 404” так, чтобы не утекало существование ресурсов
- Расширить resource-based проверки на остальные доменные ресурсы (mappings, sessions, api keys и т.д.)
- Включить безопасный режим определения client IP для admin-панели: **не доверять proxy headers по умолчанию** (`RUNTIME_TRUST_PROXY_HEADERS=false`)

---

### A02:2021 – Cryptographic Failures

**Статус:** 🟡 Частично | 🆙 УЛУЧШЕНО

**Сделано (факт):**
- ✅ bcrypt для паролей (bcrypt>=4.0.0), SHA-256 для API key storage  
- ✅ HttpOnly cookies для токенов, secure/samesite/domain управляются через config  
- ✅ JWT secret: `secrets.token_urlsafe(32)` = 256 бит (базовая энтропия)
- ✅ Кеширование JWT secret в памяти (избегает race conditions)
- ⚠️ **ПРОБЛЕМА НАЙДЕНА:** JWT_SECRET_KEY_LENGTH = 32 байта (256 бит базовая энтропия, но `token_urlsafe` дает ~256 бит полезной энтропии). Для HMAC-SHA256 рекомендуется >=256 бит. **СТАТУС: ОК, но на минимуме.**
- ❌ **НЕТ ротации JWT secrets** — используется один static secret, хранится в storage

**Нужно сделать, чтобы закрыть:**
1. **URGENT** — Реализовать ротацию JWT secrets:
   - Добавить multi-key поддержку (текущий ключ + предыдущие)
   - Добавить `kid` (key ID) в JWT header
   - Grace period (7 дней) для старых ключей при валидации
   - Ротация = каждые 90 дней или по требованию admin
   
2. В prod-режиме enforce: `cookies_secure=True`, корректный `SameSite` и `domain` (без `localhost`)
   
3. Хранение JWT secrets с дополнительной защитой (encryption at rest, если возможно)

---

### A03:2021 – Injection

**Статус:** 🟡 Частично

**Сделано (факт):**
- SQL инъекций нет (param queries через адаптеры)
- Добавлены Pydantic-модели для части критичных endpoint’ов: `modules/api/validation_models.py`
- Валидация body включена в `modules/api/module.py` для известных security-critical сервисов

**Нужно сделать, чтобы закрыть:**
- Покрыть валидацией **все** state-changing admin/auth endpoints (create_user, password set/change, revoke и т.д.)
- Добавить нормализацию/allowlist для ключевых полей (user_id, scopes, ids)
- Ввести единый подход к ошибкам валидации (без утечек внутренностей)

---

### A04:2021 – Insecure Design

**Статус:** 🟡 Частично

**Сделано (факт):**
- Rate limiting на auth endpoints и на API requests
- CSRF: double-submit token для cookie-based auth на unsafe methods (middleware)
- CSP разделён по режимам: relaxed (dev) / strict (prod) через config

**Нужно сделать, чтобы закрыть:**
- Пройтись по списку публичных endpoints и убедиться, что CSRF не ломает легитимные сценарии, но покрывает все unsafe операции
- В prod включить strict CSP по умолчанию и проверить совместимость

---

### A05:2021 – Security Misconfiguration

**Статус:** 🟡 Частично

**Сделано (факт):**
- Security headers middleware на все ответы (включая ранние 401/403)
- CORS теперь настраивается через `Config.cors_allowed_origins` / env
- Есть `env=development|production` в конфиге

**Нужно сделать, чтобы закрыть:**
- В production enforce корректные CORS origins (никаких `*` при credentials)
- Явно зафиксировать “prod profile”: CSP strict, secure cookies, log_format=json и т.д.

---

### A06:2021 – Vulnerable and Outdated Components

**Статус:** � Частично | 🔍 ПРОВЕРЕНО

**Сделано (факт):**
- ✅ Зависимости перечислены в requirements.txt:
  - fastapi>=0.95.0 ✅
  - bcrypt>=4.0.0 ✅
  - PyJWT>=2.8.0 ✅
  - cryptography>=41.0.0 ✅
  - aiohttp>=3.10.0 ✅
  - asyncpg>=0.28.0 ✅

- ❌ **НЕТ автоматического dependency scanning в CI**

**Уязвимости для проверки:**
- `pip-audit` / `safety` — нет интеграции
- `npm audit` (для admin-ui-service) — нет проверки
- Python 3.11+ используется, что хорошо

**Нужно сделать, чтобы закрыть:**
1. Добавить `pip-audit` в CI pipeline:
   ```bash
   pip install pip-audit && pip-audit
   ```
2. Обновить зависимости до latest patch versions
3. Установить Dependabot (GitHub native)

---

### A07:2021 – Identification and Authentication Failures

**Статус:** 🟡 Частично

**Сделано (факт):**
- Защита от enumeration в login: единый `invalid_credentials`
- Rate limiting есть и управляется через config

**Нужно сделать, чтобы закрыть:**
- Унифицировать ответы и для других auth flows (initialize/create_user/password/refresh, где применимо)
- Определить MFA стратегию: либо реализовать (TOTP/WebAuthn), либо официально закрепить threat model и исключить MFA из “must-have”

---

### A08:2021 – Software and Data Integrity Failures

**Статус:** 🔴 Не закрыто | ⚠️ ТРЕБУЕТ ВНИМАНИЯ

**Анализ:**
- ❌ **НЕ реализовано:** Replay protection (nonce + TTL)
- ❌ **НЕ реализовано:** Idempotency keys для повторных запросов
- ⚠️ JWT имеет `exp` (expiration), но нет `jti` (JWT ID) для tracking individual tokens
- ⚠️ Refresh token имеет дату истечения, но нет проверки "используется ли уже раз"

**Риск сценарий:**
1. Пользователь кликает кнопку "Отключить устройство" дважды (быстро) → два одинаковых запроса
2. Если сеть дублирует пакеты (TCP retransmit), команда выполнится дважды
3. Никакой защиты от этого нет

**Нужно сделать, чтобы закрыть:**
1. **Добавить Idempotency-Key поддержку:**
   ```python
   # modules/api/idempotency.py
   class IdempotencyMiddleware:
       async def __call__(self, request: Request, call_next):
           key = request.headers.get("Idempotency-Key")
           if key and request.method in ("POST", "PUT", "DELETE"):
               # Проверить, не выполняли ли мы уже этот запрос
               cached = await cache.get(f"idempotency:{key}")
               if cached:
                   return cached
               
               response = await call_next(request)
               await cache.set(f"idempotency:{key}", response, ttl=3600)
               return response
   ```

2. **Добавить `jti` в JWT для revocation tracking:**
   - `jti` = `jwt_id` (уникальный ID каждого токена)
   - При logout/revoke добавить `jti` в revocation list
   - При валидации проверить, не в ли jti в revoked list

3. **Добавить нonce для критичных операций:**
   - Для изменения пароля / отвязки устройства
   - Nonce = одноразовый код, выдается при GET запросе, проверяется при POST

---

### A09:2021 – Security Logging and Monitoring Failures

**Статус:** 🟡 Частично

**Сделано (факт):**
- Audit logging есть
- Structured logging: `LoggerModule` поддерживает `log_format=json`

**Нужно сделать, чтобы закрыть:**
- В production включать JSON logging по умолчанию
- Centralized logging (Loki/ELK) — хотя бы documented integration + формат
- Alerting hooks на аномалии (rate-limit spikes, bursts of 401/403, refresh failures)

---

### A10:2021 – Server-Side Request Forgery (SSRF)

**Статус:** � Средний риск | 🔍 НАЙДЕНО

**Анализ кода:**
- ❌ `RemotePluginProxy._http_call()` в [plugins/remote_plugin_proxy.py](../../plugins/remote_plugin_proxy.py):
  - Принимает `endpoint: str` и формирует `url = f"{self.remote_url}{endpoint}"`
  - **РИСК:** Нет валидации URL
  - **ИСПОЛЬЗОВАНИЕ:** Плагины могут отправлять HTTP запросы без ограничений
  - **ПРИМЕР АТАКИ:**
    ```python
    # Плагин может сделать:
    await proxy._http_call("@http://internal-db:5432/")
    # или redirect в локальную сеть
    ```

- ⚠️ `trust_proxy_headers` в конфиге по умолчанию `False` (это **хорошо**)
- ⚠️ `admin_access_middleware.py` корректно блокирует публичный доступ к /admin/*

**Нужно сделать, чтобы закрыть:**
1. **CRITICAL** — Добавить URL allowlist validator:
   ```python
   # modules/api/security/url_validator.py
   def validate_external_url(url: str) -> bool:
       """
       Валидирует URL для внешних запросов.
       - Запрещает: localhost, 127.0.0.1, 169.254.x.x, private IPs
       - Запрещает: file://, ftp://, gopher://, telnet://
       - Разрешает: только http:// и https://
       """
       pass
   ```

2. Применить в `RemotePluginProxy._http_call()`:
   ```python
   from modules.api.security.url_validator import validate_external_url
   
   async def _http_call(self, endpoint: str, ...):
       url = f"{self.remote_url}{endpoint}"
       if not validate_external_url(url):
           raise ForbiddenError("URL not allowed")
   ```

---

## Приоритет (что делаем дальше)

1. 🔴 **A10 (SSRF)**: URL allowlist/validation в RemotePluginProxy — **IMMEDIATE**
2. 🔴 **A08 (Integrity)**: Idempotency-Key middleware для race conditions — **WEEK 1**
3. 🟠 **A02 (Crypto)**: JWT key rotation + multi-key support — **WEEK 2**
4. 🟠 **A01 (ACL)**: Enforcement на сервисном уровне — **MONTH 1**
5. 🟡 **A06/A09**: Dependency scanning + centralized logging — **ONGOING**

---

## Production checklist (актуальный)

**ПЕРЕД PRODUCTION DEPLOYMENT:**

### Конфигурация
- [ ] `RUNTIME_ENV=production`
- [ ] `RUNTIME_TRUST_PROXY_HEADERS=false` (или явно `true` если за реальным proxy)
- [ ] `RUNTIME_CORS_ALLOWED_ORIGINS` выставлен на реальные домены (без `*`)
- [ ] `RUNTIME_CSP_MODE=strict`
- [ ] `RUNTIME_LOG_FORMAT=json`
- [ ] `RUNTIME_COOKIES_SECURE=true` + корректный `RUNTIME_COOKIES_DOMAIN` (не localhost)
- [ ] `RUNTIME_CSRF_ENABLED=true` и фронт отправляет `X-CSRF-Token`

### Безопасность
- [ ] JWT secret >= 256 бит (текущее: ✅ 256 бит)
- [ ] Планы на ротацию JWT secrets (раз в 90 дней)
- [ ] SSRF validation включена в плагинах
- [ ] Idempotency-Key поддержка для критичных операций
- [ ] Rate limiting включён (auth: 10 попыток/60 сек)

### CI/CD
- [ ] `pip-audit` запускается при каждом push
- [ ] `npm audit` для admin-ui-service
- [ ] Результаты сканирования в отчётах
- [ ] Dependency updates на schedule (Dependabot)

### Мониторинг
- [ ] Structured logging (JSON format) включен
- [ ] Audit logs отправляются в централизованный storage
- [ ] Alerts на rate-limit spikes (>100 401 ошибок за 5 мин)
- [ ] Alerts на 403 bursts (возможный перебор доступа)

---

## Дополнительные рекомендации

### 1. Документирование (Security Model)
```markdown
# Threat Model

## Trust Boundaries
- HTTP boundary: валидируем all requests (JWT, CSRF, rate limiting)
- Internal services: считаем trusted (нет extra checks)
- External URLs: SSRF validation required

## Authentication Model
- JWT access tokens: 15 минут
- Refresh tokens: 7 дней (в storage, revoke list)
- API keys: indefinite (до manual revoke)

## Authorization Model
- Admin: only from private IPs (127.0.0.1, 10.x, 172.16-31.x, 192.168.x)
- Users: resource owner или в shared_with list
- Scopes: admin.*, device.read, device.write и т.д.
```

### 2. Данные для чек-листа
- Версия Python: 3.11+
- Основные зависимости: fastapi, bcrypt, PyJWT, cryptography, aiohttp
- Развертывание: Docker / Kubernetes (рекомендуется)

---

## Ссылки на стандарты

- [OWASP Top 10 (2021)](https://owasp.org/Top10/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [FastAPI Security Best Practices](https://fastapi.tiangolo.com/advanced/security/)
- [JWT Best Practices](https://tools.ietf.org/html/rfc8725)
- [SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
