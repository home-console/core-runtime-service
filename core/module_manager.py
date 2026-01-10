"""
ModuleManager — менеджер встроенных модулей Runtime.

Управляет жизненным циклом RuntimeModule:
- обнаружение и регистрация модулей
- запуск/остановка модулей
- гарантия уникальности имён
"""

from typing import Any, Dict, List, Optional
import sys
import importlib
import importlib.util

from core.runtime_module import RuntimeModule
from core.logger_helper import error as log_error


# Список обязательных модулей (встроенных доменов)
# ВАЖНО: logger должен быть первым, так как он нужен для логирования других модулей!
BUILTIN_MODULES = [
    "logger",      # LoggerModule (инфраструктурный, должен быть первым)
    "devices",     # DevicesModule
    "automation",  # AutomationModule
    "presence",    # PresenceModule
]


class ModuleManager:
    """
    Менеджер встроенных модулей Runtime.

    Управляет экземплярами RuntimeModule, гарантирует уникальность имён,
    обеспечивает идемпотентность регистрации.
    """

    def __init__(self, runtime: Optional[Any] = None):
        """
        Инициализация менеджера модулей.
        
        Args:
            runtime: опциональный экземпляр CoreRuntime для логирования
        """
        self._modules: Dict[str, RuntimeModule] = {}
        self._runtime = runtime

    async def register(self, module: RuntimeModule) -> None:
        """
        Регистрирует модуль в менеджере.

        Args:
            module: экземпляр RuntimeModule

        Raises:
            ValueError: если модуль с таким именем уже зарегистрирован
        """
        module_name = module.name

        # Проверка уникальности имени (идемпотентность)
        if module_name in self._modules:
            # Если это тот же экземпляр — игнорируем (идемпотентность)
            if self._modules[module_name] is module:
                return
            # Если другой экземпляр — ошибка
            raise ValueError(
                f"Module '{module_name}' is already registered. "
                f"Use unregister() first or use a different name."
            )

        # Регистрируем модуль
        self._modules[module_name] = module

        # Вызываем register() модуля для регистрации в CoreRuntime
        await module.register()

    def unregister(self, module_name: str) -> None:
        """
        Отменяет регистрацию модуля.

        Args:
            module_name: имя модуля
        """
        if module_name in self._modules:
            del self._modules[module_name]

    def get_module(self, module_name: str) -> Optional[RuntimeModule]:
        """
        Получает модуль по имени.

        Args:
            module_name: имя модуля

        Returns:
            экземпляр RuntimeModule или None если не найден
        """
        return self._modules.get(module_name)

    def list_modules(self) -> List[str]:
        """
        Возвращает список зарегистрированных модулей.

        Returns:
            список имён модулей
        """
        return list(self._modules.keys())

    async def start_all(self) -> None:
        """
        Запускает все зарегистрированные модули.

        Вызывается при runtime.start().
        """
        for module in self._modules.values():
            try:
                await module.start()
            except Exception as e:
                # Не ломаем запуск других модулей при ошибке одного
                # Логируем ошибку для отладки
                try:
                    await log_error(
                        self._runtime,
                        f"Ошибка при запуске модуля '{module.name}': {e}",
                        component="module_manager",
                        module=module.name
                    )
                except Exception:
                    # Fallback на print если logger недоступен
                    print(f"[ModuleManager] Ошибка при запуске модуля '{module.name}': {e}", file=sys.stderr)

    async def stop_all(self) -> None:
        """
        Останавливает все зарегистрированные модули.

        Вызывается при runtime.stop().
        """
        for module in self._modules.values():
            try:
                await module.stop()
            except Exception as e:
                # Не ломаем остановку других модулей при ошибке одного
                # Логируем ошибку для отладки
                try:
                    await log_error(
                        self._runtime,
                        f"Ошибка при остановке модуля '{module.name}': {e}",
                        component="module_manager",
                        module=module.name
                    )
                except Exception:
                    # Fallback на print если logger недоступен
                    print(f"[ModuleManager] Ошибка при остановке модуля '{module.name}': {e}", file=sys.stderr)

    def clear(self) -> None:
        """Очищает все зарегистрированные модули."""
        self._modules.clear()

    async def register_builtin_modules(self, runtime: Any) -> None:
        """
        Регистрирует все встроенные модули из BUILTIN_MODULES.

        Args:
            runtime: экземпляр CoreRuntime (используется для создания модулей)
        """
        for module_name in BUILTIN_MODULES:
            try:
                await self._register_module_by_name(runtime, module_name)
            except Exception:
                # Не ломаем инициализацию при ошибках регистрации модуля
                pass

    async def _register_module_by_name(self, runtime: Any, module_name: str) -> None:
        """
        Регистрирует модуль по имени (обнаружение и создание экземпляра).

        Args:
            runtime: экземпляр CoreRuntime
            module_name: имя модуля (например, "automation")
        """
        # Проверяем, существует ли модуль
        module_path = f"modules.{module_name}"
        spec = importlib.util.find_spec(module_path)
        if spec is None:
            return

        # Импортируем модуль и ищем класс RuntimeModule
        try:
            # Все модули экспортируют класс через __init__.py
            module = importlib.import_module(module_path)
            module_class_name = f"{module_name.capitalize()}Module"
            module_class = getattr(module, module_class_name, None)

            if module_class is None or not issubclass(module_class, RuntimeModule):
                return

            # Создаём экземпляр и регистрируем
            module_instance = module_class(runtime)
            await self.register(module_instance)

        except Exception:
            # Ошибка импорта или регистрации - игнорируем
            pass
