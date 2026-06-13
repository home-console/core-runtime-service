import logging
"""
Admin HTTP handlers for credentials (SSH hosts and other secrets).

Сначала пробует credential.* через ServiceRegistry.
Если модуль credentials не загружен — использует CredentialRepository напрямую (storage_manager + secret_store).
"""

import asyncio
import io
import json
import threading
import time
from typing import Any, Dict, List

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
from core.runtime.auth_contextvars import get_current_auth_context, set_current_auth_context
from core.runtime.system_context import create_system_context
from modules.credentials import CredentialType
logger = logging.getLogger(__name__)

# SystemContext не имеет user_id; для credential.* передаём явно admin
_ADMIN_USER_ID = "admin"
# RBAC Role values are lowercase (see modules.security.rbac_models.Role)
_ADMIN_ROLES = ["admin"]


def _service_not_loaded(e: Exception) -> bool:
    """Проверка, что ошибка из-за отсутствия сервиса (модуль не загружен)."""
    s = str(e).lower()
    return "credential." in s or "not found" in s or "not loaded" in s


def _get_repo(runtime: Any):
    """Создать CredentialRepository из runtime.storage_manager и secret_store (fallback без модуля credentials)."""
    sm = getattr(runtime, "storage_manager", None)
    ss = getattr(runtime, "secret_store", None)
    if sm is None or ss is None:
        return None
    try:
        from modules.credentials import CredentialRepository

        return CredentialRepository(storage_manager=sm, secret_store=ss)
    except (ImportError, ModuleNotFoundError, TypeError):
        logger.debug("_get_repo: CredentialRepository unavailable", exc_info=True)
        return None


async def admin_credentials_list(runtime: Any) -> list:
    """GET /admin/v1/credentials — list all credentials."""
    try:
        ctx = create_system_context("admin", "credential.list")
        prev = get_current_auth_context()
        try:
            set_current_auth_context(ctx)
            out = await runtime.service_registry.call(
                "credential.list",
                _user_id=_ADMIN_USER_ID,
                _user_roles=_ADMIN_ROLES,
            )
            return (out or {}).get("credentials", [])
        finally:
            set_current_auth_context(prev)
    except Exception as e:
        if not _service_not_loaded(e):
            raise
        repo = _get_repo(runtime)
        if repo is None:
            return []
        try:
            from modules.credentials.schemas import CredentialMetadata

            creds = await repo.list()
            return [CredentialMetadata.from_domain(c).to_dict() for c in creds]
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "admin_credentials_list: fallback list failed (storage boundary)",
                exc_info=True,
            )
            return []
        except Exception:
            logger.warning(
                "admin_credentials_list: fallback list failed", exc_info=True
            )
            return []


async def admin_credentials_create(
    runtime: Any, body: Dict[str, Any] = None
) -> Dict[str, Any]:
    """POST /admin/v1/credentials — create credential."""
    if not body:
        raise ValueError("body required")
    credential = dict(body.get("credential", body))
    secret_str = body.get("secret") or credential.get("secret")
    if not secret_str:
        raise ValueError("secret required")
    credential.pop("secret", None)
    secret_bytes = (
        secret_str.encode("utf-8") if isinstance(secret_str, str) else secret_str
    )

    try:
        ctx = create_system_context("admin", "credential.create")
        prev = get_current_auth_context()
        try:
            set_current_auth_context(ctx)
            return await runtime.service_registry.call(
                "credential.create",
                credential=credential,
                secret=secret_bytes,
                _user_id=_ADMIN_USER_ID,
                _user_roles=_ADMIN_ROLES,
            )
        finally:
            set_current_auth_context(prev)
    except Exception as e:
        if not _service_not_loaded(e):
            raise
        repo = _get_repo(runtime)
        if repo is None:
            raise ValueError(
                "Credentials module not loaded and storage/secret_store unavailable. Enable credentials module or check SecretStore init."
            ) from e
        try:
            from modules.credentials import Credential, CredentialType
            from modules.credentials.schemas import CredentialMetadata

            secret_ref = (credential.get("secret_ref") or "").strip()
            if not secret_ref:
                secret_ref = f"cred:{credential.get('name', '').replace(' ', '_')}"
            cred = Credential.create(
                type=CredentialType(credential["type"]),
                name=credential["name"].strip(),
                secret_ref=secret_ref,
                username=credential.get("username"),
                host=credential.get("host"),
                port=credential.get("port"),
                metadata=credential.get("metadata") or {},
                tags=credential.get("tags") or [],
            )
        except (KeyError, TypeError, ValueError) as e2:
            raise ValueError(f"Create failed: invalid input: {e2}") from e2
        try:
            await repo.create(cred, secret_bytes)
        except STORAGE_BOUNDARY_ERRORS as e2:
            logger.warning(
                "admin_credentials_create: fallback repo.create storage boundary",
                exc_info=True,
            )
            raise ValueError(f"Create failed (storage): {e2}") from e2
        except Exception as e2:
            logger.warning(
                "admin_credentials_create: fallback repo.create failed",
                exc_info=True,
            )
            raise ValueError(f"Create failed: {e2}") from e2
        return CredentialMetadata.from_domain(cred).to_dict()


async def admin_credentials_get_secret(
    runtime: Any, credential_id: str = None, **kw: Any
) -> Dict[str, Any]:
    """GET /admin/v1/credentials/{credential_id}/secret — получить секрет (для экспорта в .ssh/config и т.д.)."""
    cid = credential_id or kw.get("credential_id")
    if not cid:
        raise ValueError("credential_id required")
    try:
        ctx = create_system_context("admin", "credential.get_with_secret")
        prev = get_current_auth_context()
        try:
            set_current_auth_context(ctx)
            out = await runtime.service_registry.call(
                "credential.get_with_secret",
                credential_id=cid,
                _user_id=_ADMIN_USER_ID,
                _user_roles=_ADMIN_ROLES,
            )
            if not out:
                raise ValueError(f"Credential {cid} not found")
            cred, secret_bytes = out
            secret_str = secret_bytes.decode("utf-8", errors="replace")
            return {"secret": secret_str}
        finally:
            set_current_auth_context(prev)
    except Exception as e:
        if not _service_not_loaded(e):
            raise
        repo = _get_repo(runtime)
        if repo is None:
            raise ValueError("Credentials module not loaded") from e
        try:
            pair = await repo.get_with_secret(cid)
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "admin_credentials_get_secret: fallback get_with_secret storage boundary",
                exc_info=True,
            )
            raise
        if pair is None:
            raise ValueError(f"Credential {cid} not found")
        cred, secret_bytes = pair
        secret_str = secret_bytes.decode("utf-8", errors="replace")
        return {"secret": secret_str}


async def admin_credentials_get(
    runtime: Any, credential_id: str = None, **kw: Any
) -> Dict[str, Any]:
    """GET /admin/v1/credentials/{credential_id} — get one credential (metadata)."""
    cid = credential_id or kw.get("credential_id")
    if not cid:
        raise ValueError("credential_id required")
    try:
        ctx = create_system_context("admin", "credential.get")
        prev = get_current_auth_context()
        try:
            set_current_auth_context(ctx)
            return await runtime.service_registry.call(
                "credential.get",
                credential_id=cid,
                _user_id=_ADMIN_USER_ID,
                _user_roles=_ADMIN_ROLES,
            )
        finally:
            set_current_auth_context(prev)
    except Exception as e:
        if not _service_not_loaded(e):
            raise
        repo = _get_repo(runtime)
        if repo is None:
            raise ValueError("Credentials module not loaded") from e
        try:
            cred = await repo.get(cid)
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "admin_credentials_get: fallback repo.get storage boundary",
                exc_info=True,
            )
            raise
        if cred is None:
            raise ValueError(f"Credential {cid} not found")
        from modules.credentials.schemas import CredentialMetadata

        return CredentialMetadata.from_domain(cred).to_dict()


async def admin_credentials_delete(
    runtime: Any, credential_id: str = None, **kw: Any
) -> Dict[str, Any]:
    """DELETE /admin/v1/credentials/{credential_id}."""
    cid = credential_id or kw.get("credential_id")
    if not cid:
        raise ValueError("credential_id required")
    try:
        ctx = create_system_context("admin", "credential.delete")
        prev = get_current_auth_context()
        try:
            set_current_auth_context(ctx)
            await runtime.service_registry.call(
                "credential.delete",
                credential_id=cid,
                _user_id=_ADMIN_USER_ID,
                _user_roles=_ADMIN_ROLES,
            )
            return {"deleted": True}
        finally:
            set_current_auth_context(prev)
    except Exception as e:
        if not _service_not_loaded(e):
            raise
        repo = _get_repo(runtime)
        if repo is None:
            raise ValueError("Credentials module not loaded") from e
        try:
            await repo.delete(cid)
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "admin_credentials_delete: fallback repo.delete storage boundary",
                exc_info=True,
            )
            raise
        return {"deleted": True}


async def admin_credentials_update(
    runtime: Any, credential_id: str, body: Dict[str, Any] = None, **kw: Any
) -> Dict[str, Any]:
    """PUT /admin/v1/credentials/{credential_id} — update credential (metadata и/или секрет)."""
    cid = credential_id or kw.get("credential_id")
    if not cid:
        raise ValueError("credential_id required")
    if not body:
        raise ValueError("body required")
    credential = dict(body.get("credential", body))
    credential["id"] = cid
    secret_str = body.get("secret") or credential.get("secret")
    credential.pop("secret", None)
    secret_bytes = (
        secret_str.encode("utf-8")
        if isinstance(secret_str, str) and secret_str
        else (secret_str if isinstance(secret_str, bytes) else None)
    )

    try:
        ctx = create_system_context("admin", "credential.update")
        prev = get_current_auth_context()
        try:
            set_current_auth_context(ctx)
            return await runtime.service_registry.call(
                "credential.update",
                credential=credential,
                secret=secret_bytes,
                _user_id=_ADMIN_USER_ID,
                _user_roles=_ADMIN_ROLES,
            )
        finally:
            set_current_auth_context(prev)
    except Exception as e:
        if not _service_not_loaded(e):
            raise
        repo = _get_repo(runtime)
        if repo is None:
            raise ValueError("Credentials module not loaded") from e
        try:
            current = await repo.get(cid)
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "admin_credentials_update: fallback repo.get storage boundary",
                exc_info=True,
            )
            raise
        if current is None:
            raise ValueError(f"Credential {cid} not found")
        from modules.credentials import CredentialType
        from modules.credentials.schemas import CredentialMetadata

        try:
            changes = {}
            if credential.get("name") is not None:
                changes["name"] = str(credential["name"]).strip()
            if credential.get("host") is not None:
                changes["host"] = str(credential["host"]).strip() or None
            if credential.get("username") is not None:
                changes["username"] = str(credential["username"]).strip() or None
            if credential.get("port") is not None:
                changes["port"] = int(credential["port"]) if credential["port"] else None
            if credential.get("type") is not None:
                changes["type"] = CredentialType(credential["type"])
            if credential.get("secret_ref") is not None:
                changes["secret_ref"] = str(credential["secret_ref"]).strip()
            if credential.get("metadata") is not None:
                changes["metadata"] = credential["metadata"]
            if credential.get("tags") is not None:
                changes["tags"] = credential["tags"]
            # version не передаём в mutate — репозиторий ожидает version = current.version + 1,
            # mutate() сам инкрементирует, если version не передан
            updated = current.mutate(**changes)
        except (KeyError, TypeError, ValueError) as e2:
            raise ValueError(f"Update failed: invalid input: {e2}") from e2
        try:
            await repo.update(updated, secret_bytes)
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "admin_credentials_update: fallback repo.update storage boundary",
                exc_info=True,
            )
            raise
        except Exception as e2:
            logger.warning(
                "admin_credentials_update: fallback repo.update failed",
                exc_info=True,
            )
            raise ValueError(f"Update failed: {e2}") from e2
        return CredentialMetadata.from_domain(updated).to_dict()


def _ssh_connect_with_credential(cred, secret_bytes: bytes) -> Dict[str, Any]:
    """
    Установить SSH-подключение к хосту по креду из БД.
    Возвращает { "ok": True } или { "ok": False, "error": "..." }.
    """
    try:
        import paramiko
    except ImportError:
        return {"ok": False, "error": "paramiko не установлен (pip install paramiko)"}

    if cred.type not in (CredentialType.SSH_PASSWORD, CredentialType.SSH_KEY):
        return {
            "ok": False,
            "error": f"Тип креда {cred.type} не поддерживает подключение к хосту (нужен ssh_password или ssh_key)",
        }
    if not cred.host or not cred.username:
        return {"ok": False, "error": "У креда должны быть указаны host и username"}

    host = cred.host
    port = cred.port or 22
    username = cred.username
    secret_str = secret_bytes.decode("utf-8", errors="replace").strip()

    client = None
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        _ssh_key_errors = (paramiko.SSHException, ValueError, OSError)
        if cred.type == CredentialType.SSH_PASSWORD:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=secret_str,
                timeout=15,
                allow_agent=False,
                look_for_keys=False,
            )
        else:
            # SSH_KEY
            pkey = None
            for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
                try:
                    pkey = key_cls.from_private_key(io.StringIO(secret_str))
                    break
                except _ssh_key_errors:
                    continue
            if pkey is None:
                return {
                    "ok": False,
                    "error": "Не удалось прочитать приватный ключ (RSA/Ed25519/ECDSA)",
                }
            client.connect(
                hostname=host,
                port=port,
                username=username,
                pkey=pkey,
                timeout=15,
                allow_agent=False,
                look_for_keys=False,
            )
        return {"ok": True, "message": "Подключение установлено"}
    except (paramiko.SSHException, OSError, TimeoutError) as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.warning(
            "_ssh_connect_with_credential: unexpected error: %s", e, exc_info=True
        )
        return {"ok": False, "error": str(e)}
    finally:
        if client:
            try:
                client.close()
            except OSError:
                logger.debug("ssh connect: client.close failed", exc_info=True)


async def admin_credentials_connect(
    runtime: Any, credential_id: str = None, **kw: Any
) -> Dict[str, Any]:
    """
    POST /admin/v1/credentials/{credential_id}/connect — подключиться к хосту по креду из БД.
    Для SSH-кредов (ssh_password, ssh_key) устанавливает соединение и возвращает ok/error.
    """
    cid = credential_id or kw.get("credential_id")
    if not cid:
        raise ValueError("credential_id required")

    repo = _get_repo(runtime)
    if repo is None:
        raise ValueError(
            "Credentials module not loaded (storage_manager or secret_store missing)"
        )

    pair = await repo.get_with_secret(cid)
    if pair is None:
        raise ValueError(f"Credential {cid} not found")

    cred, secret_bytes = pair
    return _ssh_connect_with_credential(cred, secret_bytes)


def _ssh_open_shell(cred, secret_bytes: bytes):
    """
    Открыть SSH-подключение и интерактивный shell (PTY).
    Возвращает (client, channel). Вызывающий должен закрыть client.
    """
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("paramiko не установлен (pip install paramiko)")

    if cred.type not in (CredentialType.SSH_PASSWORD, CredentialType.SSH_KEY):
        raise RuntimeError(
            f"Тип креда {cred.type} не поддерживает терминал (нужен ssh_password или ssh_key)"
        )
    if not cred.host or not cred.username:
        raise RuntimeError("У креда должны быть указаны host и username")

    host = cred.host
    port = cred.port or 22
    username = cred.username
    secret_str = secret_bytes.decode("utf-8", errors="replace").strip()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    _key_load_errors = (paramiko.SSHException, ValueError, OSError)
    if cred.type == CredentialType.SSH_PASSWORD:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=secret_str,
            timeout=15,
            allow_agent=False,
            look_for_keys=False,
        )
    else:
        pkey = None
        for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = key_cls.from_private_key(io.StringIO(secret_str))
                break
            except _key_load_errors:
                continue
        if pkey is None:
            raise RuntimeError(
                "Не удалось прочитать приватный ключ (RSA/Ed25519/ECDSA)"
            )
        client.connect(
            hostname=host,
            port=port,
            username=username,
            pkey=pkey,
            timeout=15,
            allow_agent=False,
            look_for_keys=False,
        )
    channel = client.invoke_shell(term="xterm")
    return client, channel


_ACTIVE_TERMINAL_SESSIONS: Dict[str, Dict[str, Any]] = {}
# Internal map: session_id -> underlying SSH client/channel handles for admin WebSocket terminal
_TERMINAL_HANDLES: Dict[str, Dict[str, Any]] = {}


async def admin_credentials_terminal_sessions(runtime: Any) -> List[Dict[str, Any]]:
    """
    GET /admin/v1/credentials/terminal/sessions — список активных SSH терминальных сессий.
    """
    now = time.time()
    sessions = []
    for sid, info in list(_ACTIVE_TERMINAL_SESSIONS.items()):
        created = info.get("created_at")
        handles = _TERMINAL_HANDLES.get(sid)
        channel = handles.get("channel") if handles else None
        alive = channel is not None and not channel.closed
        # Expose only serializable metadata to API
        item = {
            "session_id": sid,
            "credential_id": info.get("credential_id"),
            "host": info.get("host") or "",
            "username": info.get("username") or "",
            "created_at": created if isinstance(created, (int, float)) else now,
            "age_sec": now - created if isinstance(created, (int, float)) else 0.0,
            "alive": alive,
        }
        sessions.append(item)
    return sessions


async def admin_credentials_terminal_ws(runtime: Any, websocket: Any) -> None:
    """
    WebSocket /admin/v1/credentials/terminal?credential_id=xxx — терминал по креду из БД.
    Мост: браузер ↔ SSH PTY. Закрытие WebSocket закрывает SSH.
    """
    credential_id = (
        websocket.query_params.get("credential_id")
        if hasattr(websocket, "query_params")
        else None
    )
    if not credential_id:
        await websocket.close(code=4000, reason="credential_id required")
        return

    repo = _get_repo(runtime)
    if repo is None:
        await websocket.close(code=4001, reason="Credentials not available")
        return

    try:
        pair = await repo.get_with_secret(credential_id)
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "admin_credentials_terminal_ws: get_with_secret storage boundary: %s",
            e,
            exc_info=True,
        )
        await websocket.close(code=4002, reason=str(e)[:120])
        return
    except Exception as e:
        logger.warning(
            "admin_credentials_terminal_ws: get_with_secret failed: %s",
            e,
            exc_info=True,
        )
        await websocket.close(code=4002, reason=str(e)[:120])
        return

    if pair is None:
        await websocket.close(code=4003, reason="Credential not found")
        return

    cred, secret_bytes = pair
    try:
        client, channel = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _ssh_open_shell(cred, secret_bytes)
        )
    except Exception as e:
        logger.warning(
            "admin_credentials_terminal_ws: ssh open failed: %s", e, exc_info=True
        )
        await websocket.close(code=4004, reason=str(e)[:120])
        return

    session_id = f"{credential_id}:{id(channel)}"
    _ACTIVE_TERMINAL_SESSIONS[session_id] = {
        "credential_id": credential_id,
        "host": getattr(cred, "host", None),
        "username": getattr(cred, "username", None),
        "created_at": time.time(),
    }
    # Keep SSH handles separately so they can be closed from API
    _TERMINAL_HANDLES[session_id] = {"client": client, "channel": channel}

    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def thread_read_ssh():
        try:
            while True:
                data = channel.recv(4096)
                if not data:
                    break
                loop.call_soon_threadsafe(queue.put_nowait, data)
        except OSError:
            logger.debug("ssh terminal: recv ended (OSError)", exc_info=True)
        except Exception:
            logger.debug("ssh terminal: recv error", exc_info=True)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    async def bridge_ssh_to_ws():
        try:
            while True:
                data = await queue.get()
                if data is None:
                    break
                try:
                    await websocket.send_bytes(data)
                except Exception:
                    logger.debug(
                        "ssh terminal: websocket send_bytes failed", exc_info=True
                    )
                    break
        finally:
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def bridge_ws_to_ssh():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(websocket.receive(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if msg.get("type") == "websocket.disconnect":
                    break
                text = msg.get("text")
                if text:
                    # Поддержка JSON‑сообщений от терминала (resize и т.п.)
                    handled = False
                    if text.startswith("{"):
                        try:
                            payload = json.loads(text)
                            if (
                                isinstance(payload, dict)
                                and payload.get("type") == "resize"
                            ):
                                cols = int(payload.get("cols") or 80)
                                rows = int(payload.get("rows") or 24)
                                await loop.run_in_executor(
                                    None,
                                    lambda: channel.resize_pty(width=cols, height=rows),
                                )
                                handled = True
                        except (json.JSONDecodeError, TypeError, ValueError, OSError):
                            handled = False
                    if handled:
                        continue

                    data = text.encode("utf-8", errors="replace")
                    await loop.run_in_executor(None, lambda d=data: channel.send(d))
        except Exception:
            logger.debug("ssh terminal: ws→ssh bridge error", exc_info=True)

    t = threading.Thread(target=thread_read_ssh, daemon=True)
    t.start()
    try:
        await asyncio.gather(bridge_ssh_to_ws(), bridge_ws_to_ssh())
    finally:
        # Очистка SSH и удаление записи о сессии
        _ACTIVE_TERMINAL_SESSIONS.pop(session_id, None)
        handles = _TERMINAL_HANDLES.pop(session_id, None)
        ch = handles.get("channel") if handles else channel
        cl = handles.get("client") if handles else client
        try:
            if ch:
                ch.close()
        except OSError:
            logger.debug("ssh terminal cleanup: channel.close failed", exc_info=True)
        try:
            if cl:
                cl.close()
        except OSError:
            logger.debug("ssh terminal cleanup: client.close failed", exc_info=True)


async def admin_credentials_terminal_session_close(
    runtime: Any, session_id: str
) -> Dict[str, Any]:
    """
    DELETE /admin/v1/credentials/terminal/sessions/{session_id} — принудительно закрыть SSH терминальную сессию.
    """
    info = _ACTIVE_TERMINAL_SESSIONS.pop(session_id, None)
    handles = _TERMINAL_HANDLES.pop(session_id, None)
    closed = False

    if handles:
        ch = handles.get("channel")
        cl = handles.get("client")
        try:
            if ch:
                ch.close()
            closed = True
        except OSError:
            logger.debug("terminal_session_close: channel.close failed", exc_info=True)
        try:
            if cl:
                cl.close()
        except OSError:
            logger.debug("terminal_session_close: client.close failed", exc_info=True)

    return {"deleted": closed or info is not None}
