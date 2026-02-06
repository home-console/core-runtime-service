"""
Reference plugin — эталонный плагин (SDK v0).

Импортирует только sdk. Регистрирует 1 сервис и 1 operation.
Не знает admin, ui, домены.
"""

from sdk import BasePlugin, PluginMetadata, PluginRuntime


class ExamplePlugin(BasePlugin):
    """Канонический пример плагина по контракту SDK."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="example_plugin",
            version="1.0.0",
            description="Reference plugin (SDK v0)",
            is_integration=False,
            integration_flags=[],
            capabilities_provided=[],
            capabilities_required=[],
        )

    async def on_load(self) -> None:
        rt: PluginRuntime = self.runtime
        # Регистрация одного сервиса
        async def ping(_payload: object = None) -> dict:
            return {"ok": True, "plugin": self.metadata.name}
        await rt.service_registry.register("example_plugin.ping", ping)
        # Регистрация одного handler операции
        if hasattr(rt, "operations") and hasattr(rt.operations, "register_handler"):
            async def handle_example_ping(_params: dict) -> dict:
                return {"done": True}
            await rt.operations.register_handler("example.ping", handle_example_ping)

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass

    async def on_unload(self) -> None:
        pass
