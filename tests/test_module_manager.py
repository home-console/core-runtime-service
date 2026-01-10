"""
Тесты для ModuleManager.
"""

import pytest

from core.module_manager import ModuleManager
from core.runtime_module import RuntimeModule


class TestModule(RuntimeModule):
    """Тестовый модуль для проверки ModuleManager."""

    def __init__(self, runtime, name="test"):
        super().__init__(runtime)
        self._name = name
        self.registered = False
        self.started = False
        self.stopped = False

    @property
    def name(self) -> str:
        return self._name

    def register(self) -> None:
        self.registered = True

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_register_module():
    """Тест регистрации модуля."""
    manager = ModuleManager()
    runtime = object()
    module = TestModule(runtime, "test_module")

    manager.register(module)

    assert "test_module" in manager.list_modules()
    assert manager.get_module("test_module") is module
    assert module.registered is True


@pytest.mark.asyncio
async def test_register_duplicate_raises():
    """Тест, что регистрация модуля с существующим именем вызывает ошибку."""
    manager = ModuleManager()
    runtime = object()
    module1 = TestModule(runtime, "test")
    module2 = TestModule(runtime, "test")

    manager.register(module1)

    with pytest.raises(ValueError, match="already registered"):
        manager.register(module2)


@pytest.mark.asyncio
async def test_register_idempotent():
    """Тест идемпотентности регистрации."""
    manager = ModuleManager()
    runtime = object()
    module = TestModule(runtime, "test")

    # Первая регистрация
    manager.register(module)
    assert len(manager.list_modules()) == 1

    # Повторная регистрация того же экземпляра - игнорируется
    manager.register(module)
    assert len(manager.list_modules()) == 1


@pytest.mark.asyncio
async def test_unregister_module():
    """Тест отмены регистрации модуля."""
    manager = ModuleManager()
    runtime = object()
    module = TestModule(runtime, "test")

    manager.register(module)
    assert "test" in manager.list_modules()

    manager.unregister("test")
    assert "test" not in manager.list_modules()
    assert manager.get_module("test") is None


@pytest.mark.asyncio
async def test_start_all_modules():
    """Тест запуска всех модулей."""
    manager = ModuleManager()
    runtime = object()
    module1 = TestModule(runtime, "module1")
    module2 = TestModule(runtime, "module2")

    manager.register(module1)
    manager.register(module2)

    await manager.start_all()

    assert module1.started is True
    assert module2.started is True


@pytest.mark.asyncio
async def test_stop_all_modules():
    """Тест остановки всех модулей."""
    manager = ModuleManager()
    runtime = object()
    module1 = TestModule(runtime, "module1")
    module2 = TestModule(runtime, "module2")

    manager.register(module1)
    manager.register(module2)

    await manager.start_all()
    await manager.stop_all()

    assert module1.stopped is True
    assert module2.stopped is True


@pytest.mark.asyncio
async def test_start_all_handles_errors():
    """Тест, что ошибка в одном модуле не ломает запуск других."""
    manager = ModuleManager()
    runtime = object()

    class FailingModule(TestModule):
        async def start(self) -> None:
            raise RuntimeError("Start failed")

    module1 = TestModule(runtime, "module1")
    module2 = FailingModule(runtime, "module2")
    module3 = TestModule(runtime, "module3")

    manager.register(module1)
    manager.register(module2)
    manager.register(module3)

    # Запуск не должен упасть, даже если module2 упал
    await manager.start_all()

    assert module1.started is True
    assert module3.started is True


@pytest.mark.asyncio
async def test_stop_all_handles_errors():
    """Тест, что ошибка в одном модуле не ломает остановку других."""
    manager = ModuleManager()
    runtime = object()

    class FailingModule(TestModule):
        async def stop(self) -> None:
            raise RuntimeError("Stop failed")

    module1 = TestModule(runtime, "module1")
    module2 = FailingModule(runtime, "module2")
    module3 = TestModule(runtime, "module3")

    manager.register(module1)
    manager.register(module2)
    manager.register(module3)

    await manager.start_all()
    # Остановка не должна упасть, даже если module2 упал
    await manager.stop_all()

    assert module1.stopped is True
    assert module3.stopped is True


@pytest.mark.asyncio
async def test_clear_modules():
    """Тест очистки всех модулей."""
    manager = ModuleManager()
    runtime = object()
    module1 = TestModule(runtime, "module1")
    module2 = TestModule(runtime, "module2")

    manager.register(module1)
    manager.register(module2)
    assert len(manager.list_modules()) == 2

    manager.clear()
    assert len(manager.list_modules()) == 0


@pytest.mark.asyncio
async def test_register_builtin_modules(memory_adapter):
    """Тест автоматической регистрации встроенных модулей."""
    from core.runtime import CoreRuntime

    runtime = CoreRuntime(memory_adapter)
    manager = runtime.module_manager

    # Модули должны быть зарегистрированы автоматически
    modules = manager.list_modules()
    assert "devices" in modules
    assert "automation" in modules
    assert "presence" in modules

    # Проверяем, что модули действительно зарегистрированы
    devices_module = manager.get_module("devices")
    assert devices_module is not None
    assert devices_module.name == "devices"

    automation_module = manager.get_module("automation")
    assert automation_module is not None
    assert automation_module.name == "automation"

    presence_module = manager.get_module("presence")
    assert presence_module is not None
    assert presence_module.name == "presence"
