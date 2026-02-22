"""
Admin HTTP handlers for credentials (SSH hosts and other secrets).

Сначала пробует credential.* через ServiceRegistry.
Если модуль credentials не загружен — использует CredentialRepository напрямую (storage_manager + secret_store).
"""

from typing import Any, Dict, Optional

from core.system_context import create_system_context
from core.auth_contextvars import set_current_auth_context, get_current_auth_context


# SystemContext не имеет user_id; для credential.* передаём явно admin
_ADMIN_USER_ID = "admin"
_ADMIN_ROLES = ["ADMIN"]


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
        from core.credentials.repository import CredentialRepository
        return CredentialRepository(storage_manager=sm, secret_store=ss)
    except Exception:
        return None


async def admin_credentials_list(runtime: Any) -> Dict[str, Any]:
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
            return out or {"credentials": [], "count": 0}
        finally:
            set_current_auth_context(prev)
    except Exception as e:
        if not _service_not_loaded(e):
            raise
        repo = _get_repo(runtime)
        if repo is None:
            return {"credentials": [], "count": 0, "_message": "Credentials module not loaded; storage_manager or secret_store missing."}
        try:
            from modules.credentials.schemas import CredentialMetadata
            creds = await repo.list()
            return {
                "credentials": [CredentialMetadata.from_domain(c).to_dict() for c in creds],
                "count": len(creds),
            }
        except Exception:
            return {"credentials": [], "count": 0}


async def admin_credentials_create(runtime: Any, body: Dict[str, Any] = None) -> Dict[str, Any]:
    """POST /admin/v1/credentials — create credential."""
    if not body:
        raise ValueError("body required")
    credential = dict(body.get("credential", body))
    secret_str = body.get("secret") or credential.get("secret")
    if not secret_str:
        raise ValueError("secret required")
    credential.pop("secret", None)
    secret_bytes = secret_str.encode("utf-8") if isinstance(secret_str, str) else secret_str

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
            raise ValueError("Credentials module not loaded and storage/secret_store unavailable. Enable credentials module or check SecretStore init.") from e
        try:
            from core.credentials.domain import Credential, CredentialType
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
            await repo.create(cred, secret_bytes)
            return CredentialMetadata.from_domain(cred).to_dict()
        except Exception as e2:
            raise ValueError(f"Create failed: {e2}") from e2


async def admin_credentials_get_secret(runtime: Any, credential_id: str = None, **kw: Any) -> Dict[str, Any]:
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
        pair = await repo.get_with_secret(cid)
        if pair is None:
            raise ValueError(f"Credential {cid} not found")
        cred, secret_bytes = pair
        secret_str = secret_bytes.decode("utf-8", errors="replace")
        return {"secret": secret_str}


async def admin_credentials_get(runtime: Any, credential_id: str = None, **kw: Any) -> Dict[str, Any]:
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
        cred = await repo.get(cid)
        if cred is None:
            raise ValueError(f"Credential {cid} not found")
        from modules.credentials.schemas import CredentialMetadata
        return CredentialMetadata.from_domain(cred).to_dict()


async def admin_credentials_delete(runtime: Any, credential_id: str = None, **kw: Any) -> Dict[str, Any]:
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
        await repo.delete(cid)
        return {"deleted": True}


async def admin_credentials_update(runtime: Any, credential_id: str, body: Dict[str, Any] = None, **kw: Any) -> Dict[str, Any]:
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
    secret_bytes = secret_str.encode("utf-8") if isinstance(secret_str, str) and secret_str else (secret_str if isinstance(secret_str, bytes) else None)

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
        current = await repo.get(cid)
        if current is None:
            raise ValueError(f"Credential {cid} not found")
        from core.credentials.domain import CredentialType
        from modules.credentials.schemas import CredentialMetadata
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
        await repo.update(updated, secret_bytes)
        return CredentialMetadata.from_domain(updated).to_dict()
