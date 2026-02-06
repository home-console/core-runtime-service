from __future__ import annotations

"""
Process execution backend (D3.2).

Использует тот же execution-протокол и runner, что и ContainerBackend, но
запускает runner как локальный subprocess (без Docker / container runtime).

Backend = чистый транспорт:
- формирует JSON envelope по docs/EXECUTION-PROTOCOL.md
- запускает runner (`python -m execution.runner.homeconsole_runner`)
- пишет envelope в stdin, читает stdout
- мапит stdout JSON в OperationResult
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

from execution.backend import OperationResult


@dataclass(frozen=True)
class ProcessBackendConfig:
    python_executable: str = sys.executable
    module_path: str = "execution.runner.homeconsole_runner"


class ProcessBackend:
    def __init__(self, config: Optional[ProcessBackendConfig] = None) -> None:
        self._cfg = config or ProcessBackendConfig()

    async def execute(
        self,
        *,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: int | None = None,
    ) -> OperationResult:
        # Execution protocol envelope (identичен ContainerBackend / runner).
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

        cmd = [
            self._cfg.python_executable,
            "-m",
            self._cfg.module_path,
        ]

        stdin_bytes = (json.dumps(payload, ensure_ascii=False)).encode("utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            return OperationResult(
                ok=False,
                error={"code": "python_not_found", "message": str(e)},
                backend="process",
            )
        except Exception as e:
            return OperationResult(
                ok=False,
                error={"code": "process_spawn_failed", "message": str(e), "type": type(e).__name__},
                backend="process",
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
                error={"code": "timeout", "message": "Process execution timed out"},
                backend="process",
                killed=True,
                timed_out=True,
            )
        except Exception as e:
            return OperationResult(
                ok=False,
                error={"code": "process_io_failed", "message": str(e), "type": type(e).__name__},
                backend="process",
            )

        stdout_text = (out or b"").decode("utf-8", errors="replace").strip()
        stderr_text = (err or b"").decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            # Runner всегда пишет корректный JSON, но transport не делает предположений
            return OperationResult(
                ok=False,
                error={
                    "code": "process_exit_nonzero",
                    "message": f"Runner process exited with code {proc.returncode}",
                    "details": {"stderr": stderr_text, "stdout": stdout_text, "returncode": proc.returncode},
                },
                backend="process",
                stderr=stderr_text or None,
            )

        if not stdout_text:
            return OperationResult(
                ok=False,
                error={
                    "code": "empty_runner_output",
                    "message": "Runner produced empty stdout",
                    "details": {"stderr": stderr_text},
                },
                backend="process",
                stderr=stderr_text or None,
            )

        try:
            res = json.loads(stdout_text)
        except Exception as e:
            return OperationResult(
                ok=False,
                error={
                    "code": "invalid_runner_output",
                    "message": f"Failed to parse runner stdout as JSON: {e}",
                    "details": {"stdout": stdout_text, "stderr": stderr_text},
                },
                backend="process",
                stderr=stderr_text or None,
            )

        status = res.get("status")
        if status == "ok":
            result = res.get("result")
            if not isinstance(result, dict):
                result = {"value": result}
            return OperationResult(ok=True, result=result, backend="process")

        if status == "error":
            err_obj = res.get("error") or {}
            if not isinstance(err_obj, dict):
                err_obj = {"code": "execution_error", "message": str(err_obj)}
            if stderr_text and "details" not in err_obj:
                err_obj["details"] = {"stderr": stderr_text}
            return OperationResult(ok=False, error=err_obj, backend="process", stderr=stderr_text or None)

        return OperationResult(
            ok=False,
            error={
                "code": "unknown_runner_response",
                "message": "Runner response must have status=ok|error",
                "details": {"stdout": res, "stderr": stderr_text},
            },
            backend="process",
        )

