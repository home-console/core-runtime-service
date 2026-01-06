"""
Интерактивный и неинтерактивный CLI-адаптер для Core Runtime.

Правила:
- Источник действий: `runtime.http.list()`
- Поддерживает интерактивный и неинтерактивный режимы
- Не содержит бизнес-логики, не знает доменов

Запуск:
- Интерактивно: `python3 console.py`
- Неинтерактивно: `python3 console.py presence enter`

Функции доступны для импорта из тестов.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter
from plugins.base_plugin import BasePlugin
from core.http_registry import HttpEndpoint


async def _auto_load_plugins(runtime: CoreRuntime) -> None:
    """Асинхронный автоскан каталога `plugins/` и загрузка всех классов-наследников BasePlugin."""
    plugins_dir = Path(__file__).parent / "plugins"
    if not plugins_dir.exists() or not plugins_dir.is_dir():
        return

    for _finder, mod_name, _ispkg in pkgutil.iter_modules([str(plugins_dir)]):
        module_name = f"plugins.{mod_name}"
        try:
            module = importlib.import_module(module_name)
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                try:
                    if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                        plugin_instance = obj(runtime)
                        await runtime.plugin_manager.load_plugin(plugin_instance)
                except Exception:
                    continue
        except Exception:
            # Игнорируем ошибки при импортировании плагинов
            continue


def _match_endpoint(path: str, endpoints: List[HttpEndpoint]) -> Optional[Tuple[HttpEndpoint, Dict[str, str]]]:
    """Найти endpoint по фактическому path (например, '/devices/lamp/on') или по шаблону.

    Возвращает пару (endpoint, params) или None.
    """
    # Normalize
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
    """Выполнить сервис, сопоставив параметры пути в порядке шаблона.

    Параметры передаются позиционно согласно порядку в шаблоне.
    """
    # Extract ordered params
    parts = [p for p in endpoint.path.split("/") if p != ""]
    ordered_values: List[Any] = []
    for p in parts:
        if p.startswith("{") and p.endswith("}"):
            key = p[1:-1]
            ordered_values.append(path_params.get(key))
    # Parse service string for optional encoded kwargs (format: 'service.name?key=val&...')
    service_raw = endpoint.service
    service_name = service_raw
    extra_kwargs: Dict[str, Any] = {}
    if "?" in service_raw:
        service_name, qs = service_raw.split("?", 1)
        # простая парсинг пары key=val, разделённые &
        for part in qs.split("&"):
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                # Преобразуем 'true'/'false' в булевые значения
                val: Any = v
                if v.lower() == "true":
                    val = True
                elif v.lower() == "false":
                    val = False
                extra_kwargs[k] = val
            else:
                extra_kwargs[part] = ""

    # Call service with positional path params and extra kwargs
    return await runtime.service_registry.call(service_name, *ordered_values, **extra_kwargs)


async def run_cli(argv: Optional[List[str]] = None, input_func: Callable[[str], str] = input, shutdown_on_exit: bool = True) -> CoreRuntime:
    """Главная точка запуска CLI.

    Args:
        argv: если None — интерактивный режим, иначе список аргументов (без имени скрипта)
        input_func: функция для получения пользовательского ввода (можно мокировать в тестах)
        shutdown_on_exit: при True — остановит runtime перед выходом

    Возвращает экземпляр `runtime` (полезно для тестов).
    """
    # Инициализация runtime (как в demo/main)
    config = Config.from_env()
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    adapter = SQLiteAdapter(config.db_path)
    await adapter.initialize_schema()
    runtime = CoreRuntime(adapter)

    # Автозагрузка плагинов
    await _auto_load_plugins(runtime)

    # Запуск runtime
    await runtime.start()

    # Список endpoint'ов
    endpoints = runtime.http.list()

    if argv and len(argv) > 0:
        # Неинтерактивный режим — собрать path из argv и выполнить
        requested = "/" + "/".join(argv)
        match = _match_endpoint(requested, endpoints)
        if match is None:
            print(f"Не найден endpoint для пути: {requested}")
            if shutdown_on_exit:
                await runtime.shutdown()
            return runtime
        endpoint, params = match
        try:
            result = await _call_service(runtime, endpoint, params)
            print("Результат:", result)
        except Exception as exc:
            try:
                await runtime.service_registry.call("logger.log", level="error", message=f"CLI call error: {exc}")
            except Exception:
                pass
        if shutdown_on_exit:
            await runtime.shutdown()
        return runtime

    # Интерактивный режим
    print("Интерактивный режим CLI. Доступные действия:")
    for idx, ep in enumerate(endpoints):
        print(f"[{idx}] {ep.method} {ep.path} -> {ep.service}{(' - ' + ep.description) if ep.description else ''}")

    choice = input_func("Выберите действие (номер, путь или service): ").strip()
    # попытка распознать индекс
    selected: Optional[Tuple[HttpEndpoint, Dict[str, str]]] = None
    if choice.isdigit():
        i = int(choice)
        if 0 <= i < len(endpoints):
            selected = (endpoints[i], {})
    if selected is None:
        # пробуем трактовать как путь
        match = _match_endpoint(choice, endpoints)
        if match:
            selected = match
    if selected is None:
        # пробуем трактовать как service
        for ep in endpoints:
            if ep.service == choice:
                selected = (ep, {})
                break
    if selected is None:
        print("Не удалось распознать выбор")
        if shutdown_on_exit:
            await runtime.shutdown()
        return runtime

    endpoint, params = selected
    # Если есть параметры в пути — запросить у пользователя значения (если ещё не заданы)
    # Соберём имена параметров из шаблона
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
        print("Отменено")
        if shutdown_on_exit:
            await runtime.shutdown()
        return runtime

    try:
        result = await _call_service(runtime, endpoint, params)
        print("Результат:", result)
    except Exception as exc:
        try:
            await runtime.service_registry.call("logger.log", level="error", message=f"CLI call error: {exc}")
        except Exception:
            pass
        print("Ошибка при вызове сервиса:", exc)

    if shutdown_on_exit:
        await runtime.shutdown()
    return runtime


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]

    asyncio.run(run_cli(argv if len(argv) > 0 else None))
