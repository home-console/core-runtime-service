"""
PluginLifecycle - управление lifecycle плагинов.

Отвечает за:
- Загрузку плагинов (load_plugin)
- Запуск плагинов (start_plugin, start_all)
- Остановку плагинов (stop_plugin, stop_all)
- Выгрузку плагинов (unload_plugin)
- Перезагрузку плагинов (reload_plugin)

Делегирует:
- PluginStorageManager — сохранение метаданных
- PluginOrchestrationManager — управление контейнерами
- PluginInfrastructureCoordinator — capabilities, operations, integrations
"""

import sys
from pathlib import Path
from typing import Any, Dict, Optional

import asyncio

from core.kernel.base_plugin import BasePlugin
from core.kernel.plugin_loader import PluginManifestLoader
from core.kernel.plugin_infrastructure import PluginInfrastructureCoordinator
from core.kernel.plugin_orchestration_manager import PluginOrchestrationManager
from core.kernel.plugin_registry import PluginRegistry, PluginState
from core.kernel.plugin_storage_manager import PluginStorageManager
from core.kernel.plugin_sandbox import PluginSandbox
from core.kernel.plugin_supervisor import PluginSupervisor, RestartPolicy, PluginStatus
from core.observability.logger_helper import info, warning
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS
import logging
logger = logging.getLogger(__name__)


class PluginLifecycleManager:
    """
    Менеджер lifecycle плагинов.

    Управляет загрузкой, запуском, остановкой и выгрузкой плагинов.
    Делегирует хранение и оркестрацию специализированным компонентам.
    """

    def __init__(
        self,
        registry: PluginRegistry,
        runtime: Optional[Any] = None,
        capability_registry: Optional[Any] = None,
    ):
        """
        Инициализация менеджера lifecycle.

        Args:
            registry: реестр плагинов
            runtime: экземпляр CoreRuntime
            capability_registry: реестр capabilities (опционально, для регистрации capabilities плагинов)
        """
        self._registry = registry
        self._runtime = runtime
        self._capability_registry = capability_registry
        self._supervisor = PluginSupervisor()

        async def _mark_plugin_failed(name: str, exc: Exception) -> None:
            # "Degraded" semantics mapped to registry ERROR (plugin stays registered).
            await self._registry.set_plugin_state(name, PluginState.ERROR)

        self._supervisor.on_plugin_failed(_mark_plugin_failed)

        # Делегирование специализированным компонентам (SRP)
        self._storage_manager = PluginStorageManager(runtime)
        self._orchestration_manager = PluginOrchestrationManager(
            runtime,
            orchestration_service=getattr(runtime, "orchestration_service", None)
            if runtime is not None
            else None,
        )

        # Инфраструктурный координатор: capabilities, operations, integrations
        operations = (
            getattr(runtime, "operations", None) if runtime is not None else None
        )
        integrations = (
            getattr(runtime, "integrations", None) if runtime is not None else None
        )
        self._infra = PluginInfrastructureCoordinator(
            capability_registry=capability_registry,
            operations=operations,
            integrations=integrations,
        )

    def _resolve_plugins_dir(self) -> Optional[Path]:
        """Получить plugins_dir из runtime config. Возвращает None если не сконфигурировано."""
        config = getattr(self._runtime, "_config", None)
        plugins_dir_str = getattr(config, "plugins_dir", None) if config is not None else None
        if not plugins_dir_str:
            return None
        return Path(plugins_dir_str).expanduser()

    def _manifest_skills_for_plugin(self, plugin_name: str) -> list:
        plugins_dir = self._resolve_plugins_dir()
        if plugins_dir is None:
            return []
        plugin_path = PluginManifestLoader.find_plugin_directory(plugins_dir, plugin_name)
        if plugin_path is None:
            return []
        data = PluginManifestLoader.load_manifest(plugin_path, strict=False)
        if not data or not isinstance(data, dict):
            return []
        raw = data.get("skills")
        if not isinstance(raw, list):
            return []
        return [s for s in raw if isinstance(s, dict)]

    async def _publish_plugin_loaded(self, plugin_name: str, plugin_version: str) -> None:
        bus = getattr(self._runtime, "event_bus", None) if self._runtime is not None else None
        if bus is None:
            return
        await bus.publish(
            "internal.plugin.loaded",
            {
                "plugin_name": plugin_name,
                "plugin_version": plugin_version,
                "skills": self._manifest_skills_for_plugin(plugin_name),
            },
        )

    async def _publish_plugin_unloaded(self, plugin_name: str) -> None:
        bus = getattr(self._runtime, "event_bus", None) if self._runtime is not None else None
        if bus is None:
            return
        await bus.publish(
            "internal.plugin.unloaded",
            {"plugin_name": plugin_name},
        )

    async def load_plugin(self, plugin: BasePlugin) -> None:
        """
        Загрузить плагин.

        Выполняет:
        1. Создание изолированного контекста (sandbox)
        2. Вызов plugin.on_load()
        3. Регистрацию в реестре
        4. Регистрацию capabilities

        Args:
            plugin: экземпляр плагина

        Raises:
            ValueError: если плагин уже загружен или отсутствуют зависимости
        """
        # Получить имя плагина заранее для error handling
        metadata = plugin.metadata
        plugin_name = metadata.name

        # Проверка на дубликат
        if await self._registry.has_plugin(plugin_name):
            raise ValueError(f"Плагин '{plugin_name}' уже загружен")

        # Установим ссылку на runtime у плагина перед вызовом on_load
        try:
            # Создаём изолированный контекст
            PluginSandbox.create_isolation_context(plugin, self._runtime, plugin_name)

            # Вызов on_load может обновить metadata (например, remote proxy)
            await plugin.on_load()

            # Заново прочитаем metadata после on_load в случае, если она изменилась
            metadata = plugin.metadata
            plugin_name = metadata.name

            # Проверка зависимостей
            deps = self._resolve_plugin_dependencies(plugin, metadata)
            if deps:
                for dep_name in deps:
                    if not await self._registry.has_plugin(dep_name):
                        raise ValueError(
                            f"Плагин '{plugin_name}' требует плагин '{dep_name}', "
                            f"но он не загружен"
                        )

            # Регистрируем в реестре
            await self._registry.register(plugin_name, plugin, PluginState.LOADED)

            # Сохраняем метаданные плагина в persistent storage
            # Это позволяет восстановить информацию о плагине после выгрузки
            await self._storage_manager.save_plugin_metadata(plugin_name, metadata)

            # CapabilityRegistry / инфраструктура: регистрация capabilities вынесена в координатор
            await self._infra.on_plugin_loaded(plugin)
            await self._publish_plugin_loaded(
                plugin_name,
                str(getattr(metadata, "version", None) or "0.0.0"),
            )
        except asyncio.CancelledError:
            raise
        except BEST_EFFORT_BACKGROUND_ERRORS:
            await self._registry.set_plugin_state(plugin_name, PluginState.ERROR)
            logger.exception("plugin_lifecycle.load_plugin: failed for '%s'", plugin_name)
            raise

    async def start_plugin(
        self,
        plugin_name: str,
        _start_stack: Optional[set[str]] = None,
        *,
        _propagate_errors: bool = True,
    ) -> None:
        """
        Запустить плагин.

        Если у плагина есть требуемые capabilities и хотя бы одна не имеет provider,
        плагин НЕ стартует; состояние остаётся LOADED, причина в get_plugin_block_reason().

        Args:
            plugin_name: имя плагина

        Raises:
            ValueError: если плагин не найден или не загружен
        """
        start_stack = _start_stack or set()
        if plugin_name in start_stack:
            cycle = " -> ".join([*start_stack, plugin_name])
            raise RuntimeError(f"Циклический запуск зависимостей плагинов: {cycle}")
        start_stack.add(plugin_name)

        plugin = await self._registry.get_plugin(plugin_name)
        if plugin is None:
            start_stack.discard(plugin_name)
            raise ValueError(f"Плагин '{plugin_name}' не найден")

        state = await self._registry.get_plugin_state(plugin_name)
        if state == PluginState.STARTED:
            start_stack.discard(plugin_name)
            return  # Уже запущен

        metadata = plugin.metadata
        deps = self._resolve_plugin_dependencies(plugin, metadata)
        if deps:
            missing_dependencies: list[str] = []
            not_ready_dependencies: list[Dict[str, Any]] = []

            for dep_name in deps:
                if not await self._registry.has_plugin(dep_name):
                    missing_dependencies.append(dep_name)
                    continue
                dep_state = await self._registry.get_plugin_state(dep_name)
                if dep_state != PluginState.STARTED:
                    try:
                        await self.start_plugin(
                            dep_name, start_stack, _propagate_errors=False
                        )
                    except (RuntimeError, ValueError, AttributeError, KeyError) as e:
                        logger.warning(
                            "plugin_lifecycle.start_plugin: dependency start failed: %s",
                            e,
                            exc_info=True,
                        )
                        not_ready_dependencies.append(
                            {
                                "dependency": dep_name,
                                "state": dep_state.value if dep_state else None,
                                "error": str(e),
                            }
                        )
                        continue
                    except BEST_EFFORT_BACKGROUND_ERRORS as e:
                        logger.warning(
                            "plugin_lifecycle.start_plugin: unexpected dependency error: %s",
                            e,
                            exc_info=True,
                        )
                        not_ready_dependencies.append(
                            {
                                "dependency": dep_name,
                                "state": dep_state.value if dep_state else None,
                                "error": str(e),
                            }
                        )
                        continue

                    dep_state = await self._registry.get_plugin_state(dep_name)
                    if dep_state != PluginState.STARTED:
                        not_ready_dependencies.append(
                            {
                                "dependency": dep_name,
                                "state": dep_state.value if dep_state else None,
                            }
                        )

            if missing_dependencies:
                await self._registry.set_plugin_block_reason(
                    plugin_name, {"missing_dependencies": missing_dependencies}
                )
                start_stack.discard(plugin_name)
                return

            if not_ready_dependencies:
                await self._registry.set_plugin_block_reason(
                    plugin_name,
                    {"dependency_not_ready": not_ready_dependencies},
                )
                start_stack.discard(plugin_name)
                return

        # Проверка required capabilities: все должны иметь хотя бы одного provider
        await self._registry.clear_plugin_block_reason(plugin_name)
        if self._capability_registry is not None:
            reg = self._capability_registry
            if self._runtime:
                await info(
                    self._runtime,
                    f"RUNTIME: validating capabilities for plugin {plugin_name}",
                    component="runtime",
                )
            ok, missing = await reg.validate_plugin_requirements(plugin_name)
            if self._runtime:
                await info(
                    self._runtime,
                    f"RUNTIME: capabilities validated for {plugin_name} ok={ok}",
                    component="runtime",
                )
            if not ok:
                await self._registry.set_plugin_block_reason(
                    plugin_name, {"missing_capabilities": missing}
                )
                start_stack.discard(plugin_name)
                return  # Плагин не стартуем — управляемое состояние (blocked), не исключение

        try:
            # Fault isolation with deterministic semantics:
            # on_start() is an init hook; after await it must have executed (tests rely on it).
            handle = await self._supervisor.run_supervised(
                plugin_name=plugin_name,
                coro=plugin.on_start(),
                restart_policy=RestartPolicy.NEVER,
            )
            # If plugin crashed during on_start, supervisor marks it DEGRADED.
            # In that case do NOT mark plugin as STARTED.
            if handle.status == PluginStatus.DEGRADED:
                await self._registry.set_plugin_state(plugin_name, PluginState.ERROR)
                if _propagate_errors:
                    raise RuntimeError(f"Ошибка запуска плагина '{plugin_name}'")
                return

            await self._registry.set_plugin_state(plugin_name, PluginState.STARTED)
        except asyncio.CancelledError:
            raise
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            await self._registry.set_plugin_state(plugin_name, PluginState.ERROR)
            start_stack.discard(plugin_name)
            logger.exception("plugin_lifecycle.start_plugin: on_start failed for '%s'", plugin_name)
            # Runtime must stay alive, but caller may want an explicit error.
            if _propagate_errors:
                raise RuntimeError(f"Ошибка запуска плагина '{plugin_name}'") from e
            return
        finally:
            start_stack.discard(plugin_name)

    def _resolve_plugin_dependencies(self, plugin: BasePlugin, metadata: Any) -> list[str]:
        """Resolve plugin dependencies from formal plugin context or metadata fallback."""
        ctx = getattr(plugin, "_plugin_context", None)
        if ctx is not None:
            deps_obj = getattr(ctx, "dependencies", None)
            deps = getattr(deps_obj, "dependencies", None)
            if isinstance(deps, list):
                return [d for d in deps if isinstance(d, str) and d.strip()]

        deps = getattr(metadata, "dependencies", []) or []
        if isinstance(deps, list):
            return [d for d in deps if isinstance(d, str) and d.strip()]
        return []

    async def stop_plugin(self, plugin_name: str) -> None:
        """
        Остановить плагин.

        Для плагинов с execution_mode="container" также останавливает Docker контейнер.

        Args:
            plugin_name: имя плагина

        Raises:
            ValueError: если плагин не найден
        """
        plugin = await self._registry.get_plugin(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")

        state = await self._registry.get_plugin_state(plugin_name)
        if state != PluginState.STARTED:
            return  # Не запущен

        try:
            metadata = plugin.metadata
            await self._orchestration_manager.stop_plugin_runtime(plugin_name, metadata)

            # Stop supervised task first (if any), then call plugin shutdown hook.
            await self._supervisor.stop_plugin(plugin_name)
            await plugin.on_stop()
            await self._registry.set_plugin_state(plugin_name, PluginState.STOPPED)
        except asyncio.CancelledError:
            raise
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            await self._registry.set_plugin_state(plugin_name, PluginState.ERROR)
            logger.exception("plugin_lifecycle.stop_plugin: failed for '%s'", plugin_name)
            raise RuntimeError(f"Ошибка остановки плагина '{plugin_name}': {e}") from e

    async def unload_plugin(self, plugin_name: str) -> None:
        """
        Выгрузить плагин.

        Args:
            plugin_name: имя плагина

        Raises:
            ValueError: если плагин не найден
        """
        plugin = await self._registry.get_plugin(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")

        # Сначала остановить, если запущен
        state = await self._registry.get_plugin_state(plugin_name)
        if state == PluginState.STARTED:
            await self.stop_plugin(plugin_name)

        try:
            await plugin.on_unload()
            await self._registry.clear_plugin_block_reason(plugin_name)

            metadata = plugin.metadata
            await self._orchestration_manager.remove_plugin_runtime(plugin_name, metadata)

            await self._publish_plugin_unloaded(plugin_name)

            # Инфраструктурная очистка (capabilities, handlers, integrations)
            await self._infra.on_plugin_unloaded(plugin)

            # Помечаем плагин как выгруженный в storage, но НЕ удаляем метаданные
            # Это позволяет системе знать, что плагин был установлен
            await self._storage_manager.mark_plugin_unloaded(plugin_name)

            # Удаляем из реестра плагинов (in-memory)
            await self._registry.unregister(plugin_name)

            # P2.6: Clean up dynamically loaded modules from sys.modules to avoid
            # stale references on hot-reload and prevent memory leaks.
            _cleanup_plugin_modules(plugin_name)
        except asyncio.CancelledError:
            raise
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            await self._registry.set_plugin_state(plugin_name, PluginState.ERROR)
            logger.exception("plugin_lifecycle.unload_plugin: failed for '%s'", plugin_name)
            raise RuntimeError(f"Ошибка выгрузки плагина '{plugin_name}': {e}") from e

    async def reload_plugin(
        self, plugin_name: str, load_plugin_from_manifest_func: Optional[Any] = None
    ) -> None:
        """
        Перезагрузить плагин (hot-reload).

        Выполняет последовательность: stop → unload → load → start.
        Плагин должен быть загружен из manifest для успешной перезагрузки.

        Args:
            plugin_name: имя плагина для перезагрузки
            load_plugin_from_manifest_func: функция для загрузки плагина из манифеста

        Raises:
            ValueError: если плагин не найден или не может быть перезагружен
            RuntimeError: если перезагрузка не удалась
        """
        if not await self._registry.has_plugin(plugin_name):
            raise ValueError(f"Плагин '{plugin_name}' не найден для перезагрузки")

        # Сохраняем информацию о состоянии перед перезагрузкой
        was_started = (
            await self._registry.get_plugin_state(plugin_name) == PluginState.STARTED
        )

        # Получаем plugins_dir из конфига runtime — хрупкие path-эвристики не используем.
        plugins_dir = self._resolve_plugins_dir()
        if plugins_dir is None:
            raise ValueError(
                f"Не удалось перезагрузить плагин '{plugin_name}': "
                f"plugins_dir не задан в конфигурации runtime (Config.plugins_dir)."
            )
        plugin_dir = PluginManifestLoader.find_plugin_directory(plugins_dir, plugin_name)
        if plugin_dir is None:
            raise ValueError(
                f"Не удалось найти каталог плагина '{plugin_name}' под {plugins_dir}"
            )

        if not plugin_dir.is_dir():
            raise ValueError(
                f"Не удалось найти директорию плагина '{plugin_name}' для перезагрузки "
                f"(ожидался путь: {plugin_dir})"
            )

        # Загружаем манифест
        manifest = PluginManifestLoader.load_manifest(plugin_dir)
        if not manifest:
            raise ValueError(f"Не удалось найти manifest для плагина '{plugin_name}'")

        # Выгружаем плагин
        await self.unload_plugin(plugin_name)

        # Загружаем плагин заново из манифеста (если функция предоставлена)
        if load_plugin_from_manifest_func:
            success = await load_plugin_from_manifest_func(manifest, plugin_dir)
            if not success:
                raise RuntimeError(
                    f"Не удалось загрузить плагин '{plugin_name}' после перезагрузки"
                )

        # Запускаем плагин, если он был запущен до перезагрузки
        if was_started:
            await self.start_plugin(plugin_name)

    async def start_all(self) -> None:
        """Запустить все загруженные плагины."""
        states = await self._registry.get_all_states()
        if self._runtime:
            await info(
                self._runtime,
                "RUNTIME: plugin_manager.start_all() entered",
                component="runtime",
            )
        for plugin_name, state in states.items():
            if state == PluginState.LOADED:
                if self._runtime:
                    await info(
                        self._runtime,
                        f"RUNTIME: starting plugin {plugin_name}",
                        component="runtime",
                    )
                await self.start_plugin(plugin_name)
                if self._runtime:
                    await info(
                        self._runtime,
                        f"RUNTIME: plugin {plugin_name} started",
                        component="runtime",
                    )

    async def stop_all(self) -> None:
        """Остановить все запущенные плагины."""
        states = await self._registry.get_all_states()
        for plugin_name, state in states.items():
            if state == PluginState.STARTED:
                await self.stop_plugin(plugin_name)

        # Best-effort: ensure any remaining supervised tasks are cancelled.
        await self._supervisor.stop_all(timeout=10.0)


def _cleanup_plugin_modules(plugin_name: str) -> None:
    """Remove dynamically loaded plugin modules from sys.modules (P2.6)."""
    prefix = f"hc_dynamic_plugins.{plugin_name}."
    exact = f"hc_dynamic_plugins.{plugin_name}"
    to_remove = [
        k for k in list(sys.modules)
        if k == exact or k.startswith(prefix)
    ]
    for key in to_remove:
        del sys.modules[key]
