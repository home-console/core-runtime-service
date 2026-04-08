"""
DependencyIntegrityChecker — проверка целостности runtime.

Отвечает ТОЛЬКО за:
- Валидацию что runtime в консистентном состоянии
- Поиск циклических зависимостей
- Проверку что все required capabilities имеют providers

НЕ отвечает за:
- Решения о том можно ли выполнить plugin operation (install/remove/disable/update)
- Это ответственность LifecyclePolicy
"""

from typing import List, Any

from core.dependency.models import DependencyError, RuntimeIntegrityError
from core.dependency.result import Error
from core.exception_groups import PLUGIN_INTROSPECTION_ERRORS
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS
import logging

logger = logging.getLogger(__name__)


class DependencyIntegrityChecker:
    """
    Проверка целостности runtime системы.
    
    Используется для:
    - Валидации после загрузки плагинов
    - Периодических проверок health
    - Диагностики проблем
    """

    def __init__(self, capability_registry: Any, plugin_manager: Any):
        """
        Initialize integrity checker.
        
        Args:
            capability_registry: CapabilityRegistry для информации о capabilities
            plugin_manager: PluginManager для информации о loaded plugins
        """
        self.capability_registry = capability_registry
        self.plugin_manager = plugin_manager

    def check_runtime_integrity(self) -> List[str]:
        """
        Проверить что runtime в консистентном состоянии.
        
        После загрузки всех plugins: все их requirements должны быть удовлетворены хотя бы одним provider.
        
        Returns:
            Список ошибок. Пустой список = OK.
        """
        errors: List[Error] = []

        # P0: Detect circular dependencies first
        cycle_errors = self._detect_circular_dependencies()
        errors.extend(cycle_errors)

        # Получаем все loaded plugins
        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            if isinstance(e, PLUGIN_INTROSPECTION_ERRORS):
                logger.warning(
                    "integrity_checker.check_runtime_integrity: cannot list plugins: %s",
                    e,
                    exc_info=True,
                )
            else:
                logger.warning(
                    "integrity_checker.check_runtime_integrity: unexpected error: %s",
                    e,
                    exc_info=True,
                )
            errors.append(Error(
                code="runtime_check_failed",
                message=f"Failed to get loaded plugins: {e}",
                details={"exception_type": type(e).__name__},
                component="integrity_checker"
            ))
            return [f"{e.code}: {e.message}" for e in errors]

        # Для каждого plugin'a проверяем что все его required capabilities имеют providers
        for plugin_name, plugin in loaded_plugins:
            if not hasattr(plugin, 'metadata'):
                continue

            metadata = plugin.metadata
            if not hasattr(metadata, 'capabilities_required'):
                continue

            # Проверяем каждый required capability
            for required_cap in metadata.capabilities_required:
                providers = self.capability_registry.get_providers(required_cap)

                if not providers:
                    errors.append(Error(
                        code="missing_capability_provider",
                        message=f"Required capability '{required_cap}' has no provider",
                        details={"capability": required_cap, "plugin": plugin_name},
                        component="integrity_checker"
                    ))

        return [f"{e.code}: {e.message}" for e in errors]

    def _detect_circular_dependencies(self) -> List[Error]:
        """
        P0 Hardening: Detect circular dependencies using DFS.
        
        Returns:
            List of Error if cycles found.
        """
        errors: List[Error] = []

        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            if isinstance(e, PLUGIN_INTROSPECTION_ERRORS):
                logger.warning(
                    "integrity_checker._detect_circular_dependencies: cannot list plugins: %s",
                    e,
                    exc_info=True,
                )
            else:
                logger.warning(
                    "integrity_checker._detect_circular_dependencies: unexpected: %s",
                    e,
                    exc_info=True,
                )
            return []

        # Build dependency graph: plugin -> [plugins providing its required capabilities]
        plugin_names = {name for name, _ in loaded_plugins}
        plugin_provides = {}  # plugin_name -> [capabilities it provides]
        plugin_requires = {}  # plugin_name -> [capabilities it requires]

        for plugin_name, plugin in loaded_plugins:
            if not hasattr(plugin, 'metadata'):
                continue

            metadata = plugin.metadata
            plugin_provides[plugin_name] = list(getattr(metadata, 'capabilities_provided', []) or [])
            plugin_requires[plugin_name] = list(getattr(metadata, 'capabilities_required', []) or [])

        # Build adjacency list: plugin -> [other plugins providing its requirements]
        adjacency = {}
        for plugin_name in plugin_names:
            adjacency[plugin_name] = []

            for required_cap in plugin_requires.get(plugin_name, []):
                # Find which plugins provide this capability
                for other_name in plugin_names:
                    if other_name != plugin_name and required_cap in plugin_provides.get(other_name, []):
                        adjacency[plugin_name].append(other_name)

        # DFS for cycles
        visited = set()
        rec_stack = set()

        def has_cycle_dfs(node: str, path: List[str]) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in adjacency.get(node, []):
                if neighbor not in visited:
                    if has_cycle_dfs(neighbor, path):
                        return True
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycle_str = " → ".join(cycle)

                    errors.append(Error(
                        code="circular_dependency",
                        message=f"Circular dependency detected: {cycle_str}",
                        details={"cycle": cycle, "plugins_involved": list(set(cycle))},
                        component="integrity_checker"
                    ))
                    return True

            path.pop()
            rec_stack.remove(node)
            return False

        # Check all plugins
        for plugin_name in plugin_names:
            if plugin_name not in visited:
                has_cycle_dfs(plugin_name, [])

        return errors

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """
        Получить граф зависимостей для визуализации/диагностики.
        
        Returns:
            Dict: plugin_name -> [plugins от которых зависит]
        """
        graph: dict[str, list[str]] = {}
        
        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            if isinstance(e, PLUGIN_INTROSPECTION_ERRORS):
                logger.warning(
                    "integrity_checker.get_dependency_graph: cannot list plugins: %s",
                    e,
                    exc_info=True,
                )
            else:
                logger.warning(
                    "integrity_checker.get_dependency_graph: unexpected: %s",
                    e,
                    exc_info=True,
                )
            return {}

        plugin_provides = {}
        plugin_requires = {}

        for plugin_name, plugin in loaded_plugins:
            if not hasattr(plugin, 'metadata'):
                continue

            metadata = plugin.metadata
            plugin_provides[plugin_name] = set(getattr(metadata, 'capabilities_provided', []) or [])
            plugin_requires[plugin_name] = set(getattr(metadata, 'capabilities_required', []) or [])
            graph[plugin_name] = []

        # Build graph
        for plugin_name, requires in plugin_requires.items():
            for required_cap in requires:
                for other_name, provides in plugin_provides.items():
                    if other_name != plugin_name and required_cap in provides:
                        graph[plugin_name].append(other_name)

        return graph
