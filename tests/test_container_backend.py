import asyncio
import json
from types import SimpleNamespace

import pytest

from execution.backends.container import ContainerBackend, ContainerBackendConfig


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
async def test_container_backend_calls_docker_and_parses_ok(monkeypatch):
    captured = SimpleNamespace(cmd=None, env=None)

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured.cmd = list(cmd)
        captured.env = kwargs.get("env") or {}
        res = {"status": "ok", "result": {"x": 1}}
        return DummyProc(returncode=0, stdout=json.dumps(res).encode("utf-8"), stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    cfg = ContainerBackendConfig(image="img:test", docker_bin="docker", docker_run_args=(), container_cmd=("python", "-m", "homeconsole_runner"))
    backend = ContainerBackend(cfg)

    out = await backend.execute(operation_type="test.echo", params={"a": 1}, context={"k": "v"})

    assert out.ok is True
    assert out.result == {"x": 1}
    assert out.backend == "container"

    # docker run --rm -i ... -e OPERATION_CONTEXT img:test python -m homeconsole_runner
    assert captured.cmd[:4] == ["docker", "run", "--rm", "-i"]
    assert "img:test" in captured.cmd
    assert captured.env.get("OPERATION_CONTEXT") is not None


@pytest.mark.asyncio
async def test_container_backend_returns_error_on_nonzero_exit(monkeypatch):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return DummyProc(returncode=7, stdout=b"{}", stderr=b"boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    backend = ContainerBackend(ContainerBackendConfig(image="img:test"))
    out = await backend.execute(operation_type="x", params={}, context={})

    assert out.ok is False
    assert out.error is not None
    assert out.error["code"] == "container_exit_nonzero"


@pytest.mark.asyncio
async def test_container_backend_returns_error_on_invalid_json(monkeypatch):
    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return DummyProc(returncode=0, stdout=b"not-json", stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    backend = ContainerBackend(ContainerBackendConfig(image="img:test"))
    out = await backend.execute(operation_type="x", params={}, context={})

    assert out.ok is False
    assert out.error is not None
    assert out.error["code"] == "invalid_container_output"

