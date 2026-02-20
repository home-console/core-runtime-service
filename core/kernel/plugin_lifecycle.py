"""
PluginLifecycle - управление lifecycle плагинов.

Отвечает за:
- Загрузку плагинов (load_plugin)
- Запуск плагинов (start_plugin, start_all)
- Остановку плагинов (stop_plugin, stop_all)
- Выгрузку плагинов (unload_plugin)
- Перезагрузку плагинов (reload_plugin)
"""

from typing import Optional, Any
from pathlib import Path
import sys
import importlib

from core.base_plugin import BasePlugin
from core.kernel.plugin_registry import PluginRegistry, PluginState
from core.kernel.plugin_sandbox import PluginSandbox
from core.kernel.plugin_infrastructure import PluginInfrastructureCoordinator
from core.logger_helper import warning, info


class PluginLifecycleManager:
    """
    Менеджер lifecycle плагинов.
    
    Управляет загрузкой, запуском, остановкой и выгрузкой плагинов.
    """
    
    def __init__(
        self,
        registry: PluginRegistry,
        runtime: Optional[Any] = None
    ):
        """
        Инициализация менеджера lifecycle.
        
        Args:
            registry: реестр плагинов
            runtime: экземпляр CoreRuntime
        """
        self._registry = registry
        self._runtime = runtime

        # Инфраструктурный координатор: capabilities, operations, integrations
        # Явно берём зависимости из runtime, чтобы lifecycle не знал деталей.
        capability_registry = getattr(runtime, "capability_registry", None) if runtime is not None else None
        operations = getattr(runtime, "operations", None) if runtime is not None else None
        integrations = getattr(runtime, "integrations", None) if runtime is not None else None
        self._infra = PluginInfrastructureCoordinator(
            capability_registry=capability_registry,
            operations=operations,
            integrations=integrations,
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
        if self._registry.has_plugin(plugin_name):
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
            deps = getattr(plugin, "_manifest_dependencies", None)
            if deps is None:
                deps = getattr(metadata, "dependencies", []) or []
            if deps:
                for dep_name in deps:
                    if not self._registry.has_plugin(dep_name):
                        raise ValueError(
                            f"Плагин '{plugin_name}' требует плагин '{dep_name}', "
                            f"но он не загружен"
                        )
            
            # Регистрируем в реестре
            self._registry.register(plugin_name, plugin, PluginState.LOADED)
            
            # CapabilityRegistry / инфраструктура: регистрация capabilities вынесена в координатор
            await self._infra.on_plugin_loaded(plugin)
        except Exception as e:
            # Устанавливаем состояние ERROR
            self._registry.set_plugin_state(plugin_name, PluginState.ERROR)
            # Пробросываем оригинальное исключение
            raise
    
    async def start_plugin(self, plugin_name: str) -> None:
        """
        Запустить плагин.
        
        Если у плагина есть требуемые capabilities и хотя бы одна не имеет provider,
        плагин НЕ стартует; состояние остаётся LOADED, причина в get_plugin_block_reason().
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден или не загружен
        """
        plugin = self._registry.get_plugin(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        state = self._registry.get_plugin_state(plugin_name)
        if state == PluginState.STARTED:
            return  # Уже запущен
        
        # Проверка required capabilities: все должны иметь хотя бы одного provider
        self._registry.clear_plugin_block_reason(plugin_name)
        if self._runtime and hasattr(self._runtime, "capability_registry"):
            reg = self._runtime.capability_registry
            if self._runtime:
                await info(self._runtime, f"RUNTIME: validating capabilities for plugin {plugin_name}", component="runtime")
            ok, missing = await reg.validate_plugin_requirements(plugin_name)
            if self._runtime:
                await info(self._runtime, f"RUNTIME: capabilities validated for {plugin_name} ok={ok}", component="runtime")
            if not ok:
                self._registry.set_plugin_block_reason(plugin_name, {"missing_capabilities": missing})
                return  # Плагин не стартуем — управляемое состояние (blocked), не исключение
        
        try:
            await plugin.on_start()
            self._registry.set_plugin_state(plugin_name, PluginState.STARTED)
        except Exception as e:
            self._registry.set_plugin_state(plugin_name, PluginState.ERROR)
            raise RuntimeError(f"Ошибка запуска плагина '{plugin_name}': {e}")
    
    async def stop_plugin(self, plugin_name: str) -> None:
        """
        Остановить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        plugin = self._registry.get_plugin(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        state = self._registry.get_plugin_state(plugin_name)
        if state != PluginState.STARTED:
            return  # Не запущен
        
        try:
            await plugin.on_stop()
            self._registry.set_plugin_state(plugin_name, PluginState.STOPPED)
        except Exception as e:
            self._registry.set_plugin_state(plugin_name, PluginState.ERROR)
            raise RuntimeError(f"Ошибка остановки плагина '{plugin_name}': {e}")
    
    async def unload_plugin(self, plugin_name: str) -> None:
        """
        Выгрузить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        plugin = self._registry.get_plugin(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        # Сначала остановить, если запущен
        state = self._registry.get_plugin_state(plugin_name)
        if state == PluginState.STARTED:
            await self.stop_plugin(plugin_name)
        
        try:
            await plugin.on_unload()
            self._registry.clear_plugin_block_reason(plugin_name)
            
            # Инфраструктурная очистка (capabilities, handlers, integrations)
            await self._infra.on_plugin_unloaded(plugin)

            # Удаляем из реестра плагинов
            self._registry.unregister(plugin_name)
        except Exception as e:
            self._registry.set_plugin_state(plugin_name, PluginState.ERROR)
            raise RuntimeError(f"Ошибка выгрузки плагина '{plugin_name}': {e}")
    
    async def reload_plugin(
        self,
        plugin_name: str,
        load_plugin_from_manifest_func: Optional[Any] = None
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
        if not self._registry.has_plugin(plugin_name):
            raise ValueError(f"Плагин '{plugin_name}' не найден для перезагрузки")
        
        # Сохраняем информацию о состоянии перед перезагрузкой
        was_started = self._registry.get_plugin_state(plugin_name) == PluginState.STARTED
        
        # Получаем путь к плагину из манифеста (нужно для перезагрузки)
        plugins_dir = Path(__file__).parent.parent.parent / "plugins"
        plugin_dir = plugins_dir / plugin_name
        
        if not plugin_dir.exists() or not plugin_dir.is_dir():
            raise ValueError(f"Не удалось найти директорию плагина '{plugin_name}' для перезагрузки")
        
        # Загружаем манифест
        from core.kernel.plugin_loader import PluginManifestLoader
        manifest = PluginManifestLoader.load_manifest(plugin_dir)
        if not manifest:
            raise ValueError(f"Не удалось найти manifest для плагина '{plugin_name}'")
        
        # Выгружаем плагин
        await self.unload_plugin(plugin_name)
        
        # Перезагружаем модуль Python для обновления кода
        class_path = manifest.get("class_path")
        if class_path:
            module_path = class_path.rsplit(".", 1)[0]
            try:
                # Перезагружаем модуль
                if module_path in sys.modules:
                    importlib.reload(sys.modules[module_path])
            except Exception as e:
                # Логируем, но продолжаем - возможно модуль уже перезагружен
                try:
                    await warning(
                        self._runtime,
                        f"Не удалось перезагрузить модуль '{module_path}' для плагина '{plugin_name}': {e}",
                        component="plugin_lifecycle"
                    )
                except Exception:
                    pass
        
        # Загружаем плагин заново из манифеста (если функция предоставлена)
        if load_plugin_from_manifest_func:
            success = await load_plugin_from_manifest_func(manifest, plugin_dir)
            if not success:
                raise RuntimeError(f"Не удалось загрузить плагин '{plugin_name}' после перезагрузки")
        
        # Запускаем плагин, если он был запущен до перезагрузки
        if was_started:
            await self.start_plugin(plugin_name)
    
    async def start_all(self) -> None:
        """Запустить все загруженные плагины."""
        states = self._registry.get_all_states()
        if self._runtime:
            await info(self._runtime, "RUNTIME: plugin_manager.start_all() entered", component="runtime")
        for plugin_name, state in states.items():
            if state == PluginState.LOADED:
                if self._runtime:
                    await info(self._runtime, f"RUNTIME: starting plugin {plugin_name}", component="runtime")
                await self.start_plugin(plugin_name)
                if self._runtime:
                    await info(self._runtime, f"RUNTIME: plugin {plugin_name} started", component="runtime")
    
    async def stop_all(self) -> None:
        """Остановить все запущенные плагины."""
        states = self._registry.get_all_states()
        for plugin_name, state in states.items():
            if state == PluginState.STARTED:
                await self.stop_plugin(plugin_name)
