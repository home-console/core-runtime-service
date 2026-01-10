"""
PluginManager - управление lifecycle плагинов.

Загружает, запускает, останавливает плагины.
"""

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Optional, TYPE_CHECKING, Callable, Awaitable
from enum import Enum

from plugins.base_plugin import BasePlugin, PluginMetadata
from core.logger_helper import warning

if TYPE_CHECKING:
    from core.runtime import CoreRuntime


class PluginState(Enum):
    """Состояния плагина."""
    UNLOADED = "unloaded"
    LOADED = "loaded"
    STARTED = "started"
    STOPPED = "stopped"
    ERROR = "error"


class PluginManager:
    """
    Менеджер для управления lifecycle плагинов.
    
    Отвечает за:
    - загрузку плагинов
    - запуск плагинов
    - остановку плагинов
    - отслеживание состояния
    """

    def __init__(self, runtime: Optional["CoreRuntime"] = None):
        # Ссылка на CoreRuntime, может быть не установлена (тесты создают PluginManager() без runtime)
        self._runtime = runtime
        # Словарь: plugin_name -> plugin_instance
        self._plugins: dict[str, BasePlugin] = {}
        # Словарь: plugin_name -> state
        self._states: dict[str, PluginState] = {}

    async def load_plugin(self, plugin: BasePlugin) -> None:
        """
        Загрузить плагин.
        
        Args:
            plugin: экземпляр плагина
            
        Raises:
            ValueError: если плагин уже загружен
        """
        # Получить имя плагина заранее для error handling
        # Читаем metadata ДО on_load, чтобы иметь plugin_name в случае ошибки
        metadata = plugin.metadata
        plugin_name = metadata.name
        
        # Установим ссылку на runtime у плагина перед вызовом on_load
        try:
            try:
                # Мgr может хранить Optional runtime; приводим к CoreRuntime
                # для подавления предупреждений типизации (архитектурный контракт).
                from typing import cast

                plugin.runtime = cast("CoreRuntime", self._runtime)
            except Exception:
                # Установка runtime не должна ломать загрузку
                pass

            # Вызов on_load может обновить metadata (например, remote proxy)
            await plugin.on_load()

            # Заново прочитаем metadata после on_load в случае, если она изменилась
            metadata = plugin.metadata
            plugin_name = metadata.name

            if plugin_name in self._plugins:
                raise ValueError(f"Плагин '{plugin_name}' уже загружен")

            # Проверить зависимости, указанные в metadata после on_load
            if metadata.dependencies:
                for dep_name in metadata.dependencies:
                    if dep_name not in self._plugins:
                        raise ValueError(
                            f"Плагин '{plugin_name}' требует плагин '{dep_name}', "
                            f"но он не загружен"
                        )

            self._plugins[plugin_name] = plugin
            self._states[plugin_name] = PluginState.LOADED
        except Exception as e:
            # Устанавливаем состояние ERROR
            self._states[plugin_name] = PluginState.ERROR
            # Пробросываем оригинальное исключение, чтобы тесты могли его ловить
            raise

    async def start_plugin(self, plugin_name: str) -> None:
        """
        Запустить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден или не загружен
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        if self._states[plugin_name] == PluginState.STARTED:
            return  # Уже запущен
        
        try:
            await plugin.on_start()
            self._states[plugin_name] = PluginState.STARTED
        except Exception as e:
            self._states[plugin_name] = PluginState.ERROR
            raise RuntimeError(f"Ошибка запуска плагина '{plugin_name}': {e}")

    async def stop_plugin(self, plugin_name: str) -> None:
        """
        Остановить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        if self._states[plugin_name] != PluginState.STARTED:
            return  # Не запущен
        
        try:
            await plugin.on_stop()
            self._states[plugin_name] = PluginState.STOPPED
        except Exception as e:
            self._states[plugin_name] = PluginState.ERROR
            raise RuntimeError(f"Ошибка остановки плагина '{plugin_name}': {e}")

    async def unload_plugin(self, plugin_name: str) -> None:
        """
        Выгрузить плагин.
        
        Args:
            plugin_name: имя плагина
            
        Raises:
            ValueError: если плагин не найден
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            raise ValueError(f"Плагин '{plugin_name}' не найден")
        
        # Сначала остановить, если запущен
        if self._states[plugin_name] == PluginState.STARTED:
            await self.stop_plugin(plugin_name)
        
        try:
            await plugin.on_unload()
            del self._plugins[plugin_name]
            self._states[plugin_name] = PluginState.UNLOADED
        except Exception as e:
            self._states[plugin_name] = PluginState.ERROR
            raise RuntimeError(f"Ошибка выгрузки плагина '{plugin_name}': {e}")

    def get_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        """
        Получить экземпляр плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Экземпляр плагина или None
        """
        return self._plugins.get(plugin_name)

    def get_plugin_state(self, plugin_name: str) -> Optional[PluginState]:
        """
        Получить состояние плагина.
        
        Args:
            plugin_name: имя плагина
            
        Returns:
            Состояние плагина или None
        """
        return self._states.get(plugin_name)

    def list_plugins(self) -> list[str]:
        """
        Получить список всех загруженных плагинов.
        
        Returns:
            Список имён плагинов
        """
        return list(self._plugins.keys())

    async def start_all(self) -> None:
        """Запустить все загруженные плагины."""
        for plugin_name in self._plugins.keys():
            if self._states[plugin_name] == PluginState.LOADED:
                await self.start_plugin(plugin_name)

    async def stop_all(self) -> None:
        """Остановить все запущенные плагины."""
        for plugin_name in self._plugins.keys():
            if self._states[plugin_name] == PluginState.STARTED:
                await self.stop_plugin(plugin_name)

    async def auto_load_plugins(
        self,
        plugins_dir: Optional[Path] = None,
        logger_func: Optional[Callable[..., Awaitable[None]]] = None
    ) -> None:
        """
        Автоматически загрузить плагины из каталога `plugins/`.
        
        Метод безопасен к повторным вызовам — ошибки загрузки отдельных плагинов
        игнорируются, а дублирующие загрузки не прерывают выполнение.
        
        Args:
            plugins_dir: путь к каталогу с плагинами (если None, определяется автоматически)
            logger_func: функция для логирования (если None, используется warning из logger_helper)
        """
        if plugins_dir is None:
            # Определяем каталог plugins относительно корня проекта
            # core/plugin_manager.py -> core/ -> корень проекта -> plugins/
            plugins_dir = Path(__file__).parent.parent / "plugins"
        
        if not plugins_dir.exists() or not plugins_dir.is_dir():
            return
        
        # Устанавливаем logger_func по умолчанию если не указан
        actual_logger_func: Callable[..., Awaitable[None]] = logger_func if logger_func is not None else warning
        
        for _finder, mod_name, _pkg in pkgutil.iter_modules([str(plugins_dir)]):
            module_name = f"plugins.{mod_name}"
            try:
                module = importlib.import_module(module_name)
            except Exception as e:
                # Игнорируем ошибки импорта отдельных модулей
                try:
                    await actual_logger_func(
                        self._runtime,
                        f"Не удалось импортировать модуль '{module_name}': {e}",
                        component="plugin_manager"
                    )
                except Exception:
                    # Fallback если logger недоступен
                    pass
                continue
            
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if obj is BasePlugin:
                    continue
                
                # Проверяем, что это класс и он наследуется от BasePlugin
                if not isinstance(obj, type):
                    continue
                
                try:
                    if not issubclass(obj, BasePlugin):
                        continue
                except TypeError:
                    # Не класс или не BasePlugin - пропускаем
                    continue
                
                # Пропускаем YandexSmartHomeStubPlugin при автозагрузке
                # Он конфликтует с YandexSmartHomeRealPlugin (оба регистрируют yandex.sync_devices)
                # Stub должен загружаться явно только для тестов
                class_name = getattr(obj, '__name__', '')
                if class_name == 'YandexSmartHomeStubPlugin':
                    # Пропускаем Yandex stub плагин при автозагрузке
                    continue
                
                # Специальная обработка для RemotePluginProxy
                # Загружается только если есть переменная окружения (проверяется внутри __init__)
                if class_name == 'RemotePluginProxy':
                    try:
                        # Создаём экземпляр без remote_url - он сам получит из переменных окружения
                        plugin_instance = obj(self._runtime)
                        await self.load_plugin(plugin_instance)
                    except ValueError as e:
                        # ValueError означает, что нет remote_url - это нормально, пропускаем тихо
                        if "remote_url обязателен" in str(e):
                            # Нет URL - пропускаем тихо (это нормально)
                            continue
                        # Другие ValueError - логируем
                        try:
                            await actual_logger_func(
                                self._runtime,
                                f"Не удалось загрузить RemotePluginProxy: {e}",
                                component="plugin_manager"
                            )
                        except Exception:
                            pass
                    except Exception as e:
                        # Другие ошибки - логируем
                        try:
                            await actual_logger_func(
                                self._runtime,
                                f"Не удалось загрузить RemotePluginProxy: {e}",
                                component="plugin_manager"
                            )
                        except Exception:
                            pass
                    continue
                
                # Проверяем сигнатуру конструктора
                # Пропускаем плагины, которые требуют дополнительные параметры
                try:
                    sig = inspect.signature(obj.__init__)
                    # Считаем параметры кроме self и runtime
                    params = list(sig.parameters.keys())
                    # Убираем 'self'
                    if 'self' in params:
                        params.remove('self')
                    # Убираем 'runtime' если есть
                    if 'runtime' in params:
                        params.remove('runtime')
                    
                    # Если остались обязательные параметры (без значений по умолчанию),
                    # пропускаем этот плагин при автозагрузке
                    required_params = []
                    for param_name in params:
                        param = sig.parameters[param_name]
                        # Проверяем, есть ли значение по умолчанию
                        if param.default is inspect.Parameter.empty:
                            required_params.append(param_name)
                    
                    if required_params:
                        # Плагин требует дополнительные параметры - пропускаем
                        plugin_name = getattr(obj, '__name__', 'unknown')
                        try:
                            await actual_logger_func(
                                self._runtime,
                                f"Пропущен плагин '{plugin_name}' при автозагрузке: требуется параметр(ы) {required_params}",
                                component="plugin_manager"
                            )
                        except Exception:
                            pass
                        continue
                except Exception:
                    # Если не удалось проверить сигнатуру, пробуем загрузить
                    pass
                
                try:
                    plugin_instance = obj(self._runtime)
                    await self.load_plugin(plugin_instance)
                except ValueError as e:
                    # ValueError при load_plugin обычно означает конфликт (дубликат или зависимость)
                    # Это нормально - просто логируем и продолжаем
                    plugin_name = getattr(obj, '__name__', 'unknown')
                    error_msg = str(e)
                    # Не логируем как WARNING, если это просто конфликт сервисов
                    if "уже зарегистрирован" in error_msg or "уже загружен" in error_msg:
                        # Это нормальная ситуация - плагин уже загружен или сервис занят
                        try:
                            await actual_logger_func(
                                self._runtime,
                                f"Пропущен плагин '{plugin_name}': {error_msg}",
                                component="plugin_manager"
                            )
                        except Exception:
                            pass
                    else:
                        # Другие ValueError - логируем как предупреждение
                        try:
                            await actual_logger_func(
                                self._runtime,
                                f"Не удалось загрузить плагин '{plugin_name}': {error_msg}",
                                component="plugin_manager"
                            )
                        except Exception:
                            pass
                except Exception as e:
                    # Игнорируем другие ошибки загрузки отдельных плагинов
                    plugin_name = getattr(obj, '__name__', 'unknown')
                    try:
                        await actual_logger_func(
                            self._runtime,
                            f"Не удалось загрузить плагин '{plugin_name}': {e}",
                            component="plugin_manager"
                        )
                    except Exception:
                        # Fallback если logger недоступен
                        pass
                    continue
