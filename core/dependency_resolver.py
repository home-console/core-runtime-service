"""
DependencyResolver — система-уровень проверка integrity.

Валидирует что систему нельзя сломать через:
- Установка плагина с неудовлетворёнными requirements
- Удаление provider плагина который требуется другим
- Отключение plugin'a которого требуют активные plugins
- Startup с broken dependency graph

DependencyResolver:
- Только валидация, не выполняет операции
- Работает с metadata + registry
- Не знает про HTTP, marketplace, execution_mode
- Возвращает список ошибок (пустой = OK)
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass

logger = None


@dataclass
class DependencyError:
    """Single dependency validation error."""
    code: str  # e.g., "missing_capability", "required_provider_removal"
    plugin: str  # plugin name that has the error
    message: str
    details: Optional[Dict[str, Any]] = None


class DependencyResolver:
    """
    Проверяет что операции не приведут систему в broken state.
    
    Использует CapabilityRegistry для информации о providers + dependencies.
    """
    
    def __init__(self, capability_registry: Any, plugin_manager: Any, storage: Any):
        """
        Initialize resolver.
        
        Args:
            capability_registry: CapabilityRegistry для информации о capabilities
            plugin_manager: PluginManager для информации о loaded plugins
            storage: Storage adapter для информации о plugin state
        """
        self.capability_registry = capability_registry
        self.plugin_manager = plugin_manager
        self.storage = storage
    
    def validate_runtime_integrity(self) -> List[str]:
        """
        Проверить что runtime в консистентном состоянии.
        
        После загрузки всех plugins: все их requirements должны быть удовлетворены хотя бы одним provider.
        
        Returns:
            Список ошибок. Пустой список = OK.
        """
        errors: List[DependencyError] = []
        
        # P0: Detect circular dependencies first
        cycle_errors = self._detect_circular_dependencies()
        errors.extend(cycle_errors)
        
        # Получаем все loaded plugins
        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
        except Exception:
            loaded_plugins = []
        
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
                    error = DependencyError(
                        code="missing_capability_provider",
                        plugin=plugin_name,
                        message=f"Required capability '{required_cap}' has no provider",
                        details={"capability": required_cap}
                    )
                    errors.append(error)
        
        # Convert to strings for backward compatibility
        return [f"{e.code}: {e.plugin} - {e.message}" for e in errors]
    
    def _detect_circular_dependencies(self) -> List[DependencyError]:
        """
        P0 Hardening: Detect circular dependencies using DFS.
        
        Returns:
            List of errors if cycles found.
        """
        errors: List[DependencyError] = []
        
        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
        except Exception:
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
                    
                    error = DependencyError(
                        code="circular_dependency",
                        plugin=node,
                        message=f"Circular dependency detected: {cycle_str}",
                        details={"cycle": cycle_str}
                    )
                    errors.append(error)
                    return True
            
            path.pop()
            rec_stack.remove(node)
            return False
        
        # Run DFS from each unvisited node
        for plugin_name in plugin_names:
            if plugin_name not in visited:
                has_cycle_dfs(plugin_name, [])
        
        return errors
    
    def validate_plugin_install(self, metadata: Any) -> List[str]:
        """
        Проверить что плагин может быть установлен.
        
        Все его required capabilities должны иметь хотя бы одного provider среди:
        - Уже loaded plugins
        - Плагина которого устанавливаем (если есть self-provided)
        
        Args:
            metadata: PluginMetadata для плагина который хотим установить
            
        Returns:
            Список ошибок. Пустой список = OK для установки.
        """
        errors: List[DependencyError] = []
        
        plugin_name = getattr(metadata, 'name', 'unknown')
        
        if not hasattr(metadata, 'capabilities_required'):
            return []
        
        # Получаем что предоставляет сам этот плагин
        self_provided = set()
        if hasattr(metadata, 'capabilities_provided'):
            self_provided = set(metadata.capabilities_provided)
        
        # Для каждого required capability
        for required_cap in metadata.capabilities_required:
            # Проверяем есть ли provider
            providers = self.capability_registry.get_providers(required_cap)
            
            # Или плагин сам это предоставляет
            has_self_provider = required_cap in self_provided
            
            if not providers and not has_self_provider:
                error = DependencyError(
                    code="missing_capability_provider",
                    plugin=plugin_name,
                    message=f"Required capability '{required_cap}' has no available provider",
                    details={"capability": required_cap}
                )
                errors.append(error)
        
        return [f"{e.code}: {e.plugin} - {e.message}" for e in errors]
    
    def validate_plugin_removal(self, plugin_name: str) -> List[str]:
        """
        Проверить что плагин может быть удален.
        
        Плагин можно удалить если для каждого capability'a которое он предоставляет:
        - Нет других enabled plugins которые его требуют
        - ИЛИ есть альтернативный provider
        
        Args:
            plugin_name: Имя плагина
            
        Returns:
            Список ошибок. Пустой список = OK для удаления.
        """
        errors: List[DependencyError] = []
        
        # Получаем metadata удаляемого плагина
        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
            plugin_to_remove = None
            for name, plugin in loaded_plugins:
                if name == plugin_name:
                    plugin_to_remove = plugin
                    break
            
            if not plugin_to_remove or not hasattr(plugin_to_remove, 'metadata'):
                # Если плагина нет, нечего проверять
                return []
            
            metadata = plugin_to_remove.metadata
        except Exception:
            return []
        
        # Получаем capabilities которые предоставляет удаляемый плагин
        if not hasattr(metadata, 'capabilities_provided'):
            return []
        
        provided_caps = set(metadata.capabilities_provided)
        
        # Для каждого предоставляемого capability
        for cap in provided_caps:
            # Найти все plugins которые это требуют
            dependents = self._find_plugins_requiring(cap)
            
            if not dependents:
                # Никто не требует, можно удалить без проблем
                continue
            
            # Для каждого dependent plugin найти альтернативные providers
            for dependent_name in dependents:
                if dependent_name == plugin_name:
                    # Сам себе не требует, игнорируем
                    continue
                
                # Найти другие providers этого capability
                all_providers = self.capability_registry.get_providers(cap)
                other_providers = [p for p in all_providers if p != plugin_name]
                
                if not other_providers:
                    # Нет альтернативный providers - запрещаем удаление
                    error = DependencyError(
                        code="required_provider_removal",
                        plugin=plugin_name,
                        message=f"Cannot remove: plugin '{dependent_name}' requires capability '{cap}' with no alternative provider",
                        details={
                            "capability": cap,
                            "dependent": dependent_name,
                            "alternatives": other_providers
                        }
                    )
                    errors.append(error)
        
        return [f"{e.code}: {e.plugin} - {e.message}" for e in errors]
    
    def validate_plugin_disable(self, plugin_name: str) -> List[str]:
        """
        Проверить что плагин может быть отключен.
        
        Аналогично validate_plugin_removal, но без удаления файлов.
        
        Args:
            plugin_name: Имя плагина
            
        Returns:
            Список ошибок. Пустой список = OK для отключения.
        """
        # Disable проверка идентична removal проверке
        # (так как disabled plugin не может предоставлять capabilities)
        return self.validate_plugin_removal(plugin_name)
    
    def validate_plugin_update(self, old_metadata: Any, new_metadata: Any) -> List[str]:
        """
        Проверить что обновление плагина не сломает систему.
        
        Проверяем:
        1. Новый плагин может быть установлен (его requirements удовлетворены)
        2. Capabilities которые убираются не требуются другим plugins
        
        Args:
            old_metadata: Старая PluginMetadata
            new_metadata: Новая PluginMetadata
            
        Returns:
            Список ошибок. Пустой список = OK для обновления.
        """
        errors: List[str] = []
        
        # Проверяем новые requirements
        errors.extend(self.validate_plugin_install(new_metadata))
        
        # Проверяем что убранные capabilities не требуются другим plugins
        old_provided = set()
        if hasattr(old_metadata, 'capabilities_provided'):
            old_provided = set(old_metadata.capabilities_provided)
        
        new_provided = set()
        if hasattr(new_metadata, 'capabilities_provided'):
            new_provided = set(new_metadata.capabilities_provided)
        
        removed_caps = old_provided - new_provided
        
        plugin_name = getattr(old_metadata, 'name', 'unknown')
        
        for cap in removed_caps:
            dependents = self._find_plugins_requiring(cap)
            
            for dependent_name in dependents:
                if dependent_name == plugin_name:
                    continue
                
                all_providers = self.capability_registry.get_providers(cap)
                other_providers = [p for p in all_providers if p != plugin_name]
                
                if not other_providers:
                    error = (f"removal_of_required_capability: {plugin_name} - "
                            f"Cannot remove capability '{cap}' required by '{dependent_name}' "
                            f"with no alternative provider")
                    errors.append(error)
        
        return errors
    
    def _find_plugins_requiring(self, capability: str) -> List[str]:
        """
        Найти all plugins которые требуют данный capability.
        
        Returns:
            Список имен plugins.
        """
        requiring_plugins: List[str] = []
        
        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
        except Exception:
            return []
        
        for plugin_name, plugin in loaded_plugins:
            if not hasattr(plugin, 'metadata'):
                continue
            
            metadata = plugin.metadata
            if not hasattr(metadata, 'capabilities_required'):
                continue
            
            if capability in metadata.capabilities_required:
                requiring_plugins.append(plugin_name)
        
        return requiring_plugins
    
    def get_capability_providers(self, capability: str) -> List[str]:
        """
        Получить список всех providers для capability.
        
        Helper для debugging + tests.
        """
        return self.capability_registry.get_providers(capability)
    
    def get_plugin_required_capabilities(self, plugin_name: str) -> List[str]:
        """
        Получить list required capabilities для plugin'a.
        
        Helper для debugging + tests.
        """
        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
            for name, plugin in loaded_plugins:
                if name == plugin_name:
                    if hasattr(plugin, 'metadata') and hasattr(plugin.metadata, 'capabilities_required'):
                        return plugin.metadata.capabilities_required
        except Exception:
            pass
        
        return []
    
    def get_plugin_provided_capabilities(self, plugin_name: str) -> List[str]:
        """
        Получить list provided capabilities для plugin'a.
        
        Helper для debugging + tests.
        """
        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
            for name, plugin in loaded_plugins:
                if name == plugin_name:
                    if hasattr(plugin, 'metadata') and hasattr(plugin.metadata, 'capabilities_provided'):
                        return plugin.metadata.capabilities_provided
        except Exception:
            pass
        
        return []


class RuntimeIntegrityError(Exception):
    """Runtime has broken dependency graph."""
    
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(
            f"Runtime integrity check failed with {len(errors)} errors:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )
