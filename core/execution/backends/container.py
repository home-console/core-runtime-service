from __future__ import annotations

"""
Container execution backend (D3.1+).

Правила:
- Core не знает, что такое Docker.
- Operations/Automation/SDK/Plugins не знают про container mode.
- Вся работа с docker CLI сосредоточена ТОЛЬКО здесь.

Протокол: docs/EXECUTION-PROTOCOL.md
"""

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from ..backend import OperationResult


@dataclass(frozen=True)
class ContainerBackendConfig:
    image: str = "homeconsole/plugin-runner:dev"
    docker_bin: str = "docker"
    # Extra args inserted after `docker run` (before the image name)
    docker_run_args: Sequence[str] = ()
    # Command inside container (defaults to runner shipped in the image)
    container_cmd: Sequence[str] = ("python", "-m", "homeconsole_runner")


class ContainerBackend:
    def __init__(self, config: Optional[ContainerBackendConfig] = None) -> None:
        self._cfg = config or ContainerBackendConfig()
        # execution_id -> (container_id | None пока неизвестен)
        self._containers: Dict[str, Optional[str]] = {}
        self._lock = asyncio.Lock()

    def _get_policy_overrides(self, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return (context or {}).get("_execution_policy") or {}
        except Exception:
            return {}

    def _resolve_image(self, context: Dict[str, Any]) -> str:
        # Allow overriding image via policy without changing Core/Operations.
        # Expected shape:
        #   { "container": { "image": "..." } }
        policy = self._get_policy_overrides(context)
        try:
            img = ((policy.get("container") or {}).get("image"))  # type: ignore[assignment]
            if isinstance(img, str) and img.strip():
                return img.strip()
        except Exception:
            pass
        return self._cfg.image

    async def execute(
        self,
        *,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: int | None = None,
    ) -> OperationResult:
        # Execution protocol envelope (runner side). Context is opaque for the runner,
        # but we keep stable shape: {request_id, caller, metadata}.
        raw_ctx = context or {}
        ctx = {
            "request_id": raw_ctx.get("request_id"),
            "caller": raw_ctx.get("caller"),
            "metadata": raw_ctx.get("metadata") if isinstance(raw_ctx.get("metadata"), dict) else dict(raw_ctx),
        }

        payload = {
            "operation_type": operation_type,
            "params": params or {},
            "context": ctx,
            "timeout": timeout,
        }

        image = self._resolve_image(context)

        # Env is optional for debugging; stdin is the canonical channel.
        env = os.environ.copy()
        try:
            env["OPERATION_CONTEXT"] = json.dumps(ctx, ensure_ascii=False)
        except Exception:
            env["OPERATION_CONTEXT"] = "{}"

        cmd = [
            self._cfg.docker_bin,
            "run",
            "--rm",
            "-i",
            *list(self._cfg.docker_run_args),
            "-e",
            "OPERATION_CONTEXT",
            image,
            *list(self._cfg.container_cmd),
        ]

        stdin_bytes = (json.dumps(payload, ensure_ascii=False)).encode("utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as e:
            return OperationResult(
                ok=False,
                error={"code": "docker_not_found", "message": str(e)},
                backend="container",
            )
        except Exception as e:
            return OperationResult(
                ok=False,
                error={"code": "container_spawn_failed", "message": str(e), "type": type(e).__name__},
                backend="container",
            )

        exec_id = raw_ctx.get("execution_id")
        if isinstance(exec_id, str):
            async with self._lock:
                # Пока мы не знаем container_id, но фиксируем факт запущенного контейнера.
                self._containers[exec_id] = None

        try:
            try:
                communicate_coro = proc.communicate(stdin_bytes)
                if timeout is not None:
                    out, err = await asyncio.wait_for(communicate_coro, timeout=timeout)
                else:
                    out, err = await communicate_coro
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return OperationResult(
                    ok=False,
                    error={"code": "timeout", "message": "Container execution timed out"},
                    backend="container",
                    killed=True,
                    timed_out=True,
                )
            except Exception as e:
                return OperationResult(
                    ok=False,
                    error={"code": "container_io_failed", "message": str(e), "type": type(e).__name__},
                    backend="container",
                )

            stdout_text = (out or b"").decode("utf-8", errors="replace").strip()
            stderr_text = (err or b"").decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                return OperationResult(
                    ok=False,
                    error={
                        "code": "container_exit_nonzero",
                        "message": f"Container exited with code {proc.returncode}",
                        "details": {"stderr": stderr_text, "stdout": stdout_text, "returncode": proc.returncode},
                    },
                    backend="container",
                    stderr=stderr_text or None,
                )

            try:
                res = json.loads(stdout_text) if stdout_text else {}
            except Exception as e:
                return OperationResult(
                    ok=False,
                    error={
                        "code": "invalid_container_output",
                        "message": f"Failed to parse container stdout as JSON: {e}",
                        "details": {"stdout": stdout_text, "stderr": stderr_text},
                    },
                    backend="container",
                    stderr=stderr_text or None,
                )

            # Transport contract: only status/result/error (do not implement fallback execution logic).
            status = res.get("status")
            if status == "ok":
                result = res.get("result")
                if not isinstance(result, dict):
                    result = {"value": result}
                return OperationResult(ok=True, result=result, backend="container")

            if status == "error":
                err_obj = res.get("error") or {}
                if not isinstance(err_obj, dict):
                    err_obj = {"code": "execution_error", "message": str(err_obj)}
                # attach stderr for debugging, но не ломаем контракт
                if stderr_text and "details" not in err_obj:
                    err_obj["details"] = {"stderr": stderr_text}
                return OperationResult(ok=False, error=err_obj, backend="container", stderr=stderr_text or None)

            return OperationResult(
                ok=False,
                error={
                    "code": "unknown_container_response",
                    "message": "Container response must have status=ok|error",
                    "details": {"stdout": res, "stderr": stderr_text},
                },
                backend="container",
            )
        finally:
            if isinstance(exec_id, str):
                async with self._lock:
                    self._containers.pop(exec_id, None)

    async def cancel(self, execution_id: str) -> bool:
        """
        Best-effort завершение container execution по execution_id.

        В минимальной реализации мы не знаем container_id, поэтому просто возвращаем False,
        если нет запущенного процесса под этим execution_id. Расширение до docker kill
        возможно в будущем без изменения контракта.
        """
        async with self._lock:
            exists = execution_id in self._containers
            # При наличии container_id: docker kill по нему; сейчас — best-effort exists
        return exists

