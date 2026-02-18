import asyncio
import json
from types import SimpleNamespace

import pytest

from core.execution.backends.process import ProcessBackend, ProcessBackendConfig


class DummyProc:
    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self, stdin: bytes):
        self.stdin_bytes = stdin
        return self._stdout, self._stderr

    def kill(self):
        return None


@pytest.mark.asyncio
async def test_process_backend_calls_runner_and_parses_ok(monkeypatch):
    captured = SimpleNamespace(cmd=None)

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured.cmd = list(cmd)
        res = {"status": "ok", "result": {"x": 1}}
        return DummyProc(returncode=0, stdout=json.dumps(res).encode("utf-8"), stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    cfg = ProcessBackendConfig(python_executable="python", module_path="core.execution.runner.homeconsole_runner")
    backend = ProcessBackend(cfg)

    out = await backend.execute(operation_type="test.echo", params={"a": 1}, context={"k": "v"})

    assert out.ok is True
    assert out.result == {"x": 1}
    assert out.backend == "process"

    assert captured.cmd[:2] == ["python", "-m"]
    assert captured.cmd[2] == "core.execution.runner.homeconsole_runner"


@pytest.mark.asyncio
async def test_process_backend_timeout_kills_process(monkeypatch):
    class SlowProc(DummyProc):
        async def communicate(self, stdin: bytes):
            await asyncio.sleep(1)
            return self._stdout, self._stderr

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return SlowProc(returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    backend = ProcessBackend(ProcessBackendConfig())
    out = await backend.execute(operation_type="x", params={}, context={}, timeout=0)

    assert out.ok is False
    assert out.error is not None
    assert out.error["code"] == "timeout"


@pytest.mark.asyncio
async def test_process_backend_invalid_json(monkeypatch):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return DummyProc(returncode=0, stdout=b"not-json", stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    backend = ProcessBackend(ProcessBackendConfig())
    out = await backend.execute(operation_type="x", params={}, context={})

    assert out.ok is False
    assert out.error is not None
    assert out.error["code"] == "invalid_runner_output"


@pytest.mark.asyncio
async def test_process_backend_smoke_real_runner():
    """
    Smoke-test реального runner'а с operation_type=test.echo.
    """
    backend = ProcessBackend(ProcessBackendConfig())

    params = {"a": 1}
    res = await backend.execute(operation_type="test.echo", params=params, context={})

    assert res.ok is True
    assert res.result is not None
    assert res.result.get("echo") == params

