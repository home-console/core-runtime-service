"""
PluginLifecyclePolicy — решения о plugin lifecycle операциях.

Отвечает ТОЛЬКО за:
- Решения о том можно ли выполнить plugin operation (install/remove/disable/update)
- Валидацию что операция не сломает систему

НЕ отвечает за:
- Проверку целостности runtime (это ответственность IntegrityChecker)
- Выполнение самих операций (это ответственность PluginManager)
"""

from typing import List, Any, Set

from core.dependency.models import DependencyError
from core.exception_groups import PLUGIN_INTROSPECTION_ERRORS
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS
import logging

logger = logging.getLogger(__name__)


class PluginLifecyclePolicy:
    """
    Policy decisions для plugin lifecycle операций.
    
    Используется для:
    - Валидации перед install/remove/disable/update
    - Проверки что операция безопасна для системы
    """

    def __init__(self, capability_registry: Any, plugin_manager: Any):
        """
        Initialize lifecycle policy.
        
        Args:
            capability_registry: CapabilityRegistry для информации о capabilities
            plugin_manager: PluginManager для информации о loaded plugins
        """
        self.capability_registry = capability_registry
        self.plugin_manager = plugin_manager

    def can_install_plugin(self, metadata: Any) -> tuple[bool, List[str]]:
        """
        Проверить что плагин может быть установлен.
        
        Все его required capabilities должны иметь хотя бы одного provider среди:
        - Уже loaded plugins
        - Плагина которого устанавливаем (если есть self-provided)
        
        Args:
            metadata: PluginMetadata для плагина который хотим установить
            
        Returns:
            (ok, errors): ok=True если можно установить, errors содержит список проблем
        """
        errors: List[DependencyError] = []
        
        plugin_name = getattr(metadata, 'name', 'unknown')
        
        if not hasattr(metadata, 'capabilities_required'):
            return (True, [])
        
        # Получаем что предоставляет сам этот плагин
        self_provided: Set[str] = set()
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
        
        ok = len(errors) == 0
        return (ok, [f"{e.code}: {e.plugin} - {e.message}" for e in errors])

    def can_remove_plugin(self, plugin_name: str) -> tuple[bool, List[str]]:
        """
        Проверить что плагин может быть удален.
        
        Плагин можно удалить если для каждого capability которое он предоставляет:
        - Нет других enabled plugins которые его требуют
        - ИЛИ есть альтернативный provider
        
        Args:
            plugin_name: Имя плагина
            
        Returns:
            (ok, errors): ok=True если можно удалить, errors содержит список проблем
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
                return (True, [])
            
            metadata = plugin_to_remove.metadata
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            if isinstance(e, PLUGIN_INTROSPECTION_ERRORS):
                logger.warning(
                    "lifecycle_policy.can_remove_plugin: cannot introspect plugins: %s",
                    e,
                    exc_info=True,
                )
            else:
                logger.warning(
                    "lifecycle_policy.can_remove_plugin: unexpected: %s",
                    e,
                    exc_info=True,
                )
            return (True, [])
        
        # Получаем capabilities которые предоставляет удаляемый плагин
        if not hasattr(metadata, 'capabilities_provided'):
            return (True, [])
        
        provided_caps: Set[str] = set(metadata.capabilities_provided)
        
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
        
        ok = len(errors) == 0
        return (ok, [f"{e.code}: {e.plugin} - {e.message}" for e in errors])

    def can_disable_plugin(self, plugin_name: str) -> tuple[bool, List[str]]:
        """
        Проверить что плагин может быть отключен.
        
        Аналогично can_remove_plugin, но без удаления файлов.
        
        Args:
            plugin_name: Имя плагина
            
        Returns:
            (ok, errors): ok=True если можно отключить, errors содержит список проблем
        """
        # Disable проверка идентична removal проверке
        # (так как disabled plugin не может предоставлять capabilities)
        return self.can_remove_plugin(plugin_name)

    def can_update_plugin(self, old_metadata: Any, new_metadata: Any) -> tuple[bool, List[str]]:
        """
        Проверить что обновление плагина не сломает систему.
        
        Проверяем:
        1. Новый плагин может быть установлен (его requirements удовлетворены)
        2. Capabilities которые убираются не требуются другим plugins
        
        Args:
            old_metadata: Старая PluginMetadata
            new_metadata: Новая PluginMetadata
            
        Returns:
            (ok, errors): ok=True если можно обновить, errors содержит список проблем
        """
        all_errors: List[str] = []
        
        # Проверяем новые requirements
        ok_install, install_errors = self.can_install_plugin(new_metadata)
        if not ok_install:
            all_errors.extend(install_errors)
        
        # Проверяем что убранные capabilities не требуются другим plugins
        old_provided: Set[str] = set()
        if hasattr(old_metadata, 'capabilities_provided'):
            old_provided = set(old_metadata.capabilities_provided)
        
        new_provided: Set[str] = set()
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
                    all_errors.append(error)
        
        ok = len(all_errors) == 0
        return (ok, all_errors)

    def _find_plugins_requiring(self, capability: str) -> List[str]:
        """
        Найти все plugins которые требуют данный capability.
        
        Returns:
            Список имен plugins.
        """
        requiring_plugins: List[str] = []
        
        try:
            loaded_plugins = self.plugin_manager.get_loaded_plugins()
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            if isinstance(e, PLUGIN_INTROSPECTION_ERRORS):
                logger.warning(
                    "lifecycle_policy._find_plugins_requiring: cannot list plugins: %s",
                    e,
                    exc_info=True,
                )
            else:
                logger.warning(
                    "lifecycle_policy._find_plugins_requiring: unexpected: %s",
                    e,
                    exc_info=True,
                )
            return []

        for plugin_name, plugin in loaded_plugins:
            if not hasattr(plugin, 'metadata'):
                continue

            metadata = plugin.metadata
            if not hasattr(metadata, 'capabilities_required'):
                continue

            required_caps = metadata.capabilities_required
            if capability in required_caps:
                requiring_plugins.append(plugin_name)

        return requiring_plugins
