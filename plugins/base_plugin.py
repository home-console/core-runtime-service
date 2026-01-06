"""
Базовый класс и интерфейс для плагинов.

Все плагины должны наследоваться от BasePlugin.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.runtime import CoreRuntime


@dataclass
class PluginMetadata:
    """Метаданные плагина."""
    
    name: str
    version: str
    description: str = ""
    author: str = ""
    dependencies: list[str] = None  # Список имён плагинов-зависимостей
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


class BasePlugin(ABC):
    """
    Базовый класс для всех плагинов.
    
    Lifecycle методы вызываются в следующем порядке:
    1. __init__(runtime) - конструктор
    2. on_load() - загрузка плагина
    3. on_start() - запуск плагина
    4. on_stop() - остановка плагина
    5. on_unload() - выгрузка плагина
    """
    
    def __init__(self, runtime: "CoreRuntime"):
        """
        Инициализация плагина.
        
        Args:
            runtime: экземпляр CoreRuntime
        """
        self.runtime = runtime
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
