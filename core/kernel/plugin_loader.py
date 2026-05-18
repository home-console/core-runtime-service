"""
PluginLoader - загрузка манифестов плагинов и discovery.

Отвечает за:
- Загрузку манифестов (plugin.json, manifest.json)
- Топологическую сортировку по зависимостям
- Discovery плагинов в директории

Использует формализованный контракт (PluginManifest, PluginDependencies, PluginContext)
вместо runtime mutation через setattr.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Awaitable
import importlib
import importlib.util

from core.observability.logger_helper import warning, info
from sdk.plugin import BasePlugin as SDKBasePlugin
from core.kernel.base_plugin import BasePlugin
from dataclasses import replace
from core.kernel.plugin_contract import PluginManifest, PluginDependencies, PluginContext
from core.kernel.plugin_isolation import (
    AgentManagerProxy,
    CapabilityRegistryProxy,
    HttpRegistryProxy,
    NamespacedStorageProxy,
    OperationRegistryProxy,
    ServiceRegistryProxy,
)
from core.kernel.plugin_runtime_facade import PluginRuntimeFacade
from sdk.operations_events import OPERATION_READY_EVENT_TYPE
from core.exception_groups import (
    BEST_EFFORT_BACKGROUND_ERRORS,
    LOGGING_HELPER_ERRORS,
    PLUGIN_INTROSPECTION_ERRORS,
)
from core.kernel.plugin_manifest_schema import ValidationError as SchemaValidationError
from core.kernel.plugin_manifest_schema import validate_plugin_json

logger = logging.getLogger(__name__)


class PluginManifestLoader:
    """
    Загрузчик манифестов плагинов.
    
    Отвечает за чтение и валидацию манифестов плагинов.
    """
    
    @staticmethod
    def load_manifest(plugin_path: Path, *, strict: bool = True) -> Optional[Dict[str, Any]]:
        """
        Загрузить манифест плагина из файла plugin.json или manifest.json.

        При ``strict=True`` (по умолчанию) содержимое проверяется через
        ``modules.plugins.schema.validate_plugin_json``; при ошибке —
        логируем и возвращаем None (чтобы один битый плагин не ронял весь процесс discovery).
        
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
                except json.JSONDecodeError as e:
                    logger.error(
                        "Invalid JSON in plugin manifest %s: %s", manifest_path, e,
                    )
                    continue
                except OSError as e:
                    logger.error("Cannot read plugin manifest %s: %s", manifest_path, e)
                    continue
                if strict:
                    try:
                        return validate_plugin_json(manifest_data)
                    except SchemaValidationError as e:
                        logger.error(
                            "plugin.json validation failed for %s: %s", manifest_path, e,
                        )
                        return None
                return manifest_data
        
        return None

    @staticmethod
    def find_plugin_directory(plugins_dir: Path, plugin_name: str) -> Optional[Path]:
        """
        Найти каталог плагина по логическому ``name`` из манифеста.

        Поддерживает каталоги, имя папки ≠ ``plugin_name`` (например ``client-manager-plugin`` для ``client_manager``).
        Если объявлено несколько каталогов с одним ``name``, берётся первый по имени каталога и пишется warning.
        """
        if not plugins_dir.is_dir():
            return None
        matches: list[Path] = []
        for item in sorted(plugins_dir.iterdir(), key=lambda p: p.name):
            if item.name == "test" or not item.is_dir():
                continue
            manifest = PluginManifestLoader.load_manifest(item)
            if manifest and manifest.get("name") == plugin_name:
                matches.append(item)
        if len(matches) > 1:
            logger.warning(
                "Multiple directories declare plugin name %r — using %s among %s",
                plugin_name,
                matches[0],
                matches,
            )
        return matches[0] if matches else None
    
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
                asyncio.create_task(warning(
                    runtime,
                    f"Обнаружены возможные циклические зависимости между плагинами: {remaining}",
                    component="plugin_loader"
                ))
            except RuntimeError as e:
                # Нет running loop (например sync-контекст) — не критично
                logger.debug(
                    "Failed to schedule cyclic dependency warning: %s",
                    e,
                    exc_info=True,
                )
            except LOGGING_HELPER_ERRORS as e:
                logger.debug(
                    "Failed to log warning about cyclic dependencies: %s",
                    e,
                    exc_info=True,
                )

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
            try:
                manifest = validate_plugin_json(dict(manifest))
            except SchemaValidationError as e:
                await logger_func(
                    runtime,
                    f"manifest validation failed ({plugin_dir}): {e}",
                    component="plugin_loader",
                )
                return False

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
            except LOGGING_HELPER_ERRORS as e:
                logger.debug(
                    "Failed to log manifest discovery for %s: %s",
                    plugin_name,
                    e,
                    exc_info=True,
                )

            # Импортируем класс плагина
            module_path, class_name = class_path.rsplit(".", 1)
            
            # Если class_path не в пространстве plugins.*:
            # 1) сначала пробуем обычный import_module (поддержка package-style class_path)
            # 2) если не вышло — загружаем модуль явно по пути (для папок с дефисом)
            try:
                if not class_path.startswith("plugins."):
                    # Prefer loading from the plugin directory when possible to avoid
                    # accidental collisions with existing installed/imported modules
                    # (e.g. module_path == "plugin").
                    plugin_file = plugin_dir / f"{module_path}.py"
                    if plugin_file.exists():
                        unique_module_name = f"hc_dynamic_plugins.{plugin_name}.{module_path}"
                        spec = importlib.util.spec_from_file_location(unique_module_name, plugin_file)
                        if spec is None or spec.loader is None:
                            raise ImportError(f"Не удалось создать spec для модуля: {module_path}")

                        module = importlib.util.module_from_spec(spec)
                        sys.modules[unique_module_name] = module  # уникально, без перезаписи коротких имён
                        spec.loader.exec_module(module)
                    else:
                        try:
                            module = importlib.import_module(module_path)
                        except ImportError:
                            # Явная загрузка модуля по пути без модификации sys.path
                            rel_path = Path(*module_path.split("."))
                            plugin_file = plugin_dir.parent / rel_path / "__init__.py"
                            if not plugin_file.exists():
                                plugin_file = plugin_dir.parent / rel_path.with_suffix(".py")
                                if not plugin_file.exists():
                                    raise FileNotFoundError(f"Модуль не найден: {module_path} в {plugin_dir}")

                            unique_module_name = f"hc_dynamic_plugins.{plugin_name}.{module_path}"
                            spec = importlib.util.spec_from_file_location(unique_module_name, plugin_file)
                            if spec is None or spec.loader is None:
                                raise ImportError(f"Не удалось создать spec для модуля: {module_path}")

                            module = importlib.util.module_from_spec(spec)
                            sys.modules[unique_module_name] = module  # уникально, без перезаписи коротких имён
                            spec.loader.exec_module(module)
                else:
                    # Стандартный импорт для plugins.*
                    module = importlib.import_module(module_path)
                
                plugin_class = getattr(module, class_name)
            except (ImportError, AttributeError, FileNotFoundError) as e:
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
                # SECURITY P0: do NOT pass raw CoreRuntime into plugin __init__.
                # A plugin can execute code in __init__ before sandbox is applied, which would
                # bypass ServiceProxy/StorageProxy allowlists/namespacing.
                plugin_name = str(manifest.get("name") or "unknown")
                default_allowed = (
                    list(getattr(runtime, "plugin_default_allowed_services", []) or [])
                    if runtime is not None
                    else []
                )
                manifest_allowed = manifest.get("allowed_services", []) or []
                # P2.4: log any services beyond the default allowlist so operators can audit.
                if isinstance(manifest_allowed, list) and manifest_allowed:
                    extra_services = [s for s in manifest_allowed if s not in default_allowed]
                    if extra_services:
                        logger.warning(
                            "plugin_loader: plugin '%s' requests extra allowed_services beyond default: %s",
                            plugin_name,
                            extra_services,
                        )
                allowed = (
                    list(manifest_allowed)
                    if isinstance(manifest_allowed, list) and manifest_allowed
                    else default_allowed
                )

                manifest_obj_early = PluginManifest.from_dict(manifest)
                plugin_namespace = manifest_obj_early.namespace
                dynamic_svc = manifest_obj_early.dynamic_service_registration
                allowed_provided_services = list(manifest_obj_early.provides_services or [])
                allowed_events = list(manifest_obj_early.provides_events or [])
                subscribed_events = list(manifest_obj_early.subscribes_events or [])
                allowed_operations = list(manifest_obj_early.provides_operations or [])
                allowed_storage_namespaces = list(manifest_obj_early.storage_namespaces or [])
                manifest_provides = manifest_obj_early.extra.get("provides", {})
                if isinstance(manifest_provides, dict):
                    allowed_provided_services.extend(manifest_provides.get("services", []) or [])
                    allowed_events.extend(manifest_provides.get("events", []) or [])
                    subscribed_events.extend(
                        manifest_provides.get("subscribes", [])
                        or manifest_provides.get("subscribes_events", [])
                        or []
                    )
                    allowed_operations.extend(manifest_provides.get("operations", []) or [])

                raw_event_bus = getattr(runtime, "event_bus", None) if runtime is not None else None
                from core.kernel.plugin_isolation import EventBusProxy
                event_bus_for_facade = (
                    EventBusProxy(
                        raw_event_bus,
                        plugin_name,
                        namespace=plugin_namespace,
                        allowed_events=allowed_events,
                        subscribed_events=subscribed_events,
                        allowed_system_events=[OPERATION_READY_EVENT_TYPE],
                    )
                    if raw_event_bus is not None
                    else None
                )
                raw_operations = getattr(runtime, "operations", None) if runtime is not None else None
                operations_for_facade = (
                    OperationRegistryProxy(
                        raw_operations,
                        plugin_name,
                        namespace=plugin_namespace,
                        allowed_operations=allowed_operations,
                        dynamic_services=dynamic_svc,
                    )
                    if raw_operations is not None
                    else None
                )
                raw_http = getattr(runtime, "http", None) if runtime is not None else None
                http_for_facade = (
                    HttpRegistryProxy(
                        raw_http,
                        plugin_name,
                        namespace=plugin_namespace,
                        allowed_provided_services=allowed_provided_services,
                        dynamic_services=dynamic_svc,
                    )
                    if raw_http is not None
                    else None
                )
                raw_capabilities = (
                    getattr(runtime, "capability_registry", None)
                    if runtime is not None
                    else None
                )
                capabilities_for_facade = (
                    CapabilityRegistryProxy(raw_capabilities)
                    if raw_capabilities is not None
                    else None
                )
                raw_agent_manager = (
                    getattr(runtime, "agent_manager", None) if runtime is not None else None
                )
                agent_manager_for_facade = (
                    AgentManagerProxy(raw_agent_manager)
                    if raw_agent_manager is not None
                    else None
                )

                facade = PluginRuntimeFacade(
                    storage=(
                        NamespacedStorageProxy(
                            getattr(runtime, "storage", None),
                            namespace=plugin_name,
                            allowed_namespaces=allowed_storage_namespaces,
                        )
                        if runtime is not None and getattr(runtime, "storage", None) is not None
                        else None
                    ),
                    service_registry=(
                        ServiceRegistryProxy(
                            getattr(runtime, "service_registry", None),
                            allowed_services=allowed,
                            plugin_name=plugin_name,
                            namespace=plugin_namespace,
                            dynamic_services=dynamic_svc,
                            allowed_provided_services=allowed_provided_services,
                        )
                        if runtime is not None and getattr(runtime, "service_registry", None) is not None
                        else None
                    ),
                    http=http_for_facade,
                    operations=operations_for_facade,
                    state=getattr(runtime, "state", None) if runtime is not None else None,
                    event_bus=event_bus_for_facade,
                    capabilities=capabilities_for_facade,
                    vault=None,
                    config=getattr(runtime, "config", None) if runtime is not None else None,
                    agent_manager=agent_manager_for_facade,
                    agent_registry=None,
                )

                plugin_instance = plugin_class(facade)

                # Создаём формализованный манифест (уже разобран выше)
                manifest_obj = manifest_obj_early

                # Создаём контекст плагина (вместо setattr на экземпляр/класс)
                plugin_context = PluginContext.create(plugin_instance, manifest_obj)

                # Сохраняем контекст в plugin_instance для доступа через _plugin_context
                # Это явный контракт вместо скрытой инъекции полей
                object.__setattr__(plugin_instance, '_plugin_context', plugin_context)

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
                except asyncio.CancelledError:
                    raise
                except PLUGIN_INTROSPECTION_ERRORS:
                    logger.debug(
                        "plugin_loader.load_plugin_from_manifest: info() failed (expected introspection boundary)",
                        exc_info=True,
                    )
                except LOGGING_HELPER_ERRORS:
                    logger.warning(
                        "plugin_loader.load_plugin_from_manifest: info() failed (unexpected)",
                        exc_info=True,
                    )
                
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
            except asyncio.CancelledError:
                raise
            except BEST_EFFORT_BACKGROUND_ERRORS as e:
                logger.warning("plugin_loader.load_plugin_from_manifest: unexpected error: %s", e, exc_info=True)
                await logger_func(
                    runtime,
                    f"Ошибка при создании плагина из манифеста: {e}",
                    component="plugin_loader"
                )
                return False

        except asyncio.CancelledError:
            raise
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            logger.warning("plugin_loader.load_plugin_from_manifest: unexpected error: %s", e, exc_info=True)
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
