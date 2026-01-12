"""
IntegrationRegistry — минимальный реестр интеграций.

Назначение:
- Хранит метаданные об интеграциях (не все плагины — интеграции)
- Используется для admin API (список доступных интеграций)
- In-memory, только {id, name, flags}

Критерии определения интеграции:
1. Явная пометка в plugin.json: "is_integration": true
2. Автоматически: плагин публикует события "external.*"
3. По паттернам (fallback): имя/описание содержат ключевые слова

Архитектура:
- IntegrationRegistry НЕ управляет lifecycle плагинов
- PluginManager остаётся единственным источником правды о плагинах
- IntegrationRegistry только каталогизирует подмножество плагинов как интеграции
"""

from dataclasses import dataclass
from typing import Optional, Dict, Set
from enum import Enum


class IntegrationFlag(Enum):
    """Флаги интеграции."""
    REQUIRES_OAUTH = "requires_oauth"  # Требует OAuth авторизации
    REQUIRES_CONFIG = "requires_config"  # Требует конфигурации
    BETA = "beta"  # Бета-версия
    EXPERIMENTAL = "experimental"  # Экспериментальная


@dataclass
class IntegrationInfo:
    """Метаданные интеграции."""
    id: str  # Идентификатор (обычно plugin_name)
    name: str  # Отображаемое имя
    plugin_name: str  # Имя плагина (связь с PluginManager)
    flags: Set[IntegrationFlag]  # Флаги интеграции
    description: str = ""  # Описание (из plugin metadata)


class IntegrationRegistry:
    """
    Минимальный реестр интеграций.
    
    Хранит только метаданные для admin API.
    Не управляет lifecycle плагинов.
    """
    
    def __init__(self):
        # Словарь: integration_id -> IntegrationInfo
        self._integrations: Dict[str, IntegrationInfo] = {}
    
    def register(
        self,
        integration_id: str,
        name: str,
        plugin_name: str,
        flags: Optional[Set[IntegrationFlag]] = None,
        description: str = ""
    ) -> None:
        """
        Зарегистрировать интеграцию.
        
        Args:
            integration_id: уникальный идентификатор интеграции
            name: отображаемое имя
            plugin_name: имя плагина (связь с PluginManager)
            flags: опциональные флаги
            description: описание интеграции
        """
        if flags is None:
            flags = set()
        
        self._integrations[integration_id] = IntegrationInfo(
            id=integration_id,
            name=name,
            plugin_name=plugin_name,
            flags=flags,
            description=description
        )
    
    def unregister(self, integration_id: str) -> None:
        """
        Удалить интеграцию из реестра.
        
        Args:
            integration_id: идентификатор интеграции
        """
        self._integrations.pop(integration_id, None)
    
    def get(self, integration_id: str) -> Optional[IntegrationInfo]:
        """
        Получить информацию об интеграции.
        
        Args:
            integration_id: идентификатор интеграции
            
        Returns:
            IntegrationInfo или None если не найдена
        """
        return self._integrations.get(integration_id)
    
    def list(self) -> list[IntegrationInfo]:
        """
        Получить список всех зарегистрированных интеграций.
        
        Returns:
            Список IntegrationInfo
        """
        return list(self._integrations.values())
    
    def list_by_plugin(self, plugin_name: str) -> list[IntegrationInfo]:
        """
        Получить список интеграций для плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Список IntegrationInfo для этого плагина
        """
        return [
            info for info in self._integrations.values()
            if info.plugin_name == plugin_name
        ]
    
    def clear(self) -> None:
        """Очистить реестр."""
        self._integrations.clear()
    
    def has_integration(self, integration_id: str) -> bool:
        """
        Проверить, зарегистрирована ли интеграция.
        
        Args:
            integration_id: идентификатор интеграции
            
        Returns:
            True если зарегистрирована
        """
        return integration_id in self._integrations
