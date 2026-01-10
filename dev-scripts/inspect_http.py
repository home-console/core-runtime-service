#!/usr/bin/env python3
import asyncio
import pkgutil
import importlib
import inspect
from pathlib import Path

from core.config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter
from core.base_plugin import BasePlugin

async def main():
    config = Config.from_env()
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    storage_adapter = SQLiteAdapter(config.db_path)
    await storage_adapter.initialize_schema()
    runtime = CoreRuntime(storage_adapter)

    plugins_dir = Path(__file__).parent / ".." / "plugins"
    for _finder, mod_name, _ispkg in pkgutil.iter_modules([str(plugins_dir)]):
        module_name = f"plugins.{mod_name}"
        try:
            module = importlib.import_module(module_name)
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                try:
                    if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                        plugin_instance = obj(runtime)
                        await runtime.plugin_manager.load_plugin(plugin_instance)
                except Exception as e:
                    print(f"skip class {obj} due to {e}")
                    continue
        except Exception as e:
            print(f"skip module {module_name} due to {e}")

    print("Loaded plugins:", runtime.plugin_manager.list_plugins())
    print("Registered HTTP endpoints:")
    for ep in runtime.http.list():
        print(f"  {ep.method} {ep.path} -> {ep.service}")

    print("Registered services (sample):")
    for name in ["oauth_yandex.get_status", "oauth_yandex.get_authorize_url", "oauth_yandex.exchange_code"]:
        print(name, await runtime.service_registry.has_service(name))

if __name__ == '__main__':
    asyncio.run(main())
