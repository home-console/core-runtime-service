"""
Remote logger — система логирования как внешний сервис.

Это standalone HTTP сервис, который реализует контракт remote plugin:
- GET  /plugin/metadata — описание плагина
- GET  /plugin/health — проверка живости
- POST /plugin/load — инициализация
- POST /plugin/start — начало работы
- POST /plugin/stop — остановка
- POST /plugin/unload — очистка

Сервис логически является плагином Home Console, но запускается вне процесса.
Core Runtime управляет им через HTTP lifecycle вызовы.

Запуск: python3 remote_logger.py [--port 8001]
"""

import asyncio
import json
import sys
from typing import Any, Dict, Optional
from datetime import datetime

try:
    from fastapi import FastAPI, HTTPException, Request
    import uvicorn
except ImportError:
    print("Требуется: pip install fastapi uvicorn")
    sys.exit(1)


# Глобальное состояние плагина
_state = {
    "loaded": False,
    "started": False,
    "logs": [],  # история логов для debug
}


app = FastAPI(title="Remote Logger Plugin", version="0.1.0")


@app.get("/plugin/metadata")
async def get_metadata():
    """Вернуть метаданные плагина."""
    return {
        "name": "remote_logger",
        "type": "system",
        "mode": "remote",
        "version": "0.1.0",
        "description": "Система логирования как удалённый сервис",
        "author": "Home Console",
    }


@app.get("/plugin/health")
async def get_health():
    """Проверка живости сервиса."""
    return {
        "status": "ok",
        "loaded": _state["loaded"],
        "started": _state["started"],
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/plugin/load")
async def plugin_load():
    """Инициализация плагина (загрузка)."""
    try:
        if _state["loaded"]:
            return {"status": "already loaded"}
        
        # Регистрируем сервис logger.log (виртуально, как контракт)
        _state["loaded"] = True
        _state["logs"].append({"event": "load", "time": datetime.utcnow().isoformat()})
        
        return {"status": "ok", "message": "plugin loaded"}
    except Exception as exc:
        _state["logs"].append({"event": "load_error", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/plugin/start")
async def plugin_start():
    """Запуск плагина."""
    try:
        if not _state["loaded"]:
            raise ValueError("Плагин не был загружен")
        if _state["started"]:
            return {"status": "already started"}
        
        _state["started"] = True
        _state["logs"].append({"event": "start", "time": datetime.utcnow().isoformat()})
        
        return {"status": "ok", "message": "plugin started"}
    except Exception as exc:
        _state["logs"].append({"event": "start_error", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/plugin/stop")
async def plugin_stop():
    """Остановка плагина."""
    try:
        if not _state["started"]:
            return {"status": "already stopped"}
        
        _state["started"] = False
        _state["logs"].append({"event": "stop", "time": datetime.utcnow().isoformat()})
        
        return {"status": "ok", "message": "plugin stopped"}
    except Exception as exc:
        _state["logs"].append({"event": "stop_error", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/plugin/unload")
async def plugin_unload():
    """Выгрузка плагина (очистка)."""
    try:
        _state["loaded"] = False
        _state["started"] = False
        _state["logs"].append({"event": "unload", "time": datetime.utcnow().isoformat()})
        
        return {"status": "ok", "message": "plugin unloaded"}
    except Exception as exc:
        _state["logs"].append({"event": "unload_error", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/logger/log")
async def log_message(request: Request):
    """Обработать log-сообщение.
    
    Body (JSON):
    {
        "level": "info",
        "message": "сообщение",
        "context": {...}
    }
    """
    try:
        if not _state["started"]:
            raise ValueError("Плагин не запущен")
        
        body = await request.json()
        level = body.get("level", "info").upper()
        message = body.get("message", "")
        context = body.get("context", {})
        
        # Формируем вывод логов в формате JSON (как system_logger)
        log_record = {
            "level": level.lower(),
            "message": message,
            "context": context,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Выводим в stdout
        print(json.dumps(log_record, ensure_ascii=False))
        
        # Сохраняем в истории (для debug)
        _state["logs"].append(log_record)
        
        return {"status": "ok"}
    except Exception as exc:
        print(json.dumps({
            "level": "error",
            "message": f"Ошибка в remote_logger: {str(exc)}",
            "timestamp": datetime.utcnow().isoformat(),
        }, ensure_ascii=False))
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/plugin/logs")
async def get_logs():
    """Debug endpoint: вернуть историю логов."""
    return {"logs": _state["logs"]}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001, help="Порт для слушания")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host для слушания")
    args = parser.parse_args()
    
    print(f"Запуск remote_logger на {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
