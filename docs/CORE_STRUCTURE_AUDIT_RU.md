# Аудит структуры ядра (после локальной доочистки)

Дата: 28 марта 2026

## Текущее состояние структуры
- `core` файлов (без `__pycache__`): **76**
- `core` директорий (без `__pycache__`): **17**
- Корень `core` файлов: **16**

## Что удалено в этой итерации
Удалены неиспользуемые shim/legacy файлы и пустые пакеты:
- `core/dependency_resolver.py`
- `core/runtime_context.py`
- `core/execution.py`
- `core/execution_router.py`
- `core/http_registry.py`
- `core/runtime/context.py`
- `core/runtime/module_manager.py`
- `core/runtime/event_bus.py`
- `core/security_init.py`
- `core/security.py`
- `core/errors.py`
- `core/service/service_policy.py`
- `core/capability/security.py`
- `core/trust/__init__.py`
- `core/trust/signature.py`
- `core/trust/trust_store.py`
- `core/trust/verifier.py`
- `core/plugins/manager.py`
- `core/policy/__init__.py`
- `core/policy/engine.py`
- `core/runtime/lifecycle.py`
- `core/runtime/monitoring.py`
- `core/interfaces.py`
- `core/runtime_interface.py`
- `core/plugins/__init__.py`
- `core/base_plugin.py`
- `core/messaging/event_bus.py`
- `core/messaging/__init__.py`
- `core/utils/__init__.py`
- `core/auth/__init__.py`
- `core/contexts/__init__.py`
- `core/contracts/event_bus.py`
- `core/foundation/__init__.py`
- `core/remote/__init__.py`
- `modules/plugins/manager.py` (shim удалён, прямой импорт больше не нужен)

## Что осталось критичным (по границе dumb-kernel)
- Явных критичных нарушений по границе `core ↔ modules` не обнаружено.
- Остался только дальнейший раздел упрощения runtime-композиции (опционально, без срочного риска).

## Рекомендуемый порядок дальнейшей чистки
1. Поразделно сокращать surface `CoreRuntime` (вынести вспомогательные runtime-only функции в app/modules при сохранении контракта).
2. Сохранять правило: любая policy/decision логика — только в `modules`.

## Статус после изменений
- Архитектурный валидатор: `0` нарушений.
- Локальные тесты на изменённые участки: зелёные.
- Мониторинг вынесен из `CoreRuntime` в app-layer (`app/runtime_monitoring.py`); в core оставлена только делегация через `runtime_health_check`/`runtime_metrics_collector`.
- В `core/runtime_module.py` удалены backward-compat ветки ручной сборки контекста; теперь модуль принимает только `RuntimeContext` или runtime с `create_context()`.
- В `core/kernel/base_plugin.py` удалены backward-compat fallback-пути на raw runtime; helper-методы работают через `PluginRuntimeFacade.api`.
- В `core/operations/*` удалены compat fallback-маршруты через глобальный реестр (`get_operation_handler`), оставлен единый handler-registry внутри `OperationManager`.
- В `core/kernel/plugin_infrastructure.py` удалена legacy-дерегистрация handler'ов по имени плагина; очистка выполняется только по capability-id.
- Удалены re-export обёртки в `core/service/__init__.py`, `core/http/__init__.py`, `core/dependency/__init__.py`, `core/module/__init__.py`, `core/exceptions/__init__.py`; импорты в кодовой базе переведены на прямые модули.
- Автозагрузка плагинов вынесена из `core/runtime` в app-level composition (`app/bootstrap`, `main`, `app/console`).
- Из `core/runtime` убраны runtime-specific debug/env/console ветки (`DEBUG_MODE`, `KERNEL DEBUG`, прямой `print` списка плагинов).
- Список `critical_state_prefixes` для startup-hydration вынесен из `core/runtime` в app composition (`app/bootstrap`), core больше не принимает доменное решение о префиксах.
- Из `core/runtime.start()` убрана диагностическая классификация плагинов (blocked/error summary) — оставлен только нейтральный lifecycle.
- Удалён compatibility package `core/plugins`; внутренние импорты переведены на `core.kernel.plugin_*`.
- Удалён compatibility shim `core/base_plugin`; импорты переведены на `core.kernel.base_plugin`.
- Удалён `core/messaging/event_bus` shim; импорты переведены на `core.messaging.inmemory`.
- `RuntimeContext` сделан canonical типом в `core/runtime/runtime_context.py`; alias `LegacyRuntimeContext` удалён.
- Удалены неиспользуемые package-init файлы `core/messaging/__init__.py` и `core/utils/__init__.py`.
- Удалён мёртвый backward-compat alias `HealthMonitor` в `core/health_monitor.py` (используется только `ProviderHealthMonitor`).
