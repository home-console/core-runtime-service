# Плагин без UI (API-only)

Режим **[2]** из политики UI (`claude-analytics.md` §1.4, §7.3).

Плагин — Python в sandbox ядра. Веб **не** загружает JS из архива. Пользователь работает через существующие страницы платформы и HTTP API.

## Когда выбирать API-only

- Данные укладываются в **устройства**, **интеграции**, **автоматизации**, **метрики**.
- Нужны только **сервисы** и **события** для других модулей или CLI.
- Действия удобно отдать через **skills** (`hc skill invoke`), без отдельной вкладки.

Секцию `ui` в `plugin.json` можно **не указывать**.

## Минимальный `plugin.json`

```json
{
  "name": "my_integration",
  "version": "1.0.0",
  "description": "Краткое описание",
  "author": "Your Team",
  "class_path": "plugins.my_integration.plugin.MyPlugin",
  "namespace": "my_integration",
  "allowed_services": ["devices.*", "state.*"],
  "provides_services": ["my_integration.status"],
  "provides_events": ["my_integration.updated"]
}
```

## Интеграция (опционально)

Если плагин — подключение внешней системы:

```json
{
  "is_integration": true,
  "integration_flags": ["connect", "disconnect"]
}
```

Состояние видно в web: **Integrations** (`GET /api/v1/admin/inspector/integrations`).

## Skills (опционально)

Декларации для `modules/skills` (не путать с `modules/agent`):

```json
{
  "skills": [
    {
      "name": "sync-now",
      "intent": "Force sync",
      "description": "Pull latest state",
      "service": "my_integration.skill.sync_now"
    }
  ]
}
```

- Реестр заполняется при **load** плагина и при **старте ядра** (scan `plugins/*/plugin.json`).
- CLI: `hc skill list`, `hc skill get my_integration.sync-now`, `hc skill invoke ...`
- API: `GET /api/v1/skills`, `POST /api/v1/skills/{id}/invoke` (scopes `admin.read` / `admin.write`).

Плагин может вызвать skill двумя способами: **зарегистрировать сервис** через `register_service` (явный `service` или конвенция `{plugin}.skill.{name}`), либо **без регистрации (SK7)** — ядро вызовет метод на экземпляре загруженного и **STARTED** плагина по dotted-пути после префикса `{plugin}.` (например `my_integration.skill.sync_now` → `skill.sync_now` на плагине, с fallback `skill_sync_now`). Имя сервиса должно проходить `service_allowed_for_plugin_invoke` (префикс `{plugin}.*` или запись в манифесте).

## Жизненный цикл

1. Собрать zip с `plugin.json` + код.
2. Опубликовать в marketplace (валидация манифеста на publish).
3. `hc marketplace install <name>` / install-archive.
4. `hc plugin load <name>` → `hc plugin start <name>` (или auto-load).
5. Проверка: Admin → Plugins, `hc skill list`, inspector `GET .../plugins/{name}`.

## Чего не делать в API-only

- Не полагаться на `ui.pages[].module` — web **не** исполняет эти файлы.
- Не ждать `cli.subcommands` из архива в `hc` — вне скоупа; используйте API и `hc skill`.
- Не хранить секреты в манифесте; используйте `SecretStore` / credentials module.

## Дальше

- Нужна вкладка настроек без своего React → **[1] server-driven UI** — см. `claude-analytics.md` §7.3, demo `docs/examples/ui_demo_plugin`.
- Демо-плагин с `ui.pages` (settings + metric): `docs/examples/ui_demo_plugin/` — скопировать в `plugins/ui_demo` и load/start.
- Config helper: `from sdk.config import register_ui_config_services` в `on_load`.
- SDK: `core-runtime-service/sdk/README.md`, пример `docs/examples/example_plugin/`.
