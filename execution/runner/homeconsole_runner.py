from __future__ import annotations

"""
Minimal container runner (D3.1 MVP).

Это НЕ Core и НЕ Plugin SDK. Это исполняющая среда для container backend,
которую позже можно заменить (отдельный сервис, другой язык, wasm, и т.д.).

Протокол:
 - stdin: JSON payload (operation_type, params, context)
 - stdout: JSON result (status=ok|error)
"""

import json
import sys
from typing import Any, Dict


def execute_operation(operation_type: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    MVP: локальная таблица операций внутри runner.

    В будущем здесь будет загрузка плагинов/handlers из изолированного окружения.
    """
    if operation_type == "test.echo":
        return {"echo": params, "context_keys": sorted(list((context or {}).keys()))}

    raise ValueError(f"Unknown operation type: {operation_type}")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        operation_type = payload["operation_type"]
        params = payload.get("params") or {}
        context = payload.get("context") or {}

        result = execute_operation(operation_type, params, context)
        print(json.dumps({"status": "ok", "result": result}, ensure_ascii=False))
        return 0
    except Exception as e:
        err = {"code": "runner_error", "message": str(e), "type": type(e).__name__}
        print(json.dumps({"status": "error", "error": err}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

