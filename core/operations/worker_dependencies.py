"""
WorkerDependencies — формальный интерфейс зависимостей для OperationWorker.

Вместо чтения через __dict__ и getattr, используем явный контракт:
- hooks — execution hooks
- action_dispatcher — диспетчер действий
- action_resolver — разрешитель действий
- operation_source — источник операций
- event_bus — шина событий

Это устраняет проблему C3:
- C3: OperationWorker читает контракт через __dict__ и getattr
"""

from typing import Any, Callable, Optional, Protocol, runtime_checkable


@runtime_checkable
class ExecutionHooks(Protocol):
    """Протокол для execution hooks."""
    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Выполнить hooks."""
        ...


@runtime_checkable
class ActionDispatcher(Protocol):
    """Протокол для action dispatcher."""
    def dispatch(self, *args: Any, **kwargs: Any) -> Any:
        """Диспетчеризировать действие."""
        ...


@runtime_checkable
class ActionResolver(Protocol):
    """Протокол для action resolver."""
    def resolve(self, *args: Any, **kwargs: Any) -> Any:
        """Разрешить действие."""
        ...


@runtime_checkable
class OperationSource(Protocol):
    """Протокол для operation source."""
    def get_runnable(self, *args: Any, **kwargs: Any) -> Any:
        """Получить исполняемую операцию."""
        ...


@runtime_checkable
class EventBus(Protocol):
    """Протокол для event bus."""
    def subscribe(self, *args: Any, **kwargs: Any) -> Any:
        """Подписаться на событие."""
        ...


class WorkerDependencies:
    """
    Формальные зависимости для OperationWorker.

    Предоставляет явный контракт вместо чтения через __dict__/getattr.

    Атрибуты:
        hooks: execution hooks
        action_dispatcher: диспетчер действий
        action_resolver: разрешитель действий
        operation_source: источник операций
        event_bus: шина событий
    """

    def __init__(
        self,
        hooks: Optional[ExecutionHooks] = None,
        action_dispatcher: Optional[ActionDispatcher] = None,
        action_resolver: Optional[ActionResolver] = None,
        operation_source: Optional[OperationSource] = None,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Инициализация зависимостей worker.

        Args:
            hooks: execution hooks
            action_dispatcher: диспетчер действий
            action_resolver: разрешитель действий
            operation_source: источник операций
            event_bus: шина событий
        """
        self._hooks = hooks
        self._action_dispatcher = action_dispatcher
        self._action_resolver = action_resolver
        self._operation_source = operation_source
        self._event_bus = event_bus

    @property
    def hooks(self) -> Optional[ExecutionHooks]:
        """Получить execution hooks."""
        return self._hooks

    @property
    def action_dispatcher(self) -> Optional[ActionDispatcher]:
        """Получить action dispatcher."""
        return self._action_dispatcher

    @property
    def action_resolver(self) -> Optional[ActionResolver]:
        """Получить action resolver."""
        return self._action_resolver

    @property
    def operation_source(self) -> Optional[OperationSource]:
        """Получить operation source."""
        return self._operation_source

    @property
    def event_bus(self) -> Optional[EventBus]:
        """Получить event bus."""
        return self._event_bus

    @classmethod
    def from_runtime(cls, runtime: Any) -> "WorkerDependencies":
        """
        Создать WorkerDependencies из runtime.

        Args:
            runtime: экземпляр CoreRuntime или совместимый объект

        Returns:
            Экземпляр WorkerDependencies
        """
        return cls(
            hooks=getattr(runtime, "hooks", None),
            action_dispatcher=getattr(runtime, "action_dispatcher", None),
            action_resolver=getattr(runtime, "action_resolver", None),
            operation_source=getattr(runtime, "operation_source", None),
            event_bus=getattr(runtime, "event_bus", None),
        )

    @classmethod
    def noop(cls) -> "WorkerDependencies":
        """
        Создать WorkerDependencies с no-op реализациями.

        Returns:
            Экземпляр WorkerDependencies с no-op компонентами
        """
        from core.operations.runtime_contract import (
            NoopExecutionHooks,
            NoopActionDispatcher,
            PassThroughActionResolver,
            NoopOperationSource,
        )

        return cls(
            hooks=NoopExecutionHooks(),
            action_dispatcher=NoopActionDispatcher(),
            action_resolver=PassThroughActionResolver(),
            operation_source=NoopOperationSource(),
            event_bus=None,
        )
