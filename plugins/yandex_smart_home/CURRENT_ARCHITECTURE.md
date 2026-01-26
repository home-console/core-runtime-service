# Yandex OAuth + Cookies: Реальная Архитектура

## ✅ Что УЖЕ реализовано в plugin.py

В `oauth_yandex/plugin.py` уже есть **ВСЯ необходимая логика**:

### 1. OAuth Management

**Сервисы:**
```python
oauth_yandex.configure(client_id, client_secret, redirect_uri, scope)
oauth_yandex.get_authorize_url() → URL для авторизации
oauth_yandex.exchange_code(code) → обмен code на tokens
oauth_yandex.get_access_token() → получить текущий токен (с auto-refresh)
oauth_yandex.validate_token(token?) → проверить валидность
oauth_yandex.clear_tokens() → unlink аккаунт
```

**HTTP endpoints:**
```
POST /oauth/yandex/configure
GET  /oauth/yandex/status
GET  /oauth/yandex/authorize-url
POST /oauth/yandex/exchange-code
GET  /oauth/yandex/validate
POST /oauth/yandex/unlink
```

### 2. Cookie Management

**Сервисы:**
```python
oauth_yandex.set_cookies(cookies: dict) → сохранить cookies
oauth_yandex.get_cookies() → получить cookies
```

**HTTP endpoints:**
```
POST /oauth/yandex/cookies
GET  /oauth/yandex/cookies
```

### 3. Хранение

**Storage структура:**
```
Namespace: oauth_yandex
Keys:
  - config: {client_id, client_secret, redirect_uri, scope}
  - tokens: {access_token, refresh_token, expires_at}

Namespace: yandex
Keys:
  - cookies: {Session_id, yandexuid, sessionid2, ...}
```

---

## 🎯 Текущий Flow (как это работает СЕЙЧАС)

### OAuth Flow

```
1. POST /oauth/yandex/configure
   → сохраняет client_id, client_secret, redirect_uri

2. GET /oauth/yandex/authorize-url
   → возвращает URL: https://oauth.yandex.ru/authorize?...

3. User открывает URL в браузере
   → логинится на Яндексе
   → redirect на redirect_uri?code=XXX

4. POST /oauth/yandex/exchange-code {"code": "XXX"}
   → обменивает code на access_token
   → сохраняет tokens в storage
   → возвращает {"status": "success"}

5. GET /oauth/yandex/status
   → проверяет configured, authorized, access_token_valid
```

### Cookie Flow (для Quasar)

```
1. User открывает yandex.ru в браузере
   → логинится
   → открывает DevTools
   → копирует Session_id, yandexuid

2. POST /oauth/yandex/cookies
   {
     "Session_id": "3:1234567890...",
     "yandexuid": "9876543210"
   }
   → сохраняет в storage yandex/cookies

3. Quasar WebSocket использует:
   cookies = await runtime.service_registry.call("oauth_yandex.get_cookies")
```

---

## 🔍 Реальная Проблема

**OAuth и Cookies — это ДВА независимых процесса:**

1. **OAuth** → автоматический (после configure)
2. **Cookies** → ручной (копирование из DevTools)

### Почему нельзя автоматизировать cookies в web app?

**Browser security:**
- JavaScript не может читать cookies с другого домена (yandex.ru)
- Даже если OAuth прошёл, cookies НЕ попадают на наш backend
- Redirect от Яндекса НЕ включает cookies в query params

**Единственные способы:**
1. **Manual** (current) - user копирует из DevTools
2. **Browser extension** - extension имеет доступ к cookies
3. **Native app (Electron)** - app контролирует WebView
4. **Headless browser** (Playwright) - автоматизация для dev/test

---

## 💡 Что ДЕЙСТВИТЕЛЬНО можно улучшить

### Вариант 1: Улучшить UX для manual flow

**Сейчас:**
```
1. Configure OAuth
2. Get authorize URL → open → login → copy code → paste
3. Open DevTools → find Session_id → copy → paste
4. Same for yandexuid
```

**Улучшенный вариант (wizard UI):**
```typescript
// В admin-ui вместо отдельных шагов - единый wizard:

<YandexConnectWizard>
  <Step1 title="OAuth Setup">
    <OAuthForm />  // configure + authorize в одном окне
  </Step1>
  
  <Step2 title="Enable Real-Time" description="Optional">
    <CookieHelper>
      <Instructions>
        1. Open yandex.ru → login
        2. Press F12 → Application → Cookies
        3. Copy values:
      </Instructions>
      
      <Input 
        label="Session_id" 
        validate={val => /^3:\d+/.test(val)}
        help="Format: 3:1234567890..."
      />
      
      <Input 
        label="yandexuid" 
        validate={val => /^\d+$/.test(val)}
      />
      
      <Button>Save Cookies</Button>
      <Button secondary>Skip (no real-time updates)</Button>
    </CookieHelper>
  </Step2>
  
  <Step3 title="Success">
    ✅ OAuth connected
    {hasCookies && "✅ Real-time updates enabled"}
  </Step3>
</YandexConnectWizard>
```

**Преимущества:**
- Guided flow вместо отдельных API calls
- Validation в форме
- Skip option для cookies (OAuth still works)
- Единый UX

### Вариант 2: Browser Extension (optional)

Если пользователи просят автоматизацию:

```javascript
// Chrome extension manifest.json
{
  "permissions": ["cookies"],
  "host_permissions": ["https://*.yandex.ru/*"]
}

// background.js
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "getCookies") {
    chrome.cookies.getAll({domain: "yandex.ru"}, (cookies) => {
      const needed = {};
      cookies.forEach(c => {
        if (['Session_id', 'yandexuid', 'sessionid2'].includes(c.name)) {
          needed[c.name] = c.value;
        }
      });
      sendResponse({cookies: needed});
    });
    return true;
  }
});
```

---

## 📋 Практические Рекомендации

### Для Web App (текущая архитектура)

**✅ Оставить как есть:**
- OAuth flow через plugin.py сервисы
- Cookie manual entry

**✅ Улучшить UI:**
- Создать wizard component
- Добавить validation
- Показывать screenshots/instructions
- Skip option для cookies

**❌ НЕ нужно:**
- Создавать новые файлы unified_auth.py
- Дублировать логику из plugin.py
- Пытаться автоматизировать cookies в pure web

### Если хочется автоматизации

**Вариант A: Browser Extension**
- Effort: Medium
- UX: Excellent (for users with extension)
- Coverage: Только те, кто установит

**Вариант B: Electron Desktop App**
- Effort: High
- UX: Perfect
- Coverage: Все desktop users

**Вариант C: Оставить manual с улучшенным UI**
- Effort: Low
- UX: Good (better than now)
- Coverage: Все users

**Рекомендация:** Вариант C

---

## 🔧 Что делать с документацией

**Удалить избыточное:**
- ~~unified_auth.py~~ (удалено)
- ~~unified_auth_endpoints.py~~ (удалено)
- ~~INTEGRATION_EXAMPLE.py~~ (удалено)
- ~~UNIFIED_LOGIN_ARCHITECTURE.md~~ (слишком сложно)
- ~~TECHNICAL_DEEP_DIVE.md~~ (over-engineering)

**Оставить полезное:**
- ✅ QUICK_START.md → переписать под текущую архитектуру
- ✅ README.md → краткое описание текущей системы
- ✅ QUASAR_ARCHITECTURE_RULE.md → объясняет почему cookies

**Создать новое:**
- ✅ CURRENT_ARCHITECTURE.md (этот файл) → как работает СЕЙЧАС
- ✅ UI_IMPROVEMENTS.md → как улучшить UX

---

## 🎯 Summary

**Текущая архитектура:**
- ✅ OAuth полностью автоматизирован (через plugin.py)
- ✅ Cookies — manual entry (через plugin.py)
- ✅ Все работает
- ⚠️ UX можно улучшить

**Что НЕ нужно:**
- ❌ Новые файлы unified_auth
- ❌ Дублирование логики
- ❌ Over-engineering

**Что НУЖНО:**
- ✅ Улучшить UI (wizard)
- ✅ Добавить validation
- ✅ Показать инструкции
- ✅ Документировать текущую систему

**Next steps:**
1. Улучшить admin-ui с wizard component
2. Добавить validation для cookies
3. Опционально: browser extension для power users
