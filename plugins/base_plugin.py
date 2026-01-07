"""
Базовый класс и интерфейс для плагинов.

Все плагины должны наследоваться от BasePlugin.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.runtime import CoreRuntime


@dataclass
class PluginMetadata:
    """Метаданные плагина."""
    
    name: str
    version: str
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)  # Список имён плагинов-зависимостей


class BasePlugin(ABC):
    """
    Базовый класс для всех плагинов.
    
    Lifecycle методы вызываются в следующем порядке:
    1. __init__() - конструктор
    2. on_load() - загрузка плагина
    3. on_start() - запуск плагина
    4. on_stop() - остановка плагина
    5. on_unload() - выгрузка плагина
    """
    
    # Явная аннотация атрибута `runtime` для статического анализатора.
    # Устанавливается позднее менеджером плагинов (PluginManager).
    if TYPE_CHECKING:
        from typing import Optional

        runtime: Optional["CoreRuntime"]

    def __init__(self, runtime: Optional["CoreRuntime"] = None) -> None:
        """
        Инициализация плагина.

        `runtime` не передаётся в конструктор и по-умолчанию равен None.
        PluginManager устанавливает ссылку на `runtime` перед вызовом lifecycle методов.
        """
        # runtime будет установлен PluginManager'ом при загрузке плагина
        self.runtime = None
        self._loaded = False
        self._started = False

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """
        Метаданные плагина.
        
        Должен быть реализован в каждом плагине.
        """
        pass

    @property
    def is_loaded(self) -> bool:
        """Загружен ли плагин."""
        return self._loaded

    @property
    def is_started(self) -> bool:
        """Запущен ли плагин."""
        return self._started

    async def on_load(self) -> None:
        """
        Вызывается при загрузке плагина.
        
        Здесь можно:
        - инициализировать ресурсы
        - регистрировать сервисы
        - подписываться на события
        """
        self._loaded = True

    async def on_start(self) -> None:
        """
        Вызывается при запуске плагина.
        
        Здесь можно:
        - запустить фоновые задачи
        - начать обработку данных
        """
        self._started = True

    async def on_stop(self) -> None:
        """
        Вызывается при остановке плагина.
        
        Здесь нужно:
        - остановить фоновые задачи
        - освободить ресурсы
        """
        self._started = False

    async def on_unload(self) -> None:
        """
        Вызывается при выгрузке плагина.
        
        Здесь нужно:
        - отписаться от событий
        - удалить сервисы
        - закрыть соединения
        """
        self._loaded = False
