import os
import sys
import asyncio
from types import SimpleNamespace

import pytest

# Ensure core-runtime-service is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.logger.module import LoggerModule


class FakeRegistry:
    def __init__(self):
        self._services = {}

    async def register(self, name, func, version=None):
        self._services[name] = func

    async def unregister(self, name):
        self._services.pop(name, None)

    async def has_service(self, name):
        return name in self._services

    async def call(self, name, *args, **kwargs):
        func = self._services.get(name)
        if func is None:
            raise ValueError("service not found")
        return await func(*args, **kwargs)


@pytest.mark.asyncio
async def test_register_registers_service(monkeypatch):
    reg = FakeRegistry()
    runtime = SimpleNamespace(service_registry=reg)
    mod = LoggerModule(runtime)

    await mod.register()

    assert "logger.log" in reg._services


@pytest.mark.asyncio
async def test_log_service_filters_and_prints(monkeypatch, capsys):
    reg = FakeRegistry()
    runtime = SimpleNamespace(service_registry=reg)
    mod = LoggerModule(runtime)

    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    await mod.register()

    # info level should be filtered out
    await reg._services["logger.log"](level="info", message="should be ignored", module="testmod")
    captured = capsys.readouterr()
    assert captured.out == ""

    # error should be printed
    await reg._services["logger.log"](level="error", message="boom", module="testmod", extra=123)
    captured = capsys.readouterr()
    assert "[ERROR] [testmod] boom" in captured.out
    assert "extra=123" in captured.out


@pytest.mark.asyncio
async def test_start_logs_message(capfd):
    reg = FakeRegistry()
    runtime = SimpleNamespace(service_registry=reg)
    mod = LoggerModule(runtime)

    # default LOG_LEVEL is INFO
    await mod.register()
    await mod.start()

    captured = capfd.readouterr()
    assert "Logger module started" in captured.out
