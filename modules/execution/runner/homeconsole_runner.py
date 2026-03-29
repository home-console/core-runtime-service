from __future__ import annotations

"""
Execution runner .

Runner — это execution boundary: минимальная среда, которая принимает JSON envelope
и возвращает JSON result, не зная про Core/automation/plugins/admin/ui.

Протокол:
 - stdin: JSON payload по docs/EXECUTION-PROTOCOL.md
 - stdout: JSON result (status=ok|error), всегда валидный JSON
"""

import json
import sys
from typing import Any, Dict

from .adapter import ExecutionAdapter, ExecutionEnvelope, default_handlers


def _read_stdin_json() -> Dict[str, Any]:
    return json.load(sys.stdin)


def _write_stdout_json(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")


def main() -> int:
    adapter = ExecutionAdapter(default_handlers())

    try:
        payload = _read_stdin_json()

        operation_type = payload["operation_type"]
        params = payload.get("params") or {}
        context = payload.get("context") or {}
        timeout = payload.get("timeout")
        if timeout is not None and not isinstance(timeout, int):
            timeout = None

        env = ExecutionEnvelope(
            operation_type=str(operation_type),
            params=params if isinstance(params, dict) else {"value": params},
            context=context if isinstance(context, dict) else {"value": context},
            timeout=timeout,
        )

        res = adapter.execute(env)
        if res.status == "ok":
            _write_stdout_json({"status": "ok", "result": res.result or {}})
            return 0

        err = res.error
        _write_stdout_json(
            {
                "status": "error",
                "error": {
                    "code": (err.code if err else "execution_error"),
                    "message": (err.message if err else "Unknown error"),
                    "details": (err.details if (err and err.details) else {}),
                },
            }
        )
        return 1
    except Exception as e:
        # stdout должен быть валидным JSON даже при ошибках парсинга/ввода
        _write_stdout_json(
            {
                "status": "error",
                "error": {"code": "runner_error", "message": str(e), "details": {"type": type(e).__name__}},
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

