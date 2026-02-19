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

from core.base_plugin import BasePlugin
from core.logger_helper import warning
from core.kernel.plugin_registry import PluginRegistry, PluginState
from core.kernel.plugin_lifecycle import PluginLifecycleManager
from core.kernel.plugin_loader import PluginManifestLoader
from core.integration_registry import IntegrationFlag

if TYPE_CHECKING:
    from core.runtime import CoreRuntime


class PluginManager:
    """
    Facade для управления lifecycle плагинов.
    
    Делегирует работу специализированным компонентам:
    - PluginRegistry: хранение и query
    - PluginLifecycleManager: lifecycle операции
    - PluginManifestLoader: загрузка манифестов
    """
    
    def __init__(self, runtime: Optional["CoreRuntime"] = None):
        """
        Инициализация PluginManager.
        
        Args:
            runtime: экземпляр CoreRuntime
        """
        self._runtime = runtime
        self._registry = PluginRegistry()
        self._lifecycle = PluginLifecycleManager(self._registry, runtime)
    
    # ========== LIFECYCLE METHODS ==========
    
    async def load_plugin(self, plugin: BasePlugin) -> None:
        """
        Загрузить плагин.
        
        Args:
            plugin: экземпляр плагина
            
        Raises:
            ValueError: если плагин уже загружен или отсутствуют зависимости
        """
        await self._lifecycle.load_plugin(plugin)
    
    async def start_plugin(self, plugin_name: str) -> None:
        """
        Запустить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден или не загружен
        """
        await self._lifecycle.start_plugin(plugin_name)
    
    async def stop_plugin(self, plugin_name: str) -> None:
        """
        Остановить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        await self._lifecycle.stop_plugin(plugin_name)
    
    async def unload_plugin(self, plugin_name: str) -> None:
        """
        Выгрузить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        await self._lifecycle.unload_plugin(plugin_name)
    
    async def reload_plugin(self, plugin_name: str) -> None:
        """
        Перезагрузить плагин (hot-reload).
        
        Args:
            plugin_name: имя плагина для перезагрузки
            
        Raises:
            ValueError: если плагин не найден или не может быть перезагружен
            RuntimeError: если перезагрузка не удалась
        """
        async def load_from_manifest(manifest: Dict[str, Any], plugin_dir: Path) -> bool:
            """Helper для загрузки плагина из манифеста при reload."""
            return await PluginManifestLoader.load_plugin_from_manifest(
                manifest=manifest,
                plugin_dir=plugin_dir,
                runtime=self._runtime,
                load_plugin_func=self.load_plugin,
                logger_func=warning,
                detect_integration_func=self._detect_and_register_integration
            )
        
        await self._lifecycle.reload_plugin(plugin_name, load_from_manifest)
    
    async def start_all(self) -> None:
        """Запустить все загруженные плагины."""
        await self._lifecycle.start_all()
    
    async def stop_all(self) -> None:
        """Остановить все запущенные плагины."""
        await self._lifecycle.stop_all()
    
    # ========== QUERY METHODS ==========
    
    def get_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        """
        Получить экземпляр плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Экземпляр плагина или None
        """
        return self._registry.get_plugin(plugin_name)
    
    def get_plugin_state(self, plugin_name: str) -> Optional[PluginState]:
        """
        Получить состояние плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Состояние плагина или None
        """
        return self._registry.get_plugin_state(plugin_name)
    
    def get_plugin_block_reason(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        Причина, по которой плагин не стартовал (например, отсутствующие capabilities).

        Args:
            plugin_name: имя плагина
        
        Returns:
            None если плагин стартовал или не загружен.
            Иначе dict, например {"missing_capabilities": ["oauth:yandex"]}.
        """
        return self._registry.get_plugin_block_reason(plugin_name)
    
    def list_plugins(self) -> list[str]:
        """
        Получить список всех загруженных плагинов.
        
        Returns:
            Список имён плагинов
        """
        return self._registry.list_plugins()
    
    # ========== MANIFEST LOADING METHODS ==========
    
    async def load_plugin_by_name(
        self,
        plugin_name: str,
        plugins_dir: Optional[Path] = None,
        logger_func: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> bool:
        """
        Загрузить один плагин по имени из каталога plugins/ (по manifest).
        
        Args:
            plugin_name: имя плагина
            plugins_dir: путь к каталогу plugins (если None, определяется автоматически)
            logger_func: функция для логирования
            
        Returns:
            True если плагин успешно загружен
        """
        if self._registry.has_plugin(plugin_name):
            return True
        
        if plugins_dir is None:
            plugins_dir = Path(__file__).parent.parent.parent / "plugins"
        
        plugin_dir = plugins_dir / plugin_name
        if not plugin_dir.is_dir():
            return False
        
        manifest = PluginManifestLoader.load_manifest(plugin_dir)
        if not manifest or manifest.get("name") != plugin_name:
            return False
        
        deps = manifest.get("dependencies", [])
        missing = [d for d in deps if d not in self._registry.list_plugins()]
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
            detect_integration_func=self._detect_and_register_integration
        )
    
    async def auto_load_plugins(
        self,
        plugins_dir: Optional[Path] = None,
        logger_func: Optional[Callable[..., Awaitable[None]]] = None
    ) -> None:
        """
        Автоматически загрузить плагины из каталога `plugins/` ТОЛЬКО через манифесты.
        
        КРИТИЧЕСКИЕ ПРАВИЛА:
        - Плагины загружаются ТОЛЬКО если найден манифест (plugin.json или manifest.json)
        - Без манифеста плагин НЕ загружается
        - НЕ сканирует Python файлы напрямую
        - НЕ импортирует модули для поиска классов
        - Загружает плагины в правильном порядке с учётом зависимостей
        
        Метод безопасен к повторным вызовам — ошибки загрузки отдельных плагинов
        игнорируются, а дублирующие загрузки не прерывают выполнение.
        
        Args:
            plugins_dir: путь к каталогу с плагинами (если None, определяется автоматически)
            logger_func: функция для логирования (если None, используется warning из logger_helper)
        """
        if plugins_dir is None:
            # Определяем каталог plugins относительно корня проекта
            plugins_dir = Path(__file__).parent.parent.parent / "plugins"
        
        if not plugins_dir.exists() or not plugins_dir.is_dir():
            return
        
        # Устанавливаем logger_func по умолчанию если не указан
        actual_logger_func: Callable[..., Awaitable[None]] = logger_func if logger_func is not None else warning
        
        # Шаг 1: Собираем все манифесты
        manifests = await PluginManifestLoader.discover_manifests(plugins_dir, self._runtime)
        
        # Шаг 2: Топологическая сортировка по зависимостям
        load_order = PluginManifestLoader.topological_sort(manifests, self._runtime)
        
        # Шаг 3: Загружаем плагины в правильном порядке
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
            
            # Проверяем, что все зависимости уже загружены
            dependencies = manifest.get("dependencies", [])
            missing_deps = [dep for dep in dependencies if dep not in self._registry.list_plugins()]
            
            if missing_deps:
                await actual_logger_func(
                    self._runtime,
                    f"Пропущен плагин '{plugin_name}': отсутствуют зависимости {missing_deps}",
                    component="plugin_manager"
                )
                continue
            
            # Загружаем плагин из манифеста
            await PluginManifestLoader.load_plugin_from_manifest(
                manifest=manifest,
                plugin_dir=plugin_dir,
                runtime=self._runtime,
                load_plugin_func=self.load_plugin,
                logger_func=actual_logger_func,
                detect_integration_func=self._detect_and_register_integration
            )
    
    # ========== INTEGRATION DETECTION ==========
    
    def _detect_and_register_integration(
        self,
        plugin_instance: BasePlugin,
        manifest: Dict[str, Any]
    ) -> None:
        """
        Определить, является ли плагин интеграцией, и зарегистрировать в IntegrationRegistry.
        
        Критерий определения интеграции:
        - Только явная пометка в manifest: "is_integration": true
        
        Args:
            plugin_instance: экземпляр загруженного плагина
            manifest: данные манифеста плагина
        """
        if self._runtime is None:
            return
        
        plugin_name = manifest.get("name", "unknown")
        plugin_description = manifest.get("description", "")
        metadata = plugin_instance.metadata
        
        # Единственный критерий: явная пометка в manifest
        is_integration = manifest.get("is_integration", False)
        
        if not is_integration:
            return
        
        # Флаги только из явных полей manifest (Core не интерпретирует имена/описания)
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
        
        # Регистрируем интеграцию (тип — из манифеста: type, role или integration)
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
        except Exception:
            # Игнорируем ошибки регистрации интеграций (не критично)
            pass
