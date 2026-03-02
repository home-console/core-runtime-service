"""
PluginLoader - загрузка манифестов плагинов и discovery.

Отвечает за:
- Загрузку манифестов (plugin.json, manifest.json)
- Топологическую сортировку по зависимостям
- Discovery плагинов в директории
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Awaitable
import importlib

from core.logger_helper import warning, info
from sdk.plugin import BasePlugin as SDKBasePlugin
from core.base_plugin import BasePlugin
from dataclasses import replace


class PluginManifestLoader:
    """
    Загрузчик манифестов плагинов.
    
    Отвечает за чтение и валидацию манифестов плагинов.
    """
    
    @staticmethod
    def load_manifest(plugin_path: Path) -> Optional[Dict[str, Any]]:
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
    
    @staticmethod
    def topological_sort(manifests: Dict[str, Dict[str, Any]], runtime: Optional[Any] = None) -> List[str]:
        """
        Топологическая сортировка плагинов по зависимостям.
        
        Использует алгоритм Кана для определения порядка загрузки.
        
        Args:
            manifests: словарь {plugin_name: manifest_data}
            runtime: опциональный runtime для логирования
            
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
                    runtime,
                    f"Обнаружены возможные циклические зависимости между плагинами: {remaining}",
                    component="plugin_loader"
                ))
            except Exception:
                pass
        
        return result
    
    @staticmethod
    async def discover_manifests(
        plugins_dir: Path,
        runtime: Optional[Any] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Обнаружить все манифесты плагинов в директории.
        
        Args:
            plugins_dir: путь к каталогу с плагинами
            runtime: опциональный runtime для логирования
            
        Returns:
            Словарь {plugin_name: manifest_data}
        """
        manifests: Dict[str, Dict[str, Any]] = {}
        
        if not plugins_dir.exists() or not plugins_dir.is_dir():
            return manifests
        
        for item in plugins_dir.iterdir():
            # Пропускаем тестовые плагины
            if item.name == "test":
                continue
            
            # Пропускаем файлы, которые не являются директориями
            if not item.is_dir():
                continue
            
            # Проверяем наличие манифеста в директории плагина
            manifest = PluginManifestLoader.load_manifest(item)
            
            if manifest:
                # Пропускаем отключенные плагины
                if manifest.get("_disabled", False):
                    continue
                
                plugin_name = manifest.get("name")
                if plugin_name:
                    manifests[plugin_name] = manifest
        
        return manifests
    
    @staticmethod
    async def load_plugin_from_manifest(
        manifest: Dict[str, Any],
        plugin_dir: Path,
        runtime: Optional[Any],
        load_plugin_func: Callable[[BasePlugin], Awaitable[None]],
        logger_func: Callable[..., Awaitable[None]],
        detect_integration_func: Optional[Callable[[BasePlugin, Dict[str, Any]], None]] = None
    ) -> bool:
        """
        Загрузить плагин используя данные из манифеста.
        
        Args:
            manifest: данные манифеста
            plugin_dir: директория плагина
            runtime: экземпляр CoreRuntime
            load_plugin_func: функция для загрузки плагина (PluginManager.load_plugin)
            logger_func: функция для логирования
            detect_integration_func: опциональная функция для регистрации интеграций
            
        Returns:
            True если плагин успешно загружен, False иначе
        """
        try:
            # Получаем путь к классу плагина
            class_path = manifest.get("class_path")
            plugin_name = manifest.get("name", "unknown")
            
            if not class_path:
                await logger_func(
                    runtime,
                    f"Манифест плагина '{plugin_name}' не содержит 'class_path'",
                    component="plugin_loader"
                )
                return False
            
            # Логируем обнаружение манифеста
            try:
                await info(
                    runtime,
                    f"Найден манифест для плагина '{plugin_name}' (class_path: {class_path})",
                    component="plugin_loader"
                )
            except Exception:
                pass

            # Если class_path не в пространстве plugins.* — считаем его относительным к plugin_dir
            # (для папок с дефисом, например client-manager-plugin, где нельзя сделать plugins.client-manager-plugin)
            path_inserted = False
            if not class_path.startswith("plugins."):
                sys.path.insert(0, str(plugin_dir))
                path_inserted = True

            # Импортируем класс плагина
            module_path, class_name = class_path.rsplit(".", 1)
            try:
                module = importlib.import_module(module_path)
                plugin_class = getattr(module, class_name)
            except (ImportError, AttributeError) as e:
                if path_inserted and sys.path and sys.path[0] == str(plugin_dir):
                    sys.path.pop(0)
                import traceback
                tb = traceback.format_exc()
                await logger_func(
                    runtime,
                    f"Не удалось импортировать класс '{class_path}' для плагина '{plugin_name}': {e}",
                    component="plugin_loader",
                    traceback=tb[:800] if len(tb) > 800 else tb,
                )
                return False

            # Проверяем, что это класс плагина (sdk.BasePlugin или core.BasePlugin)
            if not isinstance(plugin_class, type) or not issubclass(plugin_class, SDKBasePlugin):
                await logger_func(
                    runtime,
                    f"Класс '{class_path}' из манифеста плагина '{plugin_name}' не является подклассом BasePlugin",
                    component="plugin_loader"
                )
                return False
            
            # Создаём экземпляр плагина
            try:
                plugin_instance = plugin_class(runtime)
                
                # Зависимости из манифеста: передаём в load_plugin через атрибут (для sdk.PluginMetadata нет merge)
                manifest_dependencies = manifest.get("dependencies", [])
                # allowed_services: если указано в manifest — ограничивает ServiceProxy
                manifest_allowed = manifest.get("allowed_services")
                if isinstance(manifest_allowed, list) and manifest_allowed:
                    setattr(plugin_instance, "_manifest_allowed_services", manifest_allowed)
                if isinstance(manifest_dependencies, list) and manifest_dependencies:
                    setattr(plugin_instance, "_manifest_dependencies", manifest_dependencies)
                # Для core.PluginMetadata можно обновить metadata.dependencies (mutable)
                if manifest_dependencies and hasattr(plugin_instance.metadata, "__dataclass_fields__") and "dependencies" in getattr(plugin_instance.metadata, "__dataclass_fields__", {}):
                    try:
                        current_metadata = plugin_instance.metadata
                        updated_metadata = replace(
                            current_metadata,
                            dependencies=manifest_dependencies if isinstance(manifest_dependencies, list) else []
                        )
                        setattr(plugin_instance, "_manifest_metadata", updated_metadata)
                        original_metadata = type(plugin_instance).metadata
                        def get_updated_metadata(self):
                            if hasattr(self, "_manifest_metadata"):
                                return getattr(self, "_manifest_metadata")
                            return original_metadata.__get__(self, type(self))
                        setattr(type(plugin_instance), "metadata", property(get_updated_metadata))
                    except Exception:
                        pass
                
                await load_plugin_func(plugin_instance)
                
                # Автоопределение интеграций (если runtime доступен)
                if detect_integration_func:
                    detect_integration_func(plugin_instance, manifest)
                    if manifest.get("is_integration"):
                        await info(
                            runtime,
                            f"Плагин '{plugin_name}' зарегистрирован как интеграция",
                            component="plugin_loader",
                        )
                
                # Логируем успешную загрузку из манифеста
                try:
                    await info(
                        runtime,
                        f"Плагин '{plugin_name}' успешно загружен из манифеста",
                        component="plugin_loader"
                    )
                except Exception:
                    pass
                
                return True
            except ValueError as e:
                # Конфликт при загрузке (дубликат или зависимость)
                error_msg = str(e)
                if "уже зарегистрирован" in error_msg or "уже загружен" in error_msg:
                    # Это нормальная ситуация
                    await logger_func(
                        runtime,
                        f"Пропущен плагин из манифеста: {error_msg}",
                        component="plugin_loader"
                    )
                else:
                    await logger_func(
                        runtime,
                        f"Не удалось загрузить плагин из манифеста: {error_msg}",
                        component="plugin_loader"
                    )
                return False
            except Exception as e:
                await logger_func(
                    runtime,
                    f"Ошибка при создании плагина из манифеста: {e}",
                    component="plugin_loader"
                )
                return False
                
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            plugin_name = manifest.get("name", "unknown")
            await logger_func(
                runtime,
                f"Ошибка загрузки плагина '{plugin_name}': {e}",
                component="plugin_loader",
                traceback=tb[:800] if len(tb) > 800 else tb,
            )
            return False
