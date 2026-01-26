# Yandex OAuth + Quasar: Единый Login Entrypoint (Embedded WebView)

Цель: один логин на yandex.ru → backend получает одновременно:
- OAuth token (для публичных API Яндекса)
- Session cookies (Session_id, yandexuid) для Quasar WebSocket

Ключевое ограничение: cookies нельзя надёжно и легально получать через обычный браузерный redirect. Нужен контролируемый Embedded WebView, у которого мы имеем доступ к внутреннему cookie-store.

## Архитектура (схема)

[Плагины]
- oauth_yandex (существующий): хранит конфиг, обмен кода, refresh, валидация
- yandex_smart_home: использует cookies для Quasar WS

[Новые модули в oauth_yandex]
- YandexLoginService — единый entrypoint процесса логина
- EmbeddedWebViewLogin — абстракция контролируемого UI (реализация PyQtWebViewLogin)
- OAuthTokenManager — обмен `code` → `tokens` через существующие сервисы
- SessionCookieManager — сохранение cookies в storage (`yandex/cookies`)
- YandexAccountSession — агрегированное состояние и атомарная запись токены+cookies

Потоки данных:
- UI вызывает `/yandex/login/start` → backend запускает Embedded WebView
- Пользователь логинится в yandex.ru → WebView перехватывает redirect с `code` и читает cookies
- Backend через `oauth_yandex.exchange_code` получает токены
- Backend атомарно сохраняет токены+cookies → публикует событие `yandex.login.linked`
- `/yandex/login/status` возвращает агрегированный статус `linked | needs_relogin | invalid | in_progress | unsupported`

## Ответственности модулей
- YandexLoginService: оркестрация старт/статус; выбор реализации WebView; атомарная запись; статусы
- EmbeddedWebViewLogin: открыть `authorize_url`, перехватить `code`, получить cookies; вернуть `(code, cookies)`
- OAuthTokenManager: использовать `oauth_yandex.exchange_code` и загрузить сохранённые токены
- SessionCookieManager: запись/чтение cookies под `yandex/cookies`
- YandexAccountSession: объединённый статус; `save_atomic(runtime, tokens, cookies)` + событие `yandex.login.linked`

## Sequence: Единый Login Flow

```
User        Admin UI         Backend (YandexLoginService)    WebView (Embedded)
 |             |                          |                       |
 |  POST /yandex/login/start             |                       |
 |-------------------------------------->| start()               |
 |             |                          |  open authorize_url   |
 |             |                          |---------------------->|
 |             |                          |   user login          |
 |             |                          |<----------------------|
 |             |                          |   redirect -> code    |
 |             |                          |   read cookies        |
 |             |                          |  exchange_code(code)  |
 |             |                          |----------------------> (oauth_yandex)
 |             |                          |   tokens saved        |
 |             |                          |<----------------------|
 |             |                          |  save cookies         |
 |             |                          |  save_atomic          |
 |             |                          |  publish linked event |
 |  POST /yandex/login/status            |                       |
 |-------------------------------------->| status() = linked      |
```

## API контракт

Новые:
- POST `/yandex/login/start`
  - Запускает контролируемый Embedded WebView
  - Ответ: `{ state: "in_progress" }` | `{ state: "unsupported", reason }` | `{ state: "linked", expires_at? }` (при синхронной реализации)
- POST `/yandex/login/status`
  - Возвращает статус: `{ state: "linked" | "needs_relogin" | "invalid" | "in_progress" | "unsupported", expires_at?, reason? }`

Обновлённые/сохранённые:
- POST `/oauth/yandex/configure` — настройка client_id/client_secret/redirect_uri
- GET `/oauth/yandex/status` — статус OAuth
- POST `/oauth/yandex/exchange-code` — обмен кода (используется внутренне YandexLoginService)
- POST `/oauth/yandex/cookies` — запись cookies (используется внутренне YandexLoginService)
- GET `/oauth/yandex/cookies` — чтение cookies (диагностика)

Удалён из HTTP (deprecated):
- GET `/oauth/yandex/authorize-url` — остаётся как внутренний сервис `oauth_yandex.get_authorize_url` для обратной совместимости, но не публикуется как HTTP.

## Backward Compatibility
- Старый OAuth-only flow сохраняется на уровне сервисов (`get_authorize_url`, `exchange_code`) и `/oauth/yandex/exchange-code` эндпоинта
- UI должен мигрировать на `/yandex/login/start` + `/yandex/login/status`
- Маршрут миграции: сначала включить новый flow; затем удалить использование `/oauth/yandex/authorize-url`

## Жизненный цикл сессии
- Refresh OAuth: остаётся в `oauth_yandex.get_access_token()` с блокировкой и корректной семантикой ошибок
- Invalid cookies: `yandex/login/status` вернёт `needs_relogin` с `reason= cookies_missing` или по 401 от Quasar
- Re-login trigger: UI вызывает `/yandex/login/start` повторно, закрывая текущую сессию
- Статусы:
  - `linked`: есть валидный access_token и cookies (Session_id, yandexuid)
  - `needs_relogin`: истёк токен или отсутствуют cookies
  - `invalid`: нет конфигурации или аккаунт не связан
  - `in_progress`: идёт процесс логина в Embedded WebView
  - `unsupported`: нет доступной реализации WebView в окружении

## Почему cookies нельзя получать через redirect
- Стандартный OAuth redirect работает в внешнем браузере; серверу недоступен браузерный cookie-store домена yandex.ru
- Попытки передавать cookies через query/fragment недопустимы и небезопасны
- Бекенд не может законно прочитать чужой браузерный cookie jar — это нарушает модель безопасности

## Почему Embedded WebView — единственный корректный путь
- Контролируемый контейнер UI (WebView) даёт управляемый cookie-store и события навигации
- Мы перехватываем redirect внутри контейнера и извлекаем `code` без выхода в внешний браузер
- Мы читаем cookies доменов Яндекса из WebView и безопасно сохраняем их на backend

## Почему OAuth и Quasar разделены внутри, но объединены в login
- Это два разных мира авторизации: публичный OAuth API и внутренний session-based API
- Внутри плагина храним токены и cookies отдельно, с разными менеджерами
- На уровне UX login объединён: один вход создаёт оба представления идентичности и даёт лучший DX

## Реализация WebView
- Рекомендуемая реализация: PyQt6 + QtWebEngine (локальный Desktop UI)
- Альтернативы: CEF Python, Kivy с WebView (платформенные ограничения)
- В текущем репозитории добавлен каркас (`plugins/oauth_yandex/login_flow.py`), реализацию PyQtWebViewLogin нужно доработать (создать окно, профиль, подписки на events, чтение cookieStore, отсылка результатов в сервис)

## Примечания по безопасности
- Cookies — чувствительные, хранить только в зашифрованном storage (по возможности)
- Не пересылать cookies в сторонние сервисы, использовать только локально для Quasar
- Ограничить время жизни сессии и предусмотреть принудительный logout
