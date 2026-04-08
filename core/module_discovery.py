"""
Module Discovery — обнаружение и создание экземпляров модулей.

Отвечает ТОЛЬКО за:
- Обнаружение модулей по имени (import)
- Создание экземпляров RuntimeModule
- Валидацию что класс является RuntimeModule

НЕ отвечает за:
- Lifecycle модулей (register/start/stop)
- Хранение зарегистрированных модулей
- Dependency ordering

Это позволяет расширять discovery (например, remote modules) без изменения lifecycle.
"""

from typing import Any, Optional, Type, List
import importlib
import importlib.util
import logging
import pkgutil

from core.runtime.runtime_module import RuntimeModule
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS

logger = logging.getLogger(__name__)


class ModuleDiscovery:
    """
    Обнаружение и создание модулей.
    
    Использует importlib для загрузки модулей из packages.
    Поддерживает кастомные module paths (например, remote modules).
    """

    def __init__(self, module_path_prefix: str = "modules"):
        """
        Initialize module discovery.
        
        Args:
            module_path_prefix: префикс пути для импорта модулей (например, "modules")
        """
        self._module_path_prefix = module_path_prefix

    async def discover_module(self, module_name: str) -> Optional[Type[RuntimeModule]]:
        """
        Обнаружить класс RuntimeModule по имени модуля.
        
        Args:
            module_name: имя модуля (например, "automation")
            
        Returns:
            класс RuntimeModule или None если не найден
            
        Raises:
            RuntimeError: если модуль найден, но класс не является RuntimeModule
        """
        module_path = f"{self._module_path_prefix}.{module_name}"
        spec = importlib.util.find_spec(module_path)
        if spec is None:
            return None

        try:
            module = importlib.import_module(module_path)

            # 1) Explicit entrypoint (preferred): __runtime_module_class__
            explicit = getattr(module, "__runtime_module_class__", None)
            if explicit is not None:
                if not isinstance(explicit, type) or not issubclass(explicit, RuntimeModule):
                    raise RuntimeError(
                        f"__runtime_module_class__ in '{module_path}' is not a RuntimeModule subclass"
                    )
                logger.debug("discovery: %s resolved via __runtime_module_class__", module_name)
                return explicit

            # 2) Auto-discovery: if module defines exactly one RuntimeModule subclass.
            runtime_module_classes: List[type] = []
            for value in vars(module).values():
                if (
                    isinstance(value, type)
                    and value is not RuntimeModule
                    and issubclass(value, RuntimeModule)
                ):
                    runtime_module_classes.append(value)

            if len(runtime_module_classes) == 1:
                logger.debug(
                    "discovery: %s resolved via auto-discovery (%s)",
                    module_name,
                    runtime_module_classes[0].__name__,
                )
                return runtime_module_classes[0]

            # 3) Ambiguous multiple RuntimeModule subclasses without explicit entrypoint.
            if len(runtime_module_classes) > 1:
                class_names = ", ".join(sorted(c.__name__ for c in runtime_module_classes))
                raise RuntimeError(
                    f"Ambiguous RuntimeModule discovery for '{module_name}' in '{module_path}'. "
                    f"Found multiple RuntimeModule subclasses: {class_names}. "
                    f"Set __runtime_module_class__ to disambiguate."
                )

            return None
        except ImportError as e:
            raise RuntimeError(f"Failed to import module '{module_path}': {e}")
        except (AttributeError, TypeError, ValueError) as e:
            raise RuntimeError(f"Invalid module discovery state for '{module_name}': {e}")
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            raise RuntimeError(f"Unexpected error discovering module '{module_name}': {e}")

    async def create_module_instance(self, runtime: Any, module_class: Type[RuntimeModule]) -> RuntimeModule:
        """
        Создать экземпляр RuntimeModule.
        
        Args:
            runtime: экземпляр CoreRuntime
            module_class: класс RuntimeModule
            
        Returns:
            экземпляр RuntimeModule
            
        Raises:
            RuntimeError: если создание экземпляра не удалось
        """
        try:
            # Передаём runtime, RuntimeModule сам создаст context если нужно
            # Это обеспечивает обратную совместимость
            return module_class(runtime)
        except (TypeError, ValueError) as e:
            raise RuntimeError(f"Failed to create module instance (invalid args): {e}")
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            raise RuntimeError(f"Failed to create module instance: {e}")

    async def register_module_by_name(
        self,
        runtime: Any,
        module_name: str,
        required: bool = True
    ) -> Optional[RuntimeModule]:
        """
        Обнаружить и создать экземпляр модуля по имени.
        
        Комбинированный метод для удобства.
        
        Args:
            runtime: экземпляр CoreRuntime
            module_name: имя модуля
            required: является ли модуль обязательным
            
        Returns:
            экземпляр модуля или None если не найден (для optional)
            
        Raises:
            RuntimeError: если required=True и модуль не найден/не создан
        """
        # Обнаружение модуля
        module_class = await self.discover_module(module_name)

        if module_class is None:
            if required:
                available = self.list_available_modules()
                available_hint = (
                    f" Available modules: {available}." if available else ""
                )
                raise RuntimeError(
                    f"Required module '{module_name}' not found. "
                    f"Expected module at '{self._module_path_prefix}.{module_name}' "
                    f"with RuntimeModule class export. "
                    f"Prefer setting __runtime_module_class__ in the module."
                    f"{available_hint}"
                )
            # Для optional модулей просто возвращаем None
            return None

        # Создание экземпляра
        try:
            module_instance = await self.create_module_instance(runtime, module_class)
        except RuntimeError:
            # Пробрасываем RuntimeError дальше
            raise
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            if required:
                raise RuntimeError(f"Failed to create instance of required module '{module_name}': {e}")
            # Для optional модулей игнорируем ошибки создания
            return None

        return module_instance

    def list_available_modules(self) -> List[str]:
        """
        Вернуть список имён модулей доступных в module_path_prefix.

        Сканирует пакет по имени префикса, возвращает имена подпакетов/субмодулей.
        Используется для диагностики: "какие модули вообще можно загрузить?".

        Returns:
            Список имён модулей (без префикса), отсортированный.
        """
        try:
            parent = importlib.import_module(self._module_path_prefix)
        except ImportError:
            return []

        available: List[str] = []
        parent_path = getattr(parent, "__path__", None)
        if parent_path is None:
            return []

        for info in pkgutil.iter_modules(parent_path):
            available.append(info.name)

        return sorted(available)
