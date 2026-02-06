from __future__ import annotations

"""
Container execution backend (D3.1 MVP).

Правила:
- Core не знает, что такое Docker.
- Operations/Automation/SDK/Plugins не знают про container mode.
- Вся работа с docker CLI сосредоточена ТОЛЬКО здесь.

Протокол (MVP):
stdin  -> JSON payload:
  {
    "operation_type": "...",
    "params": {...},
    "context": {...}
  }

stdout -> JSON result:
  { "status": "ok", "result": {...} }
  или
  { "status": "error", "error": { "code": "...", "message": "..." } }
"""

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from execution.backend import OperationResult


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
        payload = {
            "operation_type": operation_type,
            "params": params or {},
            "context": context or {},
        }

        image = self._resolve_image(context)

        # Minimal env: duplicate context for convenience (debugging), but основной канал — stdin.
        env = os.environ.copy()
        try:
            env["OPERATION_CONTEXT"] = json.dumps(context or {}, ensure_ascii=False)
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
            )

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
            return OperationResult(ok=False, error=err_obj, backend="container")

        return OperationResult(
            ok=False,
            error={
                "code": "unknown_container_response",
                "message": "Container response must have status=ok|error",
                "details": {"stdout": res, "stderr": stderr_text},
            },
            backend="container",
        )

