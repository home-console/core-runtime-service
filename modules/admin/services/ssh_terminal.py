"""
SSH Terminal Service — проксирование SSH терминала через WebSocket для веб-версии.

Использует asyncssh для асинхронного SSH подключения и проксирует ввод/вывод через WebSocket.
"""

import asyncio
import logging
import base64
from typing import Dict, Any, Optional
from uuid import uuid4

try:
    import asyncssh
except ImportError:
    asyncssh = None

logger = logging.getLogger(__name__)

# Активные SSH сессии: session_id -> SSHConnection
_ssh_sessions: Dict[str, Any] = {}

# Активные WebSocket подключения к сессиям: session_id -> list of websockets
_active_websockets: Dict[str, list] = {}


async def start_ssh_session(
    host: str,
    port: int,
    username: str,
    password: Optional[str] = None,
    private_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Создать SSH сессию и вернуть session_id.
    
    Returns:
        {"session_id": str, "error": Optional[str]}
    """
    if asyncssh is None:
        return {"error": "asyncssh not installed. Install with: pip install asyncssh"}
    
    session_id = str(uuid4())
    
    try:
        # Подключаемся по SSH
        conn_kwargs = {
            "host": host,
            "port": port,
            "username": username,
        }
        
        if password:
            conn_kwargs["password"] = password
        elif private_key:
            # TODO: парсинг приватного ключа
            pass
        
        conn = await asyncssh.connect(**conn_kwargs)
        
        # Создаём интерактивную shell сессию с PTY
        # Используем start_shell для создания интерактивного терминала
        stdin, stdout, stderr = await conn.start_shell(
            term_type="xterm-256color",
            term_size=(80, 24)
        )
        
        _ssh_sessions[session_id] = {
            "connection": conn,
            "stdin": stdin,
            "stdout": stdout,
            "stderr": stderr,
            "host": host,
            "port": port,
            "username": username,
            "created_at": asyncio.get_event_loop().time(),
            "read_task": None,  # Задача чтения из stdout (одна на сессию)
        }
        _active_websockets[session_id] = []
        
        logger.info(f"SSH session {session_id} created for {username}@{host}:{port}")
        
        return {"session_id": session_id}
        
    except Exception as e:
        logger.error(f"Failed to create SSH session: {e}", exc_info=True)
        return {"error": str(e)}


async def handle_ssh_websocket(websocket: Any, session_id: str, runtime: Any) -> None:
    """
    Обработчик WebSocket для SSH терминала.
    Проксирует данные между браузером и SSH сессией.
    """
    logger.info(f"WebSocket connection attempt for SSH session {session_id}")
    if session_id not in _ssh_sessions:
        logger.warning(f"SSH session {session_id} not found. Available sessions: {list(_ssh_sessions.keys())}")
        await websocket.send_text('{"type":"error","message":"Session not found"}')
        await websocket.close(code=1008)
        return
    
    logger.info(f"WebSocket connected for SSH session {session_id}")
    
    # Регистрируем WebSocket подключение
    if session_id not in _active_websockets:
        _active_websockets[session_id] = []
    _active_websockets[session_id].append(websocket)
    
    session_data = _ssh_sessions[session_id]
    conn = session_data["connection"]
    stdin = session_data["stdin"]
    stdout = session_data["stdout"]
    
    # Запускаем задачу чтения из SSH только если её еще нет
    if session_data["read_task"] is None or session_data["read_task"].done():
        async def read_from_ssh_broadcast():
            """Читаем вывод из SSH и отправляем во все подключенные WebSocket."""
            try:
                while True:
                    data = await stdout.read(1024)
                    if not data:
                        break
                    
                    # Отправляем данные во все активные WebSocket подключения этой сессии
                    message = None
                    if isinstance(data, bytes):
                        # Отправляем как base64
                        b64_data = base64.b64encode(data).decode('ascii')
                        message = f'{{"type":"output","data":"{b64_data}"}}'
                    else:
                        # Текст
                        message = f'{{"type":"output","text":"{data}"}}'
                    
                    # Отправляем во все активные WebSocket
                    active_ws = _active_websockets.get(session_id, [])
                    for ws in active_ws[:]:  # Копируем список для безопасной итерации
                        try:
                            await ws.send_text(message)
                        except Exception:
                            # Удаляем неактивные WebSocket из списка
                            if ws in active_ws:
                                active_ws.remove(ws)
            except Exception as e:
                logger.error(f"Error reading from SSH: {e}", exc_info=True)
                # Отправляем ошибку во все активные WebSocket
                error_msg = f'{{"type":"error","message":"SSH read error: {e}"}}'
                active_ws = _active_websockets.get(session_id, [])
                for ws in active_ws[:]:
                    try:
                        await ws.send_text(error_msg)
                    except Exception:
                        if ws in active_ws:
                            active_ws.remove(ws)
        
        session_data["read_task"] = asyncio.create_task(read_from_ssh_broadcast())
    
    async def read_from_websocket():
        """Читаем из WebSocket и отправляем в SSH."""
        try:
            async for message in websocket:
                if isinstance(message, str):
                    # JSON control сообщения
                    import json
                    try:
                        msg = json.loads(message)
                        if msg.get("type") == "resize":
                            cols = msg.get("cols", 80)
                            rows = msg.get("rows", 24)
                            # Изменяем размер терминала через stdin (asyncssh поддерживает это через conn)
                            try:
                                # В asyncssh изменение размера терминала делается через изменение размера канала
                                # Но для start_shell это может не поддерживаться напрямую
                                # Пока пропускаем resize, можно добавить позже если нужно
                                pass
                            except Exception:
                                pass
                        elif msg.get("type") == "input":
                            # Ввод данных (base64)
                            data = base64.b64decode(msg.get("data", ""))
                            stdin.write(data)
                            await stdin.drain()
                        elif msg.get("type") == "text":
                            # Прямой текст
                            stdin.write(msg.get("text", "").encode())
                            await stdin.drain()
                    except Exception as e:
                        logger.error(f"Error processing WebSocket message: {e}", exc_info=True)
                elif isinstance(message, bytes):
                    # Прямые байты
                    stdin.write(message)
                    await stdin.drain()
        except Exception as e:
            logger.error(f"Error reading from WebSocket: {e}", exc_info=True)
    
    # Запускаем задачу чтения из WebSocket (чтение из SSH уже запущено выше)
    try:
        await read_from_websocket()
    except Exception as e:
        logger.error(f"SSH WebSocket handler error: {e}", exc_info=True)
    finally:
        # Удаляем WebSocket из списка активных подключений
        if session_id in _active_websockets:
            if websocket in _active_websockets[session_id]:
                _active_websockets[session_id].remove(websocket)
            # Если больше нет активных подключений, можно закрыть SSH сессию через таймаут
            # Но пока оставляем сессию активной для возможности переподключения
            logger.info(f"WebSocket disconnected for SSH session {session_id}, active connections: {len(_active_websockets.get(session_id, []))}")


async def close_ssh_session(session_id: str) -> None:
    """Закрыть SSH сессию."""
    if session_id in _ssh_sessions:
        session_data = _ssh_sessions[session_id]
        try:
            # Останавливаем задачу чтения из stdout
            if "read_task" in session_data and session_data["read_task"] and not session_data["read_task"].done():
                session_data["read_task"].cancel()
                try:
                    await session_data["read_task"]
                except asyncio.CancelledError:
                    pass
            
            # Закрываем все активные WebSocket подключения
            if session_id in _active_websockets:
                for ws in _active_websockets[session_id][:]:
                    try:
                        await ws.close(code=1000, reason="SSH session closed")
                    except Exception:
                        pass
                del _active_websockets[session_id]
            
            # Закрываем SSH соединение
            if "stdin" in session_data and session_data["stdin"]:
                session_data["stdin"].close()
                await session_data["stdin"].wait_closed()
            if "stdout" in session_data and session_data["stdout"]:
                session_data["stdout"].close()
                await session_data["stdout"].wait_closed()
            if "connection" in session_data:
                session_data["connection"].close()
        except Exception as e:
            logger.debug(f"Error closing SSH session: {e}")
        del _ssh_sessions[session_id]


async def ssh_terminal_start_handler(runtime: Any, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    HTTP handler для создания SSH сессии.
    POST /admin/v1/ssh/start
    Body: {"host": str, "port": int, "username": str, "password": Optional[str]}
    """
    try:
        # body уже является словарем, переданным из route_binding
        if body is None:
            return {"error": "request body required"}
        
        host = body.get("host")
        port = body.get("port", 22)
        username = body.get("username")
        password = body.get("password")
        
        if not host or not username:
            return {"error": "host and username required"}
        
        result = await start_ssh_session(host, port, username, password)
        if "error" in result:
            logger.error(f"Failed to start SSH session: {result.get('error')}")
        else:
            logger.info(f"SSH session started successfully: {result.get('session_id')}")
        return result
        
    except Exception as e:
        logger.error(f"Error in ssh_terminal_start_handler: {e}", exc_info=True)
        return {"error": str(e)}
