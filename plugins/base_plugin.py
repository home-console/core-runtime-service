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
    
    # Приватное хранилище runtime; позволяет принимать Optional при записи
    # и возвращать `CoreRuntime` при чтении (через TYPE_CHECKING контракт).
    _runtime: Optional["CoreRuntime"] = None

    # Contract: `runtime` гарантирован менеджером плагинов при вызове lifecycle-методов.

    @property
    def runtime(self) -> "CoreRuntime":
        # Возвращаем runtime как ненулевой (контракт архитектуры).
        assert self._runtime is not None
        return self._runtime

    @runtime.setter
    def runtime(self, value: Optional["CoreRuntime"]) -> None:
        # Позволяем записывать Optional для поддержки lifecycle (unload обнуляет runtime).
        self._runtime = value

    def __init__(self, runtime: Optional["CoreRuntime"] = None) -> None:
        """
        Инициализация плагина.

        `runtime` не передаётся в конструктор и по-умолчанию равен None.
        PluginManager устанавливает ссылку на `runtime` перед вызовом lifecycle методов.
        """
        # runtime будет установлен PluginManager'ом при загрузке плагина
        # Записываем во внутреннее поле; используем property setter, который
        # принимает Optional (чтобы плагины могли обнулять runtime при unload).
        self._runtime = runtime
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
        # Note: PluginManager may load plugins without a runtime set (tests).
        # Do not require runtime to be present here — lifecycle methods may be
        # invoked in environments where runtime is assigned later.
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
