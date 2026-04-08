"""
PluginManager - управление lifecycle плагинов (Facade).

Делегирует работу специализированным компонентам из core.kernel:
- PluginRegistry: хранение и query плагинов
- PluginLifecycleManager: lifecycle операции
- PluginManifestLoader: загрузка манифестов
- PluginSandbox: изоляция плагинов

КРИТИЧЕСКИЕ ПРАВИЛА:
- Плагины загружаются ТОЛЬКО через manifest (plugin.json или manifest.json)
- Без manifest плагин НЕ загружается
- Зависимости разрешаются автоматически через топологическую сортировку

Подробный контракт: docs/08-PLUGIN-CONTRACT.md
"""

from pathlib import Path
from typing import Optional, TYPE_CHECKING, Callable, Awaitable, Dict, Any

from core.kernel.base_plugin import BasePlugin
from core.observability.logger_helper import warning
from core.kernel.plugin_registry import PluginRegistry, PluginState
from core.kernel.plugin_lifecycle import PluginLifecycleManager
from core.kernel.plugin_loader import PluginManifestLoader
from core.kernel.integration_registry import IntegrationFlag
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS

if TYPE_CHECKING:
    from core.runtime.runtime import CoreRuntime
import logging
logger = logging.getLogger(__name__)


class PluginManager:
    """
    Facade для управления lifecycle плагинов.

    Делегирует работу специализированным компонентам:
    - PluginRegistry: хранение и query
    - PluginLifecycleManager: lifecycle операции
    - PluginManifestLoader: загрузка манифестов
    """

    def __init__(
        self,
        runtime: Optional["CoreRuntime"] = None,
        capability_registry: Optional[Any] = None,
    ):
        self._runtime = runtime
        self._capability_registry = capability_registry
        self._registry = PluginRegistry()
        self._lifecycle = PluginLifecycleManager(
            self._registry,
            runtime,
            capability_registry=capability_registry,
        )

    @property
    def _plugin_lock(self):
        return self._registry._plugin_lock

    @property
    def _plugins(self):
        return self._registry._plugins

    @property
    def _states(self):
        return self._registry._states
    
    def _resolve_plugins_dir(self) -> Optional[Path]:
        """Получить plugins_dir из runtime config. Возвращает None если не сконфигурировано."""
        config = getattr(self._runtime, "_config", None)
        plugins_dir_str = getattr(config, "plugins_dir", None) if config is not None else None
        if not plugins_dir_str:
            return None
        return Path(plugins_dir_str).expanduser()
    async def load_plugin(self, plugin: BasePlugin) -> None:
        await self._lifecycle.load_plugin(plugin)
    
    async def start_plugin(self, plugin_name: str) -> None:
        await self._lifecycle.start_plugin(plugin_name)
    
    async def stop_plugin(self, plugin_name: str) -> None:
        await self._lifecycle.stop_plugin(plugin_name)
    
    async def unload_plugin(self, plugin_name: str) -> None:
        await self._lifecycle.unload_plugin(plugin_name)
    
    async def reload_plugin(self, plugin_name: str) -> None:
        async def load_from_manifest(manifest: Dict[str, Any], plugin_dir: Path) -> bool:
            return await PluginManifestLoader.load_plugin_from_manifest(
                manifest=manifest,
                plugin_dir=plugin_dir,
                runtime=self._runtime,
                load_plugin_func=self.load_plugin,
                logger_func=warning,
                detect_integration_func=self._detect_and_register_integration,
            )

        await self._lifecycle.reload_plugin(plugin_name, load_from_manifest)
    
    async def start_all(self) -> None:
        await self._lifecycle.start_all()
    
    async def stop_all(self) -> None:
        await self._lifecycle.stop_all()
    
    def get_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        return self._registry.get_plugin(plugin_name)
    
    def get_plugin_state(self, plugin_name: str) -> Optional[PluginState]:
        return self._registry.get_plugin_state(plugin_name)
    
    def get_plugin_block_reason(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        return self._registry.get_plugin_block_reason(plugin_name)
    
    def list_plugins(self) -> list[str]:
        return self._registry.list_plugins()

    def get_loaded_plugins(self) -> list[tuple[str, BasePlugin]]:
        """Список загруженных плагинов для policy/integrity проверок."""
        return list(self._plugins.items())
    
    async def load_plugin_by_name(
        self,
        plugin_name: str,
        plugins_dir: Optional[Path] = None,
        logger_func: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> bool:
        if await self._registry.has_plugin(plugin_name):
            return True
        
        if plugins_dir is None:
            plugins_dir = self._resolve_plugins_dir()
        if plugins_dir is None:
            return False

        plugin_dir = plugins_dir / plugin_name
        if not plugin_dir.is_dir():
            return False
        
        manifest = PluginManifestLoader.load_manifest(plugin_dir)
        if not manifest or manifest.get("name") != plugin_name:
            return False

        deps = manifest.get("dependencies", [])
        loaded_plugins = await self._registry.list_plugins()
        missing = [d for d in deps if d not in loaded_plugins]
        if missing:
            if logger_func:
                await logger_func(
                    self._runtime,
                    f"Плагин '{plugin_name}' не загружен: отсутствуют зависимости {missing}",
                    component="plugin_manager",
                )
            return False
        
        log_func = logger_func or warning
        return await PluginManifestLoader.load_plugin_from_manifest(
            manifest=manifest,
            plugin_dir=plugin_dir,
            runtime=self._runtime,
            load_plugin_func=self.load_plugin,
            logger_func=log_func,
            detect_integration_func=self._detect_and_register_integration,
        )
    
    async def auto_load_plugins(
        self,
        plugins_dir: Optional[Path] = None,
        logger_func: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> None:
        if plugins_dir is None:
            plugins_dir = self._resolve_plugins_dir()
        if plugins_dir is None or not plugins_dir.exists() or not plugins_dir.is_dir():
            return
        
        actual_logger_func: Callable[..., Awaitable[None]] = logger_func if logger_func is not None else warning
        manifests = await PluginManifestLoader.discover_manifests(plugins_dir, self._runtime)
        load_order = PluginManifestLoader.topological_sort(manifests, self._runtime)
        
        plugin_dirs = {}
        for item in plugins_dir.iterdir():
            if item.is_dir() and item.name != "test":
                manifest = PluginManifestLoader.load_manifest(item)
                if manifest:
                    plugin_name = manifest.get("name")
                    if plugin_name:
                        plugin_dirs[plugin_name] = item
        
        for plugin_name in load_order:
            if plugin_name not in manifests:
                continue
            
            manifest = manifests[plugin_name]
            plugin_dir = plugin_dirs.get(plugin_name)
            if not plugin_dir:
                continue

            dependencies = manifest.get("dependencies", [])
            loaded_plugins = await self._registry.list_plugins()
            missing_deps = [dep for dep in dependencies if dep not in loaded_plugins]

            if missing_deps:
                await actual_logger_func(
                    self._runtime,
                    f"Пропущен плагин '{plugin_name}': отсутствуют зависимости {missing_deps}",
                    component="plugin_manager",
                )
                continue

            # Предупреждение: зависимость загружена, но находится в состоянии ERROR
            errored_deps = []
            for dep in dependencies:
                dep_state = await self._registry.get_plugin_state(dep)
                if dep_state == PluginState.ERROR:
                    errored_deps.append(dep)
            if errored_deps:
                await actual_logger_func(
                    self._runtime,
                    f"Предупреждение: плагин '{plugin_name}' загружается, "
                    f"но зависимости {errored_deps} находятся в состоянии ERROR — "
                    f"функциональность может быть деградирована",
                    component="plugin_manager",
                )

            await self._load_plugin_from_manifest(manifest, plugin_dir, actual_logger_func)

    async def _load_plugin_from_manifest(
        self,
        manifest: Dict[str, Any],
        plugin_dir: Path,
        logger_func: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> bool:
        actual_logger_func = logger_func or warning
        return await PluginManifestLoader.load_plugin_from_manifest(
            manifest=manifest,
            plugin_dir=plugin_dir,
            runtime=self._runtime,
            load_plugin_func=self.load_plugin,
            logger_func=actual_logger_func,
            detect_integration_func=self._detect_and_register_integration,
        )

    def _load_plugin_manifest(self, plugin_dir: Path) -> Optional[Dict[str, Any]]:
        return PluginManifestLoader.load_manifest(plugin_dir)
    
    def _detect_and_register_integration(
        self,
        plugin_instance: BasePlugin,
        manifest: Dict[str, Any]
    ) -> None:
        if self._runtime is None:
            return
        
        plugin_name = manifest.get("name", "unknown")
        plugin_description = manifest.get("description", "")
        metadata = plugin_instance.metadata
        
        is_integration = manifest.get("is_integration", False)
        if not is_integration:
            return
        
        flags = set()
        integration_flags = manifest.get("integration_flags", [])
        if isinstance(integration_flags, list):
            for flag_name in integration_flags:
                if not isinstance(flag_name, str):
                    continue
                fn = flag_name.strip().lower()
                if fn == "requires_oauth":
                    flags.add(IntegrationFlag.REQUIRES_OAUTH)
                elif fn == "requires_config":
                    flags.add(IntegrationFlag.REQUIRES_CONFIG)
                elif fn == "beta":
                    flags.add(IntegrationFlag.BETA)
                elif fn == "experimental":
                    flags.add(IntegrationFlag.EXPERIMENTAL)
        if manifest.get("beta", False):
            flags.add(IntegrationFlag.BETA)
        if manifest.get("experimental", False):
            flags.add(IntegrationFlag.EXPERIMENTAL)
        
        integration_name = manifest.get("integration_name") or plugin_name.replace("_", " ").title()
        integration_type = manifest.get("type") or manifest.get("role") or "integration"
        if isinstance(integration_type, list):
            integration_type = integration_type[0] if integration_type else "integration"
        if not isinstance(integration_type, str):
            integration_type = "integration"
        
        try:
            self._runtime.integrations.register(
                integration_id=plugin_name,
                name=integration_name,
                plugin_name=plugin_name,
                flags=flags,
                description=plugin_description or metadata.description,
                integration_type=integration_type,
            )
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "plugin_manager._detect_and_register_integration: expected integration error (suppressed)",
                exc_info=True,
            )
        except BEST_EFFORT_BACKGROUND_ERRORS:
            logger.warning(
                "plugin_manager._detect_and_register_integration: unexpected error (suppressed)",
                exc_info=True,
            )
