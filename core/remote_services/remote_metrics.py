"""
Remote metrics — внешний сборщик метрик как system plugin.

Реализует тот же HTTP контракт, что и remote_logger:
- GET  /plugin/metadata
- GET  /plugin/health
- POST /plugin/load
- POST /plugin/start
- POST /plugin/stop
- POST /plugin/unload

Дополнительно предоставляет сервисный endpoint:
- POST /metrics/report
  Body: {"name": str, "value": number, "tags": dict}

Это демонстрационный remote system plugin для эксперимента с proxy.
"""

import sys
from datetime import datetime

try:
    from fastapi import FastAPI, HTTPException, Request
    import uvicorn
except ImportError:
    print("Требуется: pip install fastapi uvicorn")
    sys.exit(1)

_state = {
    "loaded": False,
    "started": False,
    "metrics": [],
}

app = FastAPI(title="Remote Metrics Plugin", version="0.1.0")


@app.get("/plugin/metadata")
async def get_metadata():
    """Вернуть метаданные плагина и описание сервисов."""
    return {
        "name": "remote_metrics",
        "type": "system",
        "mode": "remote",
        "version": "0.1.0",
        "description": "Удалённый сборщик метрик",
        "author": "Home Console",
        "services": [
            {"name": "metrics.report", "endpoint": "/metrics/report", "method": "POST"}
        ],
    }


@app.get("/plugin/health")
async def get_health():
    return {"status": "ok", "loaded": _state["loaded"], "started": _state["started"], "timestamp": datetime.utcnow().isoformat()}


@app.post("/plugin/load")
async def plugin_load():
    try:
        if _state["loaded"]:
            return {"status": "already loaded"}
        _state["loaded"] = True
        _state["metrics"].append({"event": "load", "time": datetime.utcnow().isoformat()})
        return {"status": "ok", "message": "plugin loaded"}
    except Exception as exc:
        _state["metrics"].append({"event": "load_error", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/plugin/start")
async def plugin_start():
    try:
        if not _state["loaded"]:
            raise ValueError("Плагин не был загружен")
        if _state["started"]:
            return {"status": "already started"}
        _state["started"] = True
        _state["metrics"].append({"event": "start", "time": datetime.utcnow().isoformat()})
        return {"status": "ok", "message": "plugin started"}
    except Exception as exc:
        _state["metrics"].append({"event": "start_error", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/plugin/stop")
async def plugin_stop():
    try:
        if not _state["started"]:
            return {"status": "already stopped"}
        _state["started"] = False
        _state["metrics"].append({"event": "stop", "time": datetime.utcnow().isoformat()})
        return {"status": "ok", "message": "plugin stopped"}
    except Exception as exc:
        _state["metrics"].append({"event": "stop_error", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/plugin/unload")
async def plugin_unload():
    try:
        _state["loaded"] = False
        _state["started"] = False
        _state["metrics"].append({"event": "unload", "time": datetime.utcnow().isoformat()})
        return {"status": "ok", "message": "plugin unloaded"}
    except Exception as exc:
        _state["metrics"].append({"event": "unload_error", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/metrics/report")
async def report_metrics(request: Request):
    try:
        if not _state["started"]:
            raise ValueError("Плагин не запущен")
        body = await request.json()
        name = body.get("name")
        value = body.get("value")
        tags = body.get("tags", {})
        record = {"name": name, "value": value, "tags": tags, "timestamp": datetime.utcnow().isoformat()}
        # Для простоты — выводим и сохраняем
        print(record)
        _state["metrics"].append(record)
        return {"status": "ok"}
    except Exception as exc:
        _state["metrics"].append({"event": "report_error", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/plugin/metrics")
async def get_metrics():
    return {"metrics": _state["metrics"]}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8002, help="Порт для слушания")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host для слушания")
    args = parser.parse_args()
    print(f"Запуск remote_metrics на {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
