"""
SSH Terminal Session Manager.

Архитектура:
  - Сессия создаётся через POST /admin/v1/ssh/start (возвращает session_id)
  - Сессия живёт независимо от WebSocket — PTY не закрывается при дисконнекте браузера
  - Несколько WebSocket могут attach/detach к одной сессии одновременно (broadcast)
  - DELETE /admin/v1/ssh/sessions/{session_id} явно убивает сессию

Broadcast:
  - Один поток читает из SSH PTY и кладёт в asyncio.Event (shared bytes buffer)
  - Каждый WS-subscriber имеет свой asyncio.Queue, в который пишет read-loop

Transport: paramiko (уже в requirements.txt).
"""

import asyncio
import io
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Session store
# ──────────────────────────────────────────────────────────────────────────────

class _SshSession:
    """Один PTY-сеанс SSH, к которому могут attach-иться несколько WebSocket."""

    def __init__(self, session_id: str, credential_id: Optional[str], host: str, username: str):
        self.session_id = session_id
        self.credential_id = credential_id
        self.host = host
        self.username = username
        self.created_at = time.time()

        # paramiko objects (set after _open_shell)
        self.client: Any = None
        self.channel: Any = None

        # asyncio event loop (set when first WS attaches)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Subscribers: set of asyncio.Queue[bytes | None]
        self._subscribers: List[asyncio.Queue] = []
        self._lock = threading.Lock()

        # Background read thread
        self._reader_thread: Optional[threading.Thread] = None
        self._closed = False

    # ── subscriber management ──────────────────────────────────────────────

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        """Зарегистрировать нового subscriber; возвращает его очередь."""
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            if self._loop is None:
                self._loop = loop
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def _broadcast(self, data: Optional[bytes]) -> None:
        """Положить данные во все очереди subscribers (вызывается из read-thread)."""
        with self._lock:
            loop = self._loop
            subs = list(self._subscribers)
        if loop is None:
            return
        for q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, data)
            except Exception:
                pass

    # ── PTY read loop (background thread) ─────────────────────────────────

    def _start_reader(self) -> None:
        if self._reader_thread and self._reader_thread.is_alive():
            return
        t = threading.Thread(target=self._read_loop, daemon=True, name=f"ssh-reader-{self.session_id[:8]}")
        self._reader_thread = t
        t.start()

    def _read_loop(self) -> None:
        try:
            while not self._closed:
                try:
                    data = self.channel.recv(4096)
                except Exception:
                    break
                if not data:
                    break
                self._broadcast(data)
        finally:
            self._broadcast(None)  # EOF — скажем всем WS что сессия закончилась
            self._closed = True
            logger.info(f"[ssh-session] {self.session_id[:8]} read loop done")

    # ── lifecycle ──────────────────────────────────────────────────────────

    def close(self) -> None:
        self._closed = True
        self._broadcast(None)
        try:
            if self.channel:
                self.channel.close()
        except Exception:
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass

    def is_alive(self) -> bool:
        return not self._closed and (self.channel is not None) and not self.channel.closed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "credential_id": self.credential_id,
            "host": self.host,
            "username": self.username,
            "created_at": self.created_at,
            "age_sec": time.time() - self.created_at,
            "alive": self.is_alive(),
            "subscribers": len(self._subscribers),
        }


# Global registry
_sessions: Dict[str, _SshSession] = {}


# ──────────────────────────────────────────────────────────────────────────────
# SSH helpers (paramiko)
# ──────────────────────────────────────────────────────────────────────────────

def _open_shell_paramiko(host: str, port: int, username: str, password: Optional[str], private_key_pem: Optional[str]):
    """Synchronous — вызывать через run_in_executor."""
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("paramiko не установлен (pip install paramiko)")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: Dict[str, Any] = dict(
        hostname=host,
        port=port,
        username=username,
        timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )
    if password:
        connect_kwargs["password"] = password
    elif private_key_pem:
        pkey = None
        for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = key_cls.from_private_key(io.StringIO(private_key_pem))
                break
            except Exception:
                continue
        if pkey is None:
            raise RuntimeError("Не удалось распарсить приватный ключ (RSA/Ed25519/ECDSA)")
        connect_kwargs["pkey"] = pkey
    else:
        raise RuntimeError("Нужен password или private_key")

    client.connect(**connect_kwargs)
    channel = client.invoke_shell(term="xterm-256color", width=220, height=50)
    return client, channel


# ──────────────────────────────────────────────────────────────────────────────
# Public API — create / list / get / close
# ──────────────────────────────────────────────────────────────────────────────

async def create_session(
    host: str,
    port: int,
    username: str,
    password: Optional[str] = None,
    private_key_pem: Optional[str] = None,
    credential_id: Optional[str] = None,
) -> _SshSession:
    """Создать новую PTY-сессию. Возвращает объект сессии."""
    loop = asyncio.get_event_loop()
    client, channel = await loop.run_in_executor(
        None, lambda: _open_shell_paramiko(host, port, username, password, private_key_pem)
    )
    session = _SshSession(
        session_id=str(uuid4()),
        credential_id=credential_id,
        host=host,
        username=username,
    )
    session.client = client
    session.channel = channel
    session._start_reader()
    _sessions[session.session_id] = session
    logger.info(f"[ssh-session] Created {session.session_id[:8]} for {username}@{host}:{port}")
    return session


def list_sessions() -> List[Dict[str, Any]]:
    """Список всех сессий (живых и мёртвых)."""
    return [s.to_dict() for s in list(_sessions.values())]


def get_session(session_id: str) -> Optional[_SshSession]:
    return _sessions.get(session_id)


def close_session(session_id: str) -> bool:
    """Закрыть сессию по id. Возвращает True если нашли."""
    session = _sessions.pop(session_id, None)
    if session is None:
        return False
    session.close()
    logger.info(f"[ssh-session] Closed {session_id[:8]}")
    return True


def gc_dead_sessions() -> None:
    """Удалить мёртвые сессии из реестра."""
    dead = [sid for sid, s in list(_sessions.items()) if not s.is_alive()]
    for sid in dead:
        _sessions.pop(sid, None)


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket attach handler
# ──────────────────────────────────────────────────────────────────────────────

async def attach_websocket(websocket: Any, session_id: str) -> None:
    """
    Attach WebSocket к существующей PTY-сессии.
    Двунаправленный мост: WS → SSH PTY, SSH PTY → WS.
    При дисконнекте WS сессия остаётся живой (detach).
    """
    session = _sessions.get(session_id)
    if session is None or not session.is_alive():
        await websocket.send_text(json.dumps({"type": "error", "message": "Session not found or closed"}))
        await websocket.close(code=1008)
        return

    loop = asyncio.get_event_loop()
    queue = session.subscribe(loop)
    channel = session.channel
    logger.info(f"[ssh-ws] attach to {session_id[:8]}, subscribers now: {len(session._subscribers)}")

    # SSH → WS
    async def _ssh_to_ws():
        try:
            while True:
                data = await queue.get()
                if data is None:
                    # SSH сессия завершилась
                    try:
                        await websocket.send_text(json.dumps({"type": "closed", "message": "SSH session ended"}))
                        await websocket.close(code=1000)
                    except Exception:
                        pass
                    break
                try:
                    await websocket.send_bytes(data)
                except Exception:
                    break
        except Exception:
            pass

    # WS → SSH
    async def _ws_to_ssh():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                except asyncio.TimeoutError:
                    if not session.is_alive():
                        break
                    continue
                except Exception:
                    break

                if msg.get("type") == "websocket.disconnect":
                    break

                # binary
                raw_bytes = msg.get("bytes")
                if raw_bytes:
                    await loop.run_in_executor(None, lambda d=raw_bytes: channel.send(d))
                    continue

                text = msg.get("text")
                if text:
                    if text.startswith("{"):
                        try:
                            payload = json.loads(text)
                            ptype = payload.get("type")
                            if ptype == "resize":
                                cols = int(payload.get("cols") or 80)
                                rows = int(payload.get("rows") or 24)
                                await loop.run_in_executor(
                                    None, lambda: channel.resize_pty(width=cols, height=rows)
                                )
                                continue
                            elif ptype == "ping":
                                try:
                                    await websocket.send_text(json.dumps({"type": "pong"}))
                                except Exception:
                                    pass
                                continue
                        except Exception:
                            pass
                    data = text.encode("utf-8", errors="replace")
                    await loop.run_in_executor(None, lambda d=data: channel.send(d))
        except Exception:
            pass

    try:
        await asyncio.gather(_ssh_to_ws(), _ws_to_ssh())
    finally:
        session.unsubscribe(queue)
        logger.info(f"[ssh-ws] detach from {session_id[:8]}, subscribers now: {len(session._subscribers)}")


# ──────────────────────────────────────────────────────────────────────────────
# HTTP handlers
# ──────────────────────────────────────────────────────────────────────────────

async def http_create_session(runtime: Any, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    POST /admin/v1/ssh/sessions
    Body:
      { "credential_id": "..." }                     — использовать кред из БД
      { "host": ..., "username": ..., "password": ... }  — прямые параметры
    """
    if not body:
        return {"error": "body required"}

    credential_id = body.get("credential_id")
    host = body.get("host")
    port = int(body.get("port") or 22)
    username = body.get("username")
    password = body.get("password")
    private_key_pem = body.get("private_key")

    # Если передан credential_id — загрузить из БД
    if credential_id:
        sm = getattr(runtime, "storage_manager", None)
        ss = getattr(runtime, "secret_store", None)
        if sm is None or ss is None:
            return {"error": "Storage not available"}
        try:
            from core.credentials.repository import CredentialRepository
            repo = CredentialRepository(storage_manager=sm, secret_store=ss)
            pair = await repo.get_with_secret(credential_id)
        except Exception as e:
            return {"error": f"Cannot load credential: {e}"}
        if pair is None:
            return {"error": f"Credential {credential_id} not found"}
        cred, secret_bytes = pair
        host = cred.host
        port = cred.port or 22
        username = cred.username
        secret_str = secret_bytes.decode("utf-8", errors="replace").strip()
        from core.credentials.domain import CredentialType
        if cred.type == CredentialType.SSH_PASSWORD:
            password = secret_str
        else:
            private_key_pem = secret_str

    if not host or not username:
        return {"error": "host and username required (or credential_id)"}

    try:
        session = await create_session(
            host=host,
            port=port,
            username=username,
            password=password,
            private_key_pem=private_key_pem,
            credential_id=credential_id,
        )
        return session.to_dict()
    except Exception as e:
        logger.error(f"[ssh] create_session failed: {e}", exc_info=True)
        return {"error": str(e)}


async def http_list_sessions(runtime: Any) -> Dict[str, Any]:
    """GET /admin/v1/ssh/sessions"""
    gc_dead_sessions()
    return {"sessions": list_sessions()}


async def http_close_session(runtime: Any, session_id: str) -> Dict[str, Any]:
    """DELETE /admin/v1/ssh/sessions/{session_id}"""
    deleted = close_session(session_id)
    return {"deleted": deleted}
