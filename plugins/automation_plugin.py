"""
DEPRECATED: Этот плагин заменён модулем modules.automation.AutomationModule.

Оставлен для обратной совместимости.
Будет удалён в версии 1.0.0.

Вся доменная логика automation теперь в modules/automation/module.py.
AutomationModule регистрируется автоматически при создании CoreRuntime
через ModuleManager.

Этот плагин больше не нужен и может быть удалён.
"""
from plugins.base_plugin import BasePlugin, PluginMetadata


class AutomationPlugin(BasePlugin):
    """
    Тонкий адаптер для automation модуля.

    Регистрирует встроенный модуль automation при загрузке плагина.
    Это обеспечивает совместимость со старым кодом.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="automation",
            version="0.2.0",
            description="Shim-плагин для automation модуля (совместимость)",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """
        DEPRECATED: Automation теперь регистрируется автоматически через ModuleManager.

        Этот метод больше не выполняет никаких действий.
        Модуль automation регистрируется при создании CoreRuntime.
        """
        await super().on_load()
        # AutomationModule уже зарегистрирован через ModuleManager
        # Ничего делать не нужно

    async def on_start(self) -> None:
        """Запуск плагина - модуль уже зарегистрирован в on_load."""
        await super().on_start()

    async def on_stop(self) -> None:
        """Остановка плагина - модуль управляет своей подпиской самостоятельно."""
        await super().on_stop()

    async def on_unload(self) -> None:
        """Выгрузка плагина - очистка ссылок."""
        await super().on_unload()
        self.runtime = None
