"""
Module Manager — runtime built-in modules manager.

Управляет жизненным циклом RuntimeModule:
- регистрация модулей
- запуск/остановка модулей
- гарантия уникальности имён

Делегирует работу специализированным компонентам:
- ModuleDiscovery — обнаружение и создание экземпляров
- ModuleDependencySorter — сортировка по зависимостям

КОНТРАКТ:
- Плагины не должны использовать ModuleManager напрямую
- Модули регистрируются через register_module_specs из bootstrap
"""

from typing import Any, Dict, List, Optional
import logging

from core.module_spec import ModuleSpec
from core.runtime.runtime_module import RuntimeModule
from core.module_discovery import ModuleDiscovery
from core.module_dependency_sorter import ModuleDependencySorter
from core.observability.logger_helper import error as log_error
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS, LOGGING_HELPER_ERRORS

logger = logging.getLogger(__name__)

# Re-export sub-components so callers can import from core.module or directly
__all__ = [
    "ModuleManager",
    "ModuleSpec",
    "ModuleDiscovery",
    "ModuleDependencySorter",
]


class ModuleManager:
    """
    Менеджер встроенных модулей Runtime.
    
    Управляет экземплярами RuntimeModule, гарантирует уникальность имён,
    обеспечивает идемпотентность регистрации.
    
    Делегирует работу:
    - ModuleDiscovery — обнаружение и создание экземпляров
    - ModuleDependencySorter — топологическая сортировка
    """

    def __init__(self, runtime: Optional[Any] = None, *, module_path_prefix: str = "modules"):
        """
        Инициализация менеджера модулей.
        
        Args:
            runtime: опциональный экземпляр CoreRuntime для логирования
            module_path_prefix: префикс пути для импорта модулей
        """
        self._modules: Dict[str, RuntimeModule] = {}
        self._runtime = runtime
        self._required_names: set = set()
        
        # Делегирование специализированным компонентам
        self._discovery = ModuleDiscovery(module_path_prefix=module_path_prefix)
        self._sorter = ModuleDependencySorter()

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
            except BEST_EFFORT_BACKGROUND_ERRORS as e:
                if is_required:
                    failed_required.append((module.name, str(e)))
                else:
                    # Для OPTIONAL модулей логируем, но не останавливаем runtime
                    # Exception handling is intentional for optional modules
                    try:
                        await log_error(
                            self._runtime,
                            f"Ошибка при запуске optional модуля '{module.name}': {e}",
                            component="module_manager",
                            module=module.name
                        )
                    except LOGGING_HELPER_ERRORS:
                        # Fallback на logging если logger недоступен
                        logger.exception(
                            "[ModuleManager] Ошибка при запуске optional модуля '%s': %s",
                            module.name, e
                        )
        
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
            except BEST_EFFORT_BACKGROUND_ERRORS as e:
                # Не ломаем остановку других модулей при ошибке одного
                # Логируем ошибку для отладки
                try:
                    await log_error(
                        self._runtime,
                        f"Ошибка при остановке модуля '{module.name}': {e}",
                        component="module_manager",
                        module=module.name
                    )
                except LOGGING_HELPER_ERRORS:
                    # Fallback на logging если logger недоступен
                    logger.exception(
                        "[ModuleManager] Ошибка при остановке модуля '%s': %s",
                        module.name, e
                    )

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
        # Ensure deterministic module order based on declared dependencies.
        specs = self._order_specs_by_dependencies(specs)

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
                    except LOGGING_HELPER_ERRORS:
                        logger.exception(
                            "[ModuleManager] Ошибка при регистрации optional модуля '%s': %s",
                            module_spec.name, e
                        )
            except BEST_EFFORT_BACKGROUND_ERRORS as e:
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
                    except LOGGING_HELPER_ERRORS:
                        logger.exception(
                            "[ModuleManager] Неожиданная ошибка при регистрации optional модуля '%s': %s",
                            module_spec.name, e
                        )

        if failed_required:
            failed_names = [name for name, _ in failed_required]
            errors = "\n".join(f"  - {name}: {error}" for name, error in failed_required)
            raise RuntimeError(
                f"Failed to register required modules: {failed_names}\n"
                f"Errors:\n{errors}\n"
                f"Runtime cannot start without required modules."
            )

    def _order_specs_by_dependencies(
        self, specs: List[ModuleSpec]
    ) -> List[ModuleSpec]:
        """
        Переставить specs так, чтобы зависимости гарантировали корректный порядок.
        
        Делегирует ModuleDependencySorter.
        
        Args:
            specs: список спецификаций модулей
            
        Returns:
            Отсортированный список спецификаций
            
        Raises:
            RuntimeError: если обнаружен цикл или неразрешённая зависимость
        """
        return self._sorter.order_by_dependencies(specs)

    async def _register_module_by_name(self, runtime: Any, module_name: str, required: bool = True) -> None:
        """
        Зарегистрировать модуль по имени (обнаружение и создание экземпляра).
        
        Делегирует ModuleDiscovery для обнаружения/создания, затем регистрирует локально.
        
        Args:
            runtime: экземпляр CoreRuntime
            module_name: имя модуля
            required: является ли модуль обязательным
            
        Raises:
            RuntimeError: если required=True и модуль не найден/не создан
        """
        # Делегируем обнаружение и создание
        module_instance = await self._discovery.register_module_by_name(
            runtime=runtime,
            module_name=module_name,
            required=required
        )
        
        if module_instance is None:
            # Optional module not found - that's OK
            return
        
        # Регистрируем локально
        try:
            await self.register(module_instance)
        except ValueError as e:
            # Двойная регистрация - это уже обработано в register()
            raise RuntimeError(f"Module '{module_name}' registration failed: {e}")
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            if required:
                raise RuntimeError(f"Failed to register required module '{module_name}': {e}")
            return
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            logger.warning(
                "ModuleManager._register_module_by_name: unexpected registration error for '%s': %s",
                module_name,
                e,
                exc_info=True,
            )
            if required:
                raise RuntimeError(f"Failed to register required module '{module_name}': {e}")
            return
