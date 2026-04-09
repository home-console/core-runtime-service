"""
Контрактные тесты для RuntimeModule и ModuleManager.

Проверяют соответствие реализации формальному контракту:
- docs/07-RUNTIME-MODULE-CONTRACT.md
"""

import pytest

from core.runtime.runtime import CoreRuntime
from core.runtime import CoreRuntime
from core.runtime.runtime_module import RuntimeModule
from main import APP_MODULES


class DummyModule(RuntimeModule):
    """Dummy модуль для тестирования контракта."""
    
    def __init__(self, runtime, name="dummy", required=True):
        super().__init__(runtime)
        self._name = name
        self._required = required
        self.lifecycle_calls = []
        self.register_called = False
        self.start_called = False
        self.stop_called = False
    
    @property
    def name(self) -> str:
        return self._name
    
    async def register(self) -> None:
        self.register_called = True
        self.lifecycle_calls.append("register")
    
    async def start(self) -> None:
        self.start_called = True
        self.lifecycle_calls.append("start")
    
    async def stop(self) -> None:
        self.stop_called = True
        self.lifecycle_calls.append("stop")


class FailingRegisterModule(DummyModule):
    """Модуль, который падает в register()."""
    
    async def register(self) -> None:
        # Не вызываем super().register(), чтобы lifecycle_calls не обновлялся
        # Просто устанавливаем флаг и падаем
        self.register_called = True
        raise RuntimeError("register failed")


class FailingStartModule(DummyModule):
    """Модуль, который падает в start()."""
    
    async def start(self) -> None:
        await super().start()
        raise RuntimeError("start failed")


class FailingStopModule(DummyModule):
    """Модуль, который падает в stop()."""
    
    async def stop(self) -> None:
        await super().stop()
        raise RuntimeError("stop failed")


@pytest.mark.asyncio
async def test_app_modules_registration_via_bootstrap(memory_adapter):
    """Тест: модули приложения регистрируются через bootstrap, затем runtime.start()."""
    runtime = CoreRuntime(memory_adapter)
    assert len(runtime.module_manager.list_modules()) == 0

    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
    await runtime.start()

    registered_modules = runtime.module_manager.list_modules()
    for spec in APP_MODULES:
        if spec.required:
            assert spec.name in registered_modules, f"Required module '{spec.name}' not registered"
            module = runtime.module_manager.get_module(spec.name)
            assert module is not None
            assert module.name == spec.name

    await runtime.stop()


@pytest.mark.asyncio
async def test_lifecycle_order_register_start_stop(memory_adapter):
    """Тест: порядок lifecycle - register → start → stop."""
    runtime = CoreRuntime(memory_adapter)
    manager = runtime.module_manager
    
    # Создаём dummy модуль
    module = DummyModule(runtime, "test_lifecycle")
    
    # Регистрируем модуль
    await manager.register(module)
    assert module.register_called is True
    assert module.start_called is False
    assert module.stop_called is False
    assert module.lifecycle_calls == ["register"]
    
    # Запускаем модуль
    await manager.start_all()
    assert module.start_called is True
    assert module.stop_called is False
    assert module.lifecycle_calls == ["register", "start"]
    
    # Останавливаем модуль
    await manager.stop_all()
    assert module.stop_called is True
    assert module.lifecycle_calls == ["register", "start", "stop"]


@pytest.mark.asyncio
async def test_required_module_fails_register_runtime_not_starts(memory_adapter):
    """Тест: REQUIRED модуль падает в register() → runtime не стартует."""
    runtime = CoreRuntime(memory_adapter)
    manager = runtime.module_manager
    
    # Создаём failing REQUIRED модуль
    failing_module = FailingRegisterModule(runtime, "failing_required", required=True)
    
    # Регистрируем модуль напрямую - register() модуля должен упасть
    # В коде ModuleManager.register() модуль добавляется в _modules ПЕРЕД вызовом module.register()
    # Если register() падает, исключение пробрасывается, но модуль уже в _modules
    # Это нормальное поведение - исключение пробрасывается, но модуль остаётся зарегистрированным
    with pytest.raises(RuntimeError, match="register failed"):
        await manager.register(failing_module)
    
    # После ошибки register() модуль не должен считаться зарегистрированным.
    assert "failing_required" not in manager.list_modules()
    assert failing_module.register_called is True


@pytest.mark.asyncio
async def test_required_module_fails_start_runtime_not_starts(memory_adapter):
    """Тест: REQUIRED модуль падает в start() → runtime не стартует."""
    runtime = CoreRuntime(memory_adapter)
    manager = runtime.module_manager
    
    # Модуль считается required, если его имя в _required_names (задаётся приложением при register_module_specs)
    failing_module = FailingStartModule(runtime, "failing_required", required=True)
    await manager.register(failing_module)
    manager._required_names.add("failing_required")

    with pytest.raises(RuntimeError, match="Failed to start required modules"):
        await manager.start_all()

    assert failing_module.register_called is True
    assert failing_module.start_called is True


@pytest.mark.asyncio
async def test_optional_module_fails_runtime_starts(memory_adapter):
    """Тест: OPTIONAL модуль падает → runtime стартует."""
    runtime = CoreRuntime(memory_adapter)
    manager = runtime.module_manager
    
    # Создаём failing OPTIONAL модуль
    failing_module = FailingStartModule(runtime, "failing_optional", required=False)
    
    # Регистрируем модуль
    await manager.register(failing_module)
    
    # Запускаем - не должен упасть (OPTIONAL модули могут фейлиться)
    await manager.start_all()
    
    # Проверяем, что модуль был зарегистрирован и попытка запуска была
    assert failing_module.register_called is True
    assert failing_module.start_called is True
    
    # Runtime должен быть запущен (нет RuntimeError)


@pytest.mark.asyncio
async def test_stop_called_even_if_start_failed(memory_adapter):
    """Тест: stop() вызывается даже если start() упал."""
    runtime = CoreRuntime(memory_adapter)
    manager = runtime.module_manager
    
    # Создаём модуль, который падает в start()
    failing_module = FailingStartModule(runtime, "failing_start", required=True)
    
    # Регистрируем модуль
    await manager.register(failing_module)
    
    # Пытаемся запустить - упадёт
    try:
        await manager.start_all()
    except RuntimeError:
        pass
    
    # Останавливаем - stop() должен быть вызван даже при неудачном старте
    await manager.stop_all()
    
    # Проверяем, что stop() был вызван
    assert failing_module.stop_called is True


@pytest.mark.asyncio
async def test_stop_errors_do_not_stop_other_modules(memory_adapter):
    """Тест: ошибки в stop() не останавливают остановку других модулей."""
    runtime = CoreRuntime(memory_adapter)
    manager = runtime.module_manager
    
    # Создаём два модуля: один падает в stop(), другой нет
    failing_module = FailingStopModule(runtime, "failing_stop")
    normal_module = DummyModule(runtime, "normal")
    
    # Регистрируем оба модуля
    await manager.register(failing_module)
    await manager.register(normal_module)
    
    # Запускаем
    await manager.start_all()
    
    # Останавливаем - не должен упасть, оба stop() должны быть вызваны
    await manager.stop_all()
    
    # Проверяем, что оба stop() были вызваны
    assert failing_module.stop_called is True
    assert normal_module.stop_called is True


@pytest.mark.asyncio
async def test_register_idempotent(memory_adapter):
    """Тест: register() идемпотентен (повторные вызовы безопасны)."""
    runtime = CoreRuntime(memory_adapter)
    manager = runtime.module_manager
    
    module = DummyModule(runtime, "idempotent")
    
    # Первая регистрация
    await manager.register(module)
    assert len(manager.list_modules()) == 1
    assert module.register_called is True
    register_count = len(module.lifecycle_calls)
    
    # Повторная регистрация того же экземпляра - должна быть идемпотентной
    await manager.register(module)
    assert len(manager.list_modules()) == 1
    # register() модуля не должен вызываться повторно
    assert len(module.lifecycle_calls) == register_count


@pytest.mark.asyncio
async def test_app_modules_order_logger_first():
    """Тест: logger должен быть первым в APP_MODULES приложения."""
    assert len(APP_MODULES) > 0
    assert APP_MODULES[0].name == "logger", "logger must be first in APP_MODULES"
    assert APP_MODULES[0].required is True, "logger must be REQUIRED"


@pytest.mark.asyncio
async def test_app_modules_spec():
    """Тест: у APP_MODULES задан флаг required; хотя бы один REQUIRED."""
    required_names = [s.name for s in APP_MODULES if s.required]
    assert len(required_names) >= 1, "At least one app module must be REQUIRED"
    assert "logger" in required_names, "logger must be REQUIRED"


@pytest.mark.asyncio
async def test_module_manager_check_required_modules(memory_adapter):
    """Тест: check_required_modules_registered() проверяет наличие всех REQUIRED модулей."""
    runtime = CoreRuntime(memory_adapter)
    manager = runtime.module_manager

    # Когда _required_names задан, но модуль не зарегистрирован — должна быть ошибка
    manager._required_names.add("missing_required")
    with pytest.raises(RuntimeError, match="Required modules not registered"):
        manager.check_required_modules_registered()
    manager._required_names.clear()

    # После bootstrap все required модули зарегистрированы — проверка проходит
    await runtime.module_manager.register_module_specs(runtime, APP_MODULES)
    manager.check_required_modules_registered()

    await runtime.start()
    await runtime.stop()
