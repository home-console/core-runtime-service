"""
PluginContract — формализованный контракт для плагинов.

Вместо runtime mutation через setattr, используем явный контракт:
- PluginManifest — данные манифеста
- PluginDependencies — зависимости плагина
- PluginContext — контекст выполнения плагина

Это устраняет проблемы C1 и C2:
- C1: Runtime mutation класса плагина через setattr(type(...))
- C2: Инъекция runtime-полей в plugin instance через setattr
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypeVar, Generic


@dataclass(frozen=True)
class PluginManifest:
    """
    Формализованный манифест плагина.

    Атрибуты:
        name: имя плагина
        version: версия плагина
        class_path: путь к классу плагина
        dependencies: список зависимостей
        allowed_services: список разрешённых сервисов
        is_integration: флаг интеграции
        container_config: конфигурация контейнера (опционально)
        extra: дополнительные данные из манифеста
    """
    name: str
    version: str
    class_path: str
    dependencies: List[str] = field(default_factory=list)
    allowed_services: List[str] = field(default_factory=list)
    is_integration: bool = False
    container_config: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        """
        Создать PluginManifest из словаря.

        Args:
            data: словарь с данными манифеста

        Returns:
            Экземпляр PluginManifest
        """
        return cls(
            name=data.get("name", "unknown"),
            version=data.get("version", "0.0.0"),
            class_path=data.get("class_path", ""),
            dependencies=data.get("dependencies", []) or [],
            allowed_services=data.get("allowed_services", []) or [],
            is_integration=bool(data.get("is_integration", False)),
            container_config=data.get("container_config"),
            extra={k: v for k, v in data.items() if k not in [
                "name", "version", "class_path", "dependencies",
                "allowed_services", "is_integration", "container_config"
            ]}
        )


@dataclass(frozen=True)
class PluginDependencies:
    """
    Формализованные зависимости плагина.

    Атрибуты:
        dependencies: список зависимостей
        allowed_services: список разрешённых сервисов
    """
    dependencies: List[str] = field(default_factory=list)
    allowed_services: List[str] = field(default_factory=list)

    @classmethod
    def from_manifest(cls, manifest: PluginManifest) -> "PluginDependencies":
        """
        Создать PluginDependencies из манифеста.

        Args:
            manifest: экземпляр PluginManifest

        Returns:
            Экземпляр PluginDependencies
        """
        return cls(
            dependencies=manifest.dependencies,
            allowed_services=manifest.allowed_services,
        )


T = TypeVar('T')


@dataclass
class PluginContext(Generic[T]):
    """
    Контекст выполнения плагина.

    Связывает плагин с его манифестом и зависимостями
    без модификации класса или экземпляра.

    Атрибуты:
        plugin: экземпляр плагина
        manifest: манифест плагина
        dependencies: зависимости плагина
        metadata: дополнительные метаданные
    """
    plugin: T
    manifest: PluginManifest
    dependencies: PluginDependencies
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        plugin: T,
        manifest: PluginManifest,
    ) -> "PluginContext[T]":
        """
        Создать PluginContext для плагина.

        Args:
            plugin: экземпляр плагина
            manifest: манифест плагина

        Returns:
            Экземпляр PluginContext
        """
        dependencies = PluginDependencies.from_manifest(manifest)
        return cls(
            plugin=plugin,
            manifest=manifest,
            dependencies=dependencies,
            metadata={},
        )


class PluginRegistry:
    """
    Реестр плагинов с формализованным контрактом.

    Хранит PluginContext вместо модификации плагинов.
    """

    def __init__(self):
        self._contexts: Dict[str, PluginContext[Any]] = {}

    def register(self, plugin_name: str, context: PluginContext[Any]) -> None:
        """
        Зарегистрировать плагин.

        Args:
            plugin_name: имя плагина
            context: контекст плагина
        """
        self._contexts[plugin_name] = context

    def get(self, plugin_name: str) -> Optional[PluginContext[Any]]:
        """
        Получить контекст плагина по имени.

        Args:
            plugin_name: имя плагина

        Returns:
            PluginContext или None
        """
        return self._contexts.get(plugin_name)

    def list_plugins(self) -> List[str]:
        """
        Получить список зарегистрированных плагинов.

        Returns:
            Список имён плагинов
        """
        return list(self._contexts.keys())

    def unregister(self, plugin_name: str) -> Optional[PluginContext[Any]]:
        """
        Удалить плагин из реестра.

        Args:
            plugin_name: имя плагина

        Returns:
            Удалённый PluginContext или None
        """
        return self._contexts.pop(plugin_name, None)
