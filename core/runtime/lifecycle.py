"""
Core Runtime Lifecycle Management (D1).

Управление жизненным циклом Core Runtime:
- start() - инициализация модулей и плагинов
- stop() - остановка компонентов
- shutdown() - полное завершение
- run() - оркестрация всего процесса
- _hydrate_critical_state() - загрузка критичных данных в init
- _hydrate_critical_state() - восстановление состояния из persistent storage
"""

from typing import TYPE_CHECKING
import asyncio
import time
import os

from core.logger_helper import info, warning
from core.plugins import PluginState
from core.dependency import RuntimeIntegrityError

if TYPE_CHECKING:
    from core.runtime import CoreRuntime


async def hydrate_critical_state(runtime: "CoreRuntime") -> None:
    """
    Гидратировать критичные данные из persistent storage в StateEngine.
    
    Восстанавливает данные для быстрого доступа при старте без полной загрузки
    всех данных в память. Критичные namespaces:
    - plugins.* : метаданные плагинов
    - agent.* : идентификационные данные агентов
    - ca.* : CA сертификаты
    
    Эта операция выполняется ПЕРЕД запуском модулей, чтобы модули
    могли сразу использовать восстановленное состояние.
    """
    critical_prefixes = ["plugins.", "agent.", "ca.", "runtime.snapshots"]
    
    try:
        # Загружаем все namespaces, которые начинаются с критичных префиксов
        all_namespaces = await runtime.storage.list_namespaces()
        
        for namespace in all_namespaces:
            # Проверяем, является ли namespace критичным
            is_critical = any(namespace.startswith(prefix) for prefix in critical_prefixes)
            
            if is_critical:
                # Итерируем по ключам в namespace и загружаем в StateEngine
                hydrated_count = 0
                try:
                    async for key, value in runtime.storage.iter_namespace(namespace):
                        state_key = f"{namespace}.{key}"
                        await runtime.state_engine.set(state_key, value)
                        hydrated_count += 1
                except Exception as e:
                    # Логируем ошибку, но не останавливаем гидратацию
                    await warning(
                        runtime,
                        f"Ошибка при гидратации namespace '{namespace}': {e}",
                        component="runtime"
                    )
                
                if hydrated_count > 0:
                    await info(
                        runtime,
                        f"Гидратирован namespace '{namespace}' ({hydrated_count} ключей)",
                        component="runtime"
                    )
    except Exception as e:
        # Гидратация - опциональная оптимизация, ошибка не должна блокировать старт
        await warning(
            runtime,
            f"Ошибка гидратации critical state: {e}. Система продолжит работу, но может быть медленнее.",
            component="runtime"
        )


async def start_runtime(runtime: "CoreRuntime") -> None:
    """
    Запустить Core Runtime.
    
    Runtime НЕ стартует, если хоть один REQUIRED RuntimeModule:
    - не зарегистрировался
    - не смог выполниться register()
    - упал в start()
    
    Гарантии:
    - Все REQUIRED модули должны быть зарегистрированы и запущены
    - При ошибке старта REQUIRED модуля runtime останавливается
    - stop_all() вызывается даже при частичном старте
    
    Raises:
        RuntimeError: если REQUIRED модуль не зарегистрирован или не запустился
    """
    if runtime._running:
        return
    
    debug_mode = os.getenv("DEBUG_MODE", "true").lower() != "false"
    
    try:
        # DEBUG KERNEL: Log kernel startup
        if debug_mode:
            await info(runtime, "🔧 KERNEL DEBUG: Starting Core Runtime bootstrap", component="runtime")

        middleware_names = await runtime.event_bus.list_middleware()
        middleware_factory = getattr(runtime, "event_validation_middleware_factory", None)
        if callable(middleware_factory):
            middleware = middleware_factory()
            middleware_name = type(middleware).__name__
            if middleware_name not in middleware_names:
                await runtime.event_bus.add_middleware(middleware)
        
        # Модули регистрируются приложением (bootstrap) через register_module_specs() до вызова start().
        # Проверка, что все REQUIRED модули зарегистрированы (список required задаётся приложением)
        runtime.module_manager.check_required_modules_registered()
        
        # Логирование зарегистрированных модулей
        modules = runtime.module_manager.list_modules()
        if modules:
            await info(runtime, f"Модули зарегистрированы: {modules}", component="runtime")
            if debug_mode:
                await info(runtime, f"🔧 KERNEL DEBUG: Registered {len(modules)} modules", component="runtime")
        
        # P0: Hydrate critical state from persistent storage
        # Восстанавливаем критичные данные из storage в StateEngine для быстрого доступа
        # (plugins metadata, agent identities, CA certificate)
        if debug_mode:
            await info(runtime, "🔧 KERNEL DEBUG: Hydrating critical state from storage", component="runtime")
        await hydrate_critical_state(runtime)

        # Запустить все модули (обязательные домены)
        # start_all() выбросит RuntimeError если REQUIRED модуль упал в start()
        if debug_mode:
            await info(runtime, f"🔧 KERNEL DEBUG: Starting {len(modules)} modules", component="runtime")
        await runtime.module_manager.start_all()
        if modules:
            await info(runtime, f"Модули запущены: {modules}", component="runtime")
            if debug_mode:
                await info(runtime, f"🔧 KERNEL DEBUG: All {len(modules)} modules started successfully", component="runtime")
        
        # P0: Автозагрузка плагинов из папки plugins/ (один раз после модулей)
        # Сканируем папку, в каждой подпапке ищем manifest/plugin.json — если валидный, грузим плагин
        if not await runtime.plugin_manager.list_plugins() and not os.getenv('TEST_MODE'):
            try:
                if debug_mode:
                    await info(runtime, "🔧 KERNEL DEBUG: Auto-loading plugins from plugins/ directory", component="runtime")
                await runtime.plugin_manager.auto_load_plugins()
            except Exception as e:
                await warning(runtime, f"Ошибка автозагрузки плагинов: {e}", component="runtime")

        # Запустить все плагины
        plugins = await runtime.plugin_manager.list_plugins()
        if debug_mode:
            await info(runtime, f"🔧 KERNEL DEBUG: Starting {len(plugins)} plugins", component="runtime")
        await info(runtime, "RUNTIME: about to call plugin_manager.start_all()", component="runtime")
        await runtime.plugin_manager.start_all()
        await info(runtime, "RUNTIME: plugin_manager.start_all() returned", component="runtime")

        # Логируем как список, так и сводку по количеству и состояниям
        if plugins:
            await info(runtime, f"Плагины запущены: {plugins}", component="runtime")
        
        # Сводка: сколько реально запущено / заблокировано / с ошибкой
        if plugins:
            started = []
            blocked = []
            error = []
            for name in plugins:
                state = await runtime.plugin_manager.get_plugin_state(name)
                if state == PluginState.STARTED:
                    started.append(name)
                elif state == PluginState.ERROR:
                    error.append(name)
                else:
                    # LOADED, STOPPED и т.п. считаем "не стартовали до конца"
                    # В отдельную категорию "заблокировано" относим те, у кого есть block_reason
                    if await runtime.plugin_manager.get_plugin_block_reason(name):
                        blocked.append(name)
            await info(
                runtime,
                (
                    "Сводка плагинов: "
                    f"всего={len(plugins)}, "
                    f"запущено={len(started)}, "
                    f"заблокировано={len(blocked)}, "
                    f"с ошибкой={len(error)}"
                ),
                component="runtime",
            )
            if debug_mode:
                await info(
                    runtime,
                    f"🔧 KERNEL DEBUG: Plugins started={len(started)} blocked={len(blocked)} error={len(error)}",
                    component="runtime"
                )
        # Also print plugin list to stdout for quick visibility in console
        try:
            if plugins:
                print("[Runtime] Плагины:")
                for name in plugins:
                    state = await runtime.plugin_manager.get_plugin_state(name)
                    block = await runtime.plugin_manager.get_plugin_block_reason(name)
                    state_str = state.value if state is not None else "unknown"
                    if block:
                        print(f"  - {name}: {state_str} (blocked: {block})")
                    else:
                        print(f"  - {name}: {state_str}")
        except Exception:
            pass
        
        # Проверить что система в консистентном состоянии (все dependencies удовлетворены)
        integrity_errors = runtime.dependency_resolver.validate_runtime_integrity()
        if integrity_errors:
            raise RuntimeIntegrityError(integrity_errors)
        
        # Установить состояние runtime
        await runtime.state_engine.set("runtime.status", "running")
        runtime._running = True
        runtime._start_time = time.time()
        
        # DEBUG KERNEL: Log successful startup
        if debug_mode:
            uptime_ms = int((time.time() - runtime._start_time) * 1000)
            await info(
                runtime,
                f"✅ KERNEL DEBUG: Core Runtime started successfully in {uptime_ms}ms",
                component="runtime"
            )

    except Exception as e:
        # При любой ошибке старта останавливаем все модули
        # Гарантия: stop_all вызывается даже при частичном старте
        if debug_mode:
            await warning(
                runtime,
                f"❌ KERNEL DEBUG: Core Runtime startup failed: {type(e).__name__}: {str(e)}",
                component="runtime"
            )
        
        try:
            await runtime.module_manager.stop_all()
        except Exception as stop_error:
            # Логируем ошибку остановки, но не маскируем исходную ошибку
            await warning(runtime, f"Ошибка при остановке модулей после ошибки старта: {stop_error}", component="runtime")
        
        # Пробрасываем исходную ошибку
        raise


async def stop_runtime(runtime: "CoreRuntime") -> None:
    """
    Остановить Core Runtime.
    
    - сигналит HTTP серверу (should_exit)
    - останавливает все плагины
    - очищает состояние
    - закрывает storage
    
    Использует timeout из конфига (если доступен) для защиты от зависания.
    """
    if not runtime._running:
        return
    
    debug_mode = os.getenv("DEBUG_MODE", "true").lower() != "false"
    
    if debug_mode:
        await info(runtime, "🔧 KERNEL DEBUG: Stopping Core Runtime", component="runtime")
    
    # Получаем timeout из конфига или используем значение по умолчанию
    timeout = 10
    if runtime._config is not None:
        timeout = getattr(runtime._config, "shutdown_timeout", 10)
    
    async def _stop_internal() -> None:
        """Внутренняя функция остановки."""
        if debug_mode:
            await info(runtime, "🔧 KERNEL DEBUG: Stopping all plugins", component="runtime")
        # Остановить все плагины
        await runtime.plugin_manager.stop_all()
        
        if debug_mode:
            await info(runtime, "🔧 KERNEL DEBUG: Stopping all modules", component="runtime")
        # Остановить все модули
        await runtime.module_manager.stop_all()
        
        if debug_mode:
            await info(runtime, "🔧 KERNEL DEBUG: Closing storage", component="runtime")
        # Закрыть storage
        await runtime.storage.close()
        
        # Установить состояние runtime
        await runtime.state_engine.set("runtime.status", "stopped")
        runtime._running = False
        
        if debug_mode:
            await info(runtime, "✅ KERNEL DEBUG: Core Runtime stopped successfully", component="runtime")
    
    try:
        await asyncio.wait_for(_stop_internal(), timeout=timeout)
    except asyncio.TimeoutError:
        # Логируем timeout и принудительно завершаем
        try:
            await warning(
                runtime,
                f"Timeout ({timeout}s) при остановке runtime, принудительное завершение",
                component="runtime"
            )
        except Exception:
            pass
        # Принудительно устанавливаем состояние остановки
        runtime._running = False
        raise


async def shutdown_runtime(runtime: "CoreRuntime") -> None:
    """
    Полное завершение работы Runtime.
    
    - останавливает runtime
    - очищает все компоненты
    """
    debug_mode = os.getenv("DEBUG_MODE", "true").lower() != "false"
    
    if debug_mode:
        await info(runtime, "🔧 KERNEL DEBUG: Initiating full shutdown", component="runtime")
    
    await stop_runtime(runtime)
    
    if debug_mode:
        await info(runtime, "🔧 KERNEL DEBUG: Clearing modules", component="runtime")
    # Очистить модули
    runtime.module_manager.clear()

    if debug_mode:
        await info(runtime, "🔧 KERNEL DEBUG: Clearing event bus, services, state", component="runtime")
    # Очистить компоненты
    await runtime.event_bus.clear()
    await runtime.service_registry.clear()
    await runtime.state_engine.clear()
    
    if debug_mode:
        await info(runtime, "✅ KERNEL DEBUG: Full shutdown complete", component="runtime")
