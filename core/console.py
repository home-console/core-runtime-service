"""
Интерактивный и неинтерактивный CLI-адаптер для Core Runtime.

Перенесён в `core/` — обновлены пути к плагинам относительно корня проекта.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.config import Config
from core.runtime import CoreRuntime
from core.storage_factory import create_storage_adapter
from core.http_registry import HttpEndpoint


async def _auto_load_plugins(runtime: CoreRuntime) -> None:
    """Авто сканирование каталога `plugins/` в корне проекта и загрузка классов-наследников BasePlugin."""
    await runtime.plugin_manager.auto_load_plugins()


def _match_endpoint(path: str, endpoints: List[HttpEndpoint]) -> Optional[Tuple[HttpEndpoint, Dict[str, str]]]:
    if not path.startswith("/"):
        path = "/" + path

    for ep in endpoints:
        ep_parts = [p for p in ep.path.split("/") if p != ""]
        path_parts = [p for p in path.split("/") if p != ""]
        if len(ep_parts) != len(path_parts):
            continue
        params: Dict[str, str] = {}
        matched = True
        for a, b in zip(ep_parts, path_parts):
            if a.startswith("{") and a.endswith("}"):
                key = a[1:-1]
                params[key] = b
            else:
                if a != b:
                    matched = False
                    break
        if matched:
            return ep, params
    return None


async def _call_service(runtime: CoreRuntime, endpoint: HttpEndpoint, path_params: Dict[str, str]) -> Any:
    parts = [p for p in endpoint.path.split("/") if p != ""]
    ordered_values: List[Any] = []
    for p in parts:
        if p.startswith("{") and p.endswith("}"):
            key = p[1:-1]
            ordered_values.append(path_params.get(key))

    service_raw = endpoint.service
    service_name = service_raw
    extra_kwargs: Dict[str, Any] = {}
    if "?" in service_raw:
        service_name, qs = service_raw.split("?", 1)
        for part in qs.split("&"):
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                val: Any = v
                if v.lower() == "true":
                    val = True
                elif v.lower() == "false":
                    val = False
                extra_kwargs[k] = val
            else:
                extra_kwargs[part] = ""

    return await runtime.service_registry.call(service_name, *ordered_values, **extra_kwargs)


async def run_cli(argv: Optional[List[str]] = None, input_func: Callable[[str], str] = input, shutdown_on_exit: bool = True) -> CoreRuntime:
    config = Config.from_env()
    # Создать директорию для БД, если нужно (только для SQLite)
    if config.storage_type == "sqlite":
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    adapter = await create_storage_adapter(config)
    runtime = CoreRuntime(adapter)

    await _auto_load_plugins(runtime)

    await runtime.start()

    endpoints = runtime.http.list()

    if argv and len(argv) > 0:
        requested = "/" + "/".join(argv)
        match = _match_endpoint(requested, endpoints)
        if match is None:
            try:
                await runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"Не найден endpoint для пути: {requested}",
                    component="console"
                )
            except Exception:
                print(f"Не найден endpoint для пути: {requested}")
            if shutdown_on_exit:
                await runtime.shutdown()
            return runtime
        endpoint, params = match
        try:
            result = await _call_service(runtime, endpoint, params)
            # Для CLI выводим результат пользователю
            print("Результат:", result)
        except Exception as exc:
            try:
                await runtime.service_registry.call("logger.log", level="error", message=f"CLI call error: {exc}")
            except Exception:
                pass
        if shutdown_on_exit:
            await runtime.shutdown()
        return runtime

    print("Интерактивный режим CLI. Доступные действия:")
    for idx, ep in enumerate(endpoints):
        print(f"[{idx}] {ep.method} {ep.path} -> {ep.service}{(' - ' + ep.description) if ep.description else ''}")

    choice = input_func("Выберите действие (номер, путь или service): ").strip()
    selected: Optional[Tuple[HttpEndpoint, Dict[str, str]]] = None
    if choice.isdigit():
        i = int(choice)
        if 0 <= i < len(endpoints):
            selected = (endpoints[i], {})
    if selected is None:
        match = _match_endpoint(choice, endpoints)
        if match:
            selected = match
    if selected is None:
        for ep in endpoints:
            if ep.service == choice:
                selected = (ep, {})
                break
    if selected is None:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="warning",
                message="Не удалось распознать выбор",
                component="console",
                choice=choice
            )
        except Exception:
            print("Не удалось распознать выбор")
        if shutdown_on_exit:
            await runtime.shutdown()
        return runtime

    endpoint, params = selected
    param_names: List[str] = []
    for part in [p for p in endpoint.path.split("/") if p != ""]:
        if part.startswith("{") and part.endswith("}"):
            param_names.append(part[1:-1])

    for name in param_names:
        if name not in params or not params[name]:
            val = input_func(f"Введите значение для '{name}': ").strip()
            params[name] = val

    confirm = input_func(f"Подтвердить вызов {endpoint.service} (y/N)? ").strip().lower()
    if confirm not in ("y", "yes"):
        # Для CLI выводим сообщение пользователю
        print("Отменено")
        if shutdown_on_exit:
            await runtime.shutdown()
        return runtime

    try:
        result = await _call_service(runtime, endpoint, params)
        # Для CLI выводим результат пользователю
        print("Результат:", result)
    except Exception as exc:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"CLI call error: {exc}",
                component="console",
                endpoint=endpoint.service
            )
        except Exception:
            pass
        # Для CLI выводим ошибку пользователю
        print("Ошибка при вызове сервиса:", exc)

    if shutdown_on_exit:
        await runtime.shutdown()
    return runtime


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]

    asyncio.run(run_cli(argv if len(argv) > 0 else None))
