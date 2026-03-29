"""
Module Manager — runtime built-in modules manager .

Управляет жизненным циклом RuntimeModule:
- обнаружение и регистрация модулей
- запуск/остановка модулей
- гарантия уникальности имён
"""

from typing import Any, Dict, List, Optional
import sys
import importlib
import importlib.util

from dataclasses import dataclass

from core.runtime.runtime_module import RuntimeModule
from core.observability.logger_helper import error as log_error


@dataclass
class ModuleSpec:
    """Спецификация модуля с флагом обязательности. Используется на уровне приложения (bootstrap)."""
    name: str
    required: bool = True


class ModuleManager:
    """
    Менеджер встроенных модулей Runtime.

    Управляет экземплярами RuntimeModule, гарантирует уникальность имён,
    обеспечивает идемпотентность регистрации.
    """

    def __init__(self, runtime: Optional[Any] = None, *, module_path_prefix: str = "modules"):
        """
        Инициализация менеджера модулей.
        
        Args:
            runtime: опциональный экземпляр CoreRuntime для логирования
        """
        self._modules: Dict[str, RuntimeModule] = {}
        self._runtime = runtime
        self._module_path_prefix = module_path_prefix or "modules"
        # Имена модулей, помеченных как required при последнем register_module_specs (задаётся приложением)
        self._required_names: set = set()

    async def register(self, module: RuntimeModule) -> None:
        """
        Регистрирует модуль в менеджере.

        КОНТРАКТ IDEMPOTENCY:
        - Один экземпляр модуля может быть зарегистрирован только один раз
        - Повторная регистрация того же экземпляра игнорируется (идемпотентность)
        - Двойная регистрация разных экземпляров с одним именем запрещена

        КОНТРАКТ LIFECYCLE:
        - register() модуля вызывается ровно один раз при регистрации
        - Порядок: register() → start() → stop()

        Args:
            module: экземпляр RuntimeModule

        Raises:
            ValueError: если модуль с таким именем уже зарегистрирован (другой экземпляр)
        """
        module_name = module.name

        # Проверка уникальности имени (идемпотентность)
        if module_name in self._modules:
            # Если это тот же экземпляр — игнорируем (идемпотентность)
            if self._modules[module_name] is module:
                return
            # Если другой экземпляр — ошибка (защита от двойной регистрации)
            raise ValueError(
                f"Module '{module_name}' is already registered. "
                f"Use unregister() first or use a different name."
            )

        # Вызываем register() модуля ДО добавления в реестр.
        # Если register() упадёт — модуль не попадёт в _modules и
        # не будет числиться как "зарегистрированный" (zombie-state).
        await module.register()

        # Только после успешной инициализации добавляем в реестр
        self._modules[module_name] = module

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

    def get_required_modules(self) -> List[str]:
        """
        Возвращает список имён обязательных модулей (заданных при последнем register_module_specs).
        
        Returns:
            список имён REQUIRED модулей
        """
        return list(self._required_names)

    def check_required_modules_registered(self) -> None:
        """
        Проверяет, что все REQUIRED модули зарегистрированы.
        
        Raises:
            RuntimeError: если какой-то REQUIRED модуль не зарегистрирован
        """
        missing = [n for n in self._required_names if n not in self._modules]
        if missing:
            raise RuntimeError(
                f"Required modules not registered: {missing}. "
                f"Runtime cannot start without required modules. "
                f"Registered modules: {self.list_modules()}"
            )

    async def start_all(self) -> None:
        """
        Запускает все зарегистрированные модули.

        REQUIRED модули должны успешно запуститься, иначе RuntimeError.
        OPTIONAL модули могут фейлиться без остановки runtime.

        Вызывается при runtime.start().

        Raises:
            RuntimeError: если REQUIRED модуль упал в start()
        """
        failed_required = []
        
        for module in self._modules.values():
            is_required = module.name in self._required_names
            try:
                await module.start()
            except Exception as e:
                if is_required:
                    failed_required.append((module.name, str(e)))
                else:
                    # Для OPTIONAL модулей логируем, но не останавливаем runtime
                    try:
                        await log_error(
                            self._runtime,
                            f"Ошибка при запуске optional модуля '{module.name}': {e}",
                            component="module_manager",
                            module=module.name
                        )
                    except Exception:
                        # Fallback на print если logger недоступен
                        print(f"[ModuleManager] Ошибка при запуске optional модуля '{module.name}': {e}", file=sys.stderr)
        
        if failed_required:
            failed_names = [name for name, _ in failed_required]
            errors = "\n".join(f"  - {name}: {error}" for name, error in failed_required)
            raise RuntimeError(
                f"Failed to start required modules: {failed_names}\n"
                f"Errors:\n{errors}\n"
                f"Runtime cannot start without required modules."
            )

    async def stop_all(self) -> None:
        """
        Останавливает все зарегистрированные модули.

        КОНТРАКТ LIFECYCLE:
        - Вызывается при runtime.stop()
        - Вызывается даже при частичном старте (если start() упал)
        - stop() вызывается для всех зарегистрированных модулей

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
        """Очищает все зарегистрированные модули и список required."""
        self._modules.clear()
        self._required_names.clear()

    async def register_module_specs(self, runtime: Any, specs: List[ModuleSpec]) -> None:
        """
        Регистрирует модули по списку спецификаций (вызывается приложением / bootstrap).

        Core не знает, какие модули загружать — список передаётся снаружи.

        ИДЕМПОТЕНТНОСТЬ:
        - Если модуль уже зарегистрирован, он пропускается.

        REQUIRED модули должны быть успешно зарегистрированы, иначе RuntimeError.
        OPTIONAL модули могут быть пропущены при ошибках.

        Args:
            runtime: экземпляр CoreRuntime
            specs: список ModuleSpec (определяется приложением)

        Raises:
            RuntimeError: если REQUIRED модуль не найден или не зарегистрировался
        """
        self._required_names = {s.name for s in specs if s.required}
        failed_required = []

        for module_spec in specs:
            if module_spec.name in self._modules:
                continue
            try:
                await self._register_module_by_name(runtime, module_spec.name, module_spec.required)
            except RuntimeError as e:
                if module_spec.required:
                    failed_required.append((module_spec.name, str(e)))
                else:
                    try:
                        await log_error(
                            self._runtime,
                            f"Ошибка при регистрации optional модуля '{module_spec.name}': {e}",
                            component="module_manager",
                            module=module_spec.name
                        )
                    except Exception:
                        print(f"[ModuleManager] Ошибка при регистрации optional модуля '{module_spec.name}': {e}", file=sys.stderr)
            except Exception as e:
                if module_spec.required:
                    failed_required.append((module_spec.name, f"Unexpected error: {e}"))
                else:
                    try:
                        await log_error(
                            self._runtime,
                            f"Неожиданная ошибка при регистрации optional модуля '{module_spec.name}': {e}",
                            component="module_manager",
                            module=module_spec.name
                        )
                    except Exception:
                        print(f"[ModuleManager] Неожиданная ошибка при регистрации optional модуля '{module_spec.name}': {e}", file=sys.stderr)

        if failed_required:
            failed_names = [name for name, _ in failed_required]
            errors = "\n".join(f"  - {name}: {error}" for name, error in failed_required)
            raise RuntimeError(
                f"Failed to register required modules: {failed_names}\n"
                f"Errors:\n{errors}\n"
                f"Runtime cannot start without required modules."
            )

    async def _discover_module(self, module_name: str) -> Optional[type]:
        """
        Обнаруживает класс RuntimeModule по имени модуля.
        
        Изолированный метод для будущего расширения (например, RemoteModuleManager).
        
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
            # Все модули экспортируют класс через __init__.py
            module = importlib.import_module(module_path)
            # Преобразуем имя модуля в camelCase для имени класса
            # Например: "request_logger" -> "RequestLogger"
            parts = module_name.split("_")
            camel_case_name = "".join(part.capitalize() for part in parts)
            module_class_name = f"{camel_case_name}Module"
            module_class = getattr(module, module_class_name, None)

            if module_class is None:
                return None
                
            if not issubclass(module_class, RuntimeModule):
                raise RuntimeError(
                    f"Module class '{module_class_name}' in '{module_path}' "
                    f"is not a subclass of RuntimeModule"
                )

            return module_class
        except ImportError as e:
            raise RuntimeError(f"Failed to import module '{module_path}': {e}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error discovering module '{module_name}': {e}")

    async def _create_module_instance(self, runtime: Any, module_class: type) -> RuntimeModule:
        """
        Создаёт экземпляр RuntimeModule.
        
        Изолированный метод для будущего расширения (например, RemoteModuleManager).
        
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
        except Exception as e:
            raise RuntimeError(f"Failed to create module instance: {e}")

    async def _register_module_by_name(self, runtime: Any, module_name: str, required: bool = True) -> None:
        """
        Регистрирует модуль по имени (обнаружение и создание экземпляра).

        Args:
            runtime: экземпляр CoreRuntime
            module_name: имя модуля (например, "automation")
            required: является ли модуль обязательным

        Raises:
            RuntimeError: если required=True и модуль не найден, не импортирован или не является RuntimeModule
        """
        # Обнаружение модуля (изолированный метод для будущего remote-модулей)
        module_class = await self._discover_module(module_name)
        
        if module_class is None:
            if required:
                raise RuntimeError(
                    f"Required module '{module_name}' not found. "
                    f"Expected module at '{self._module_path_prefix}.{module_name}' "
                    f"with class '{module_name.capitalize()}Module'"
                )
            # Для optional модулей просто возвращаемся
            return

        # Создание экземпляра (изолированный метод для будущего remote-модулей)
        try:
            module_instance = await self._create_module_instance(runtime, module_class)
        except RuntimeError:
            # Пробрасываем RuntimeError дальше
            raise
        except Exception as e:
            if required:
                raise RuntimeError(f"Failed to create instance of required module '{module_name}': {e}")
            # Для optional модулей игнорируем ошибки создания
            return

        # Регистрация модуля
        try:
            await self.register(module_instance)
        except ValueError as e:
            # Двойная регистрация - это уже обработано в register()
            raise RuntimeError(f"Module '{module_name}' registration failed: {e}")
        except Exception as e:
            if required:
                raise RuntimeError(f"Failed to register required module '{module_name}': {e}")
            # Для optional модулей игнорируем ошибки регистрации
