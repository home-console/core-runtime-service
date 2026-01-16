"""
PluginManager - управление lifecycle плагинов.

Загружает, запускает, останавливает плагины.

КРИТИЧЕСКИЕ ПРАВИЛА:
- Плагины загружаются ТОЛЬКО через manifest (plugin.json или manifest.json)
- Без manifest плагин НЕ загружается
- Зависимости разрешаются автоматически через топологическую сортировку

Подробный контракт: docs/08-PLUGIN-CONTRACT.md
"""

import importlib
import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING, Callable, Awaitable, Dict, Any, List
from enum import Enum

from core.base_plugin import BasePlugin, PluginMetadata
from core.logger_helper import warning, info
from core.integration_registry import IntegrationRegistry, IntegrationFlag
from dataclasses import replace

if TYPE_CHECKING:
    from core.runtime import CoreRuntime


class PluginState(Enum):
    """Состояния плагина."""
    UNLOADED = "unloaded"
    LOADED = "loaded"
    STARTED = "started"
    STOPPED = "stopped"
    ERROR = "error"


class PluginManager:
    """
    Менеджер для управления lifecycle плагинов.
    
    Отвечает за:
    - загрузку плагинов
    - запуск плагинов
    - остановку плагинов
    - отслеживание состояния
    """

    def __init__(self, runtime: Optional["CoreRuntime"] = None):
        # Ссылка на CoreRuntime, может быть не установлена (тесты создают PluginManager() без runtime)
        self._runtime = runtime
        # Словарь: plugin_name -> plugin_instance
        self._plugins: dict[str, BasePlugin] = {}
        # Словарь: plugin_name -> state
        self._states: dict[str, PluginState] = {}

    async def load_plugin(self, plugin: BasePlugin) -> None:
        """
        Загрузить плагин.
        
        Args:
            plugin: экземпляр плагина
            
        Raises:
            ValueError: если плагин уже загружен
        """
        # Получить имя плагина заранее для error handling
        # Читаем metadata ДО on_load, чтобы иметь plugin_name в случае ошибки
        metadata = plugin.metadata
        plugin_name = metadata.name
        
        # Установим ссылку на runtime у плагина перед вызовом on_load
        try:
            try:
                # Мgr может хранить Optional runtime; приводим к CoreRuntime
                # для подавления предупреждений типизации (архитектурный контракт).
                from typing import cast

                plugin.runtime = cast("CoreRuntime", self._runtime)
            except Exception:
                # Установка runtime не должна ломать загрузку
                pass

            # Вызов on_load может обновить metadata (например, remote proxy)
            await plugin.on_load()

            # Заново прочитаем metadata после on_load в случае, если она изменилась
            metadata = plugin.metadata
            plugin_name = metadata.name

            if plugin_name in self._plugins:
                raise ValueError(f"Плагин '{plugin_name}' уже загружен")

            # Проверить зависимости, указанные в metadata после on_load
            if metadata.dependencies:
                for dep_name in metadata.dependencies:
                    if dep_name not in self._plugins:
                        raise ValueError(
                            f"Плагин '{plugin_name}' требует плагин '{dep_name}', "
                            f"но он не загружен"
                        )

            self._plugins[plugin_name] = plugin
            self._states[plugin_name] = PluginState.LOADED
        except Exception as e:
            # Устанавливаем состояние ERROR
            self._states[plugin_name] = PluginState.ERROR
            # Пробросываем оригинальное исключение, чтобы тесты могли его ловить
            raise

    async def start_plugin(self, plugin_name: str) -> None:
        """
        Запустить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден или не загружен
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        if self._states[plugin_name] == PluginState.STARTED:
            return  # Уже запущен
        
        try:
            await plugin.on_start()
            self._states[plugin_name] = PluginState.STARTED
        except Exception as e:
            self._states[plugin_name] = PluginState.ERROR
            raise RuntimeError(f"Ошибка запуска плагина '{plugin_name}': {e}")

    async def stop_plugin(self, plugin_name: str) -> None:
        """
        Остановить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        if self._states[plugin_name] != PluginState.STARTED:
            return  # Не запущен
        
        try:
            await plugin.on_stop()
            self._states[plugin_name] = PluginState.STOPPED
        except Exception as e:
            self._states[plugin_name] = PluginState.ERROR
            raise RuntimeError(f"Ошибка остановки плагина '{plugin_name}': {e}")

    async def unload_plugin(self, plugin_name: str) -> None:
        """
        Выгрузить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        # Сначала остановить, если запущен
        if self._states[plugin_name] == PluginState.STARTED:
            await self.stop_plugin(plugin_name)
        
        try:
            await plugin.on_unload()
            del self._plugins[plugin_name]
            self._states[plugin_name] = PluginState.UNLOADED
            
            # Удаляем интеграцию из реестра (если была зарегистрирована)
            if self._runtime is not None:
                self._runtime.integrations.unregister(plugin_name)
        except Exception as e:
            self._states[plugin_name] = PluginState.ERROR
            raise RuntimeError(f"Ошибка выгрузки плагина '{plugin_name}': {e}")

    def get_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        """
        Получить экземпляр плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Экземпляр плагина или None
        """
        return self._plugins.get(plugin_name)

    def get_plugin_state(self, plugin_name: str) -> Optional[PluginState]:
        """
        Получить состояние плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Состояние плагина или None
        """
        return self._states.get(plugin_name)

    def list_plugins(self) -> list[str]:
        """
        Получить список всех загруженных плагинов.
        
        Returns:
            Список имён плагинов
        """
        return list(self._plugins.keys())

    async def start_all(self) -> None:
        """Запустить все загруженные плагины."""
        for plugin_name in self._plugins.keys():
            if self._states[plugin_name] == PluginState.LOADED:
                await self.start_plugin(plugin_name)

    async def stop_all(self) -> None:
        """Остановить все запущенные плагины."""
        for plugin_name in self._plugins.keys():
            if self._states[plugin_name] == PluginState.STARTED:
                await self.stop_plugin(plugin_name)

    def _load_plugin_manifest(self, plugin_path: Path) -> Optional[Dict[str, Any]]:
        """
        Загрузить манифест плагина из файла plugin.json или manifest.json.
        
        Args:
            plugin_path: путь к директории плагина или файлу плагина
            
        Returns:
            Словарь с данными манифеста или None если манифест не найден
        """
        # Если передан файл, используем его директорию
        if plugin_path.is_file():
            plugin_dir = plugin_path.parent
        else:
            plugin_dir = plugin_path
        
        # Пробуем найти манифест в разных форматах
        manifest_files = ["plugin.json", "manifest.json"]
        for manifest_file in manifest_files:
            manifest_path = plugin_dir / manifest_file
            if manifest_path.exists() and manifest_path.is_file():
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest_data = json.load(f)
                        return manifest_data
                except (json.JSONDecodeError, IOError) as e:
                    # Ошибка чтения манифеста - пропускаем
                    continue
        
        return None

    async def _load_plugin_from_manifest(
        self,
        manifest: Dict[str, Any],
        plugin_dir: Path,
        actual_logger_func: Callable[..., Awaitable[None]]
    ) -> bool:
        """
        Загрузить плагин используя данные из манифеста.
        
        Args:
            manifest: данные манифеста
            plugin_dir: директория плагина
            actual_logger_func: функция для логирования
            
        Returns:
            True если плагин успешно загружен, False иначе
        """
        try:
            # Получаем путь к классу плагина
            class_path = manifest.get("class_path")
            plugin_name = manifest.get("name", "unknown")
            
            if not class_path:
                await actual_logger_func(
                    self._runtime,
                    f"Манифест плагина '{plugin_name}' не содержит 'class_path'",
                    component="plugin_manager"
                )
                return False
            
            # Логируем обнаружение манифеста
            try:
                await info(
                    self._runtime,
                    f"Найден манифест для плагина '{plugin_name}' (class_path: {class_path})",
                    component="plugin_manager"
                )
            except Exception:
                pass
            
            # Импортируем класс плагина
            module_path, class_name = class_path.rsplit(".", 1)
            try:
                module = importlib.import_module(module_path)
                plugin_class = getattr(module, class_name)
            except (ImportError, AttributeError) as e:
                await actual_logger_func(
                    self._runtime,
                    f"Не удалось импортировать класс '{class_path}' из манифеста плагина '{plugin_name}': {e}",
                    component="plugin_manager"
                )
                return False
            
            # Проверяем, что это класс BasePlugin
            if not isinstance(plugin_class, type) or not issubclass(plugin_class, BasePlugin):
                await actual_logger_func(
                    self._runtime,
                    f"Класс '{class_path}' из манифеста плагина '{plugin_name}' не является подклассом BasePlugin",
                    component="plugin_manager"
                )
                return False
            
            # Создаём экземпляр плагина
            try:
                plugin_instance = plugin_class(self._runtime)
                
                # Обновляем metadata плагина зависимостями из манифеста
                # Это нужно, чтобы проверка зависимостей в load_plugin() работала корректно
                manifest_dependencies = manifest.get("dependencies", [])
                if manifest_dependencies:
                    # Получаем текущий metadata
                    current_metadata = plugin_instance.metadata
                    # Обновляем metadata с зависимостями из манифеста
                    updated_metadata = replace(
                        current_metadata,
                        dependencies=manifest_dependencies if isinstance(manifest_dependencies, list) else []
                    )
                    # Сохраняем обновлённый metadata в приватном атрибуте через setattr
                    setattr(plugin_instance, '_manifest_metadata', updated_metadata)
                    # Временно переопределяем property metadata для этого экземпляра
                    # Используем type() для установки property на уровне класса экземпляра
                    original_metadata = type(plugin_instance).metadata
                    # Создаём новый property, который возвращает обновлённый metadata
                    def get_updated_metadata(self):
                        if hasattr(self, '_manifest_metadata'):
                            return getattr(self, '_manifest_metadata')
                        return original_metadata.__get__(self, type(self))
                    
                    # Устанавливаем property на уровне класса экземпляра
                    setattr(type(plugin_instance), 'metadata', property(get_updated_metadata))
                
                await self.load_plugin(plugin_instance)
                
                # Автоопределение интеграций (если runtime доступен)
                if self._runtime is not None:
                    self._detect_and_register_integration(plugin_instance, manifest)
                
                # Логируем успешную загрузку из манифеста
                try:
                    await info(
                        self._runtime,
                        f"Плагин '{plugin_name}' успешно загружен из манифеста",
                        component="plugin_manager"
                    )
                except Exception:
                    pass
                
                return True
            except ValueError as e:
                # Конфликт при загрузке (дубликат или зависимость)
                error_msg = str(e)
                if "уже зарегистрирован" in error_msg or "уже загружен" in error_msg:
                    # Это нормальная ситуация
                    await actual_logger_func(
                        self._runtime,
                        f"Пропущен плагин из манифеста: {error_msg}",
                        component="plugin_manager"
                    )
                else:
                    await actual_logger_func(
                        self._runtime,
                        f"Не удалось загрузить плагин из манифеста: {error_msg}",
                        component="plugin_manager"
                    )
                return False
            except Exception as e:
                await actual_logger_func(
                    self._runtime,
                    f"Ошибка при создании плагина из манифеста: {e}",
                    component="plugin_manager"
                )
                return False
                
        except Exception as e:
            await actual_logger_func(
                self._runtime,
                f"Ошибка при обработке манифеста плагина: {e}",
                component="plugin_manager"
            )
            return False

    def _topological_sort_manifests(self, manifests: Dict[str, Dict[str, Any]]) -> List[str]:
        """
        Топологическая сортировка плагинов по зависимостям.
        
        Args:
            manifests: словарь {plugin_name: manifest_data}
            
        Returns:
            Список имён плагинов в порядке загрузки (сначала без зависимостей)
        """
        # Граф зависимостей: plugin_name -> список зависимостей
        graph: Dict[str, List[str]] = {}
        for plugin_name, manifest in manifests.items():
            deps = manifest.get("dependencies", [])
            graph[plugin_name] = deps if isinstance(deps, list) else []
        
        # Топологическая сортировка (Kahn's algorithm)
        in_degree: Dict[str, int] = {name: 0 for name in manifests.keys()}
        for plugin_name, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[plugin_name] += 1
        
        # Очередь плагинов без зависимостей
        queue: List[str] = [name for name, degree in in_degree.items() if degree == 0]
        result: List[str] = []
        
        while queue:
            plugin_name = queue.pop(0)
            result.append(plugin_name)
            
            # Уменьшаем in_degree для всех плагинов, зависящих от этого
            for other_name, deps in graph.items():
                if plugin_name in deps:
                    in_degree[other_name] -= 1
                    if in_degree[other_name] == 0:
                        queue.append(other_name)
        
        # Если остались плагины с ненулевым in_degree - есть циклические зависимости
        remaining = [name for name, degree in in_degree.items() if degree > 0]
        if remaining:
            # Логируем предупреждение, но продолжаем загрузку
            try:
                import asyncio
                asyncio.create_task(warning(
                    self._runtime,
                    f"Обнаружены возможные циклические зависимости между плагинами: {remaining}",
                    component="plugin_manager"
                ))
            except Exception:
                pass
        
        return result

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
            # core/plugin_manager.py -> core/ -> корень проекта -> plugins/
            plugins_dir = Path(__file__).parent.parent / "plugins"
        
        if not plugins_dir.exists() or not plugins_dir.is_dir():
            return
        
        # Устанавливаем logger_func по умолчанию если не указан
        actual_logger_func: Callable[..., Awaitable[None]] = logger_func if logger_func is not None else warning
        
        # Шаг 1: Собираем все манифесты
        manifests: Dict[str, Dict[str, Any]] = {}  # plugin_name -> (manifest, plugin_dir)
        plugin_dirs: Dict[str, Path] = {}  # plugin_name -> plugin_dir
        
        for item in plugins_dir.iterdir():
            # Пропускаем тестовые плагины
            if item.name == "test":
                continue
            
            # Пропускаем файлы, которые не являются директориями
            if not item.is_dir():
                continue
            
            # Проверяем наличие манифеста в директории плагина
            manifest = self._load_plugin_manifest(item)
            
            if manifest:
                # Пропускаем отключенные плагины
                if manifest.get("_disabled", False):
                    continue
                
                plugin_name = manifest.get("name")
                if plugin_name:
                    manifests[plugin_name] = manifest
                    plugin_dirs[plugin_name] = item
        
        # Шаг 2: Топологическая сортировка по зависимостям
        load_order = self._topological_sort_manifests(manifests)
        
        # Шаг 3: Загружаем плагины в правильном порядке
        for plugin_name in load_order:
            if plugin_name not in manifests:
                continue
            
            manifest = manifests[plugin_name]
            plugin_dir = plugin_dirs[plugin_name]
            
            # Проверяем, что все зависимости уже загружены
            dependencies = manifest.get("dependencies", [])
            missing_deps = [dep for dep in dependencies if dep not in self._plugins]
            
            if missing_deps:
                await actual_logger_func(
                    self._runtime,
                    f"Пропущен плагин '{plugin_name}': отсутствуют зависимости {missing_deps}",
                    component="plugin_manager"
                )
                continue
            
            # Загружаем плагин из манифеста
            # Логирование происходит внутри _load_plugin_from_manifest
            await self._load_plugin_from_manifest(manifest, plugin_dir, actual_logger_func)
    
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
        
        # Определяем флаги интеграции
        flags = set()
        
        name_lower = plugin_name.lower()
        desc_lower = (plugin_description + " " + metadata.description).lower()
        
        # REQUIRES_OAUTH: если имя содержит "oauth" или есть зависимость на oauth плагин
        if "oauth" in name_lower or "oauth" in desc_lower:
            flags.add(IntegrationFlag.REQUIRES_OAUTH)
        
        # Проверяем зависимости на oauth плагины
        dependencies = manifest.get("dependencies", [])
        if any("oauth" in dep.lower() for dep in dependencies):
            flags.add(IntegrationFlag.REQUIRES_OAUTH)
        
        # REQUIRES_CONFIG: если в описании упоминается конфигурация
        if "config" in desc_lower or "configure" in desc_lower or "settings" in desc_lower:
            flags.add(IntegrationFlag.REQUIRES_CONFIG)
        
        # BETA/EXPERIMENTAL: если явно указано в manifest
        if manifest.get("beta", False):
            flags.add(IntegrationFlag.BETA)
        if manifest.get("experimental", False):
            flags.add(IntegrationFlag.EXPERIMENTAL)
        
        # Регистрируем интеграцию
        integration_name = manifest.get("integration_name") or plugin_name.replace("_", " ").title()
        
        try:
            self._runtime.integrations.register(
                integration_id=plugin_name,
                name=integration_name,
                plugin_name=plugin_name,
                flags=flags,
                description=plugin_description or metadata.description
            )
        except Exception:
            # Игнорируем ошибки регистрации интеграций (не критично)
            pass
