"""
Application Bootstrap — сборка продукта поверх Core Runtime.

Core не знает, какие модули загружать. Приложение задаёт список модулей здесь.
Один Core → много приложений (разные bootstrap с разными наборами модулей).
"""

from typing import Any, List

from core.module_manager import ModuleSpec

# Список модулей приложения Home Console.
# Logger и request_logger — первыми (инфраструктура логирования).
# product_api — опциональный (BFF для пользовательских клиентов).
APP_MODULES: List[ModuleSpec] = [
    ModuleSpec("logger", required=True),
    ModuleSpec("request_logger", required=True),
    ModuleSpec("api", required=True),
    ModuleSpec("admin", required=True),
    ModuleSpec("auth", required=True),
    ModuleSpec("operations", required=True),
    # Execution Layer (D3): policy + backends, Core об этом не знает.
    ModuleSpec("execution", required=True),
    ModuleSpec("integrations", required=True),
    ModuleSpec("devices", required=True),
    # Automation/Flows — доменный оркестратор поверх EventBus+Operations.
    # НЕ часть Core и должен быть удаляемым без остановки runtime.
    ModuleSpec("automation", required=False),
    ModuleSpec("presence", required=True),
    ModuleSpec("product_api", required=False),
]


class ApplicationBootstrap:
    """
    Регистрирует модули приложения в Core Runtime.
    Core только предоставляет среду; что загружать — решает приложение.
    """

    def __init__(self, modules: List[ModuleSpec]):
        self.modules = modules

    async def start(self, runtime: Any) -> None:
        """
        Регистрирует модули в runtime (до вызова runtime.start()).
        После этого runtime.start() проверит required и запустит модули и плагины.
        """
        await runtime.module_manager.register_module_specs(runtime, self.modules)
