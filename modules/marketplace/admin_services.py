from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict

from modules.marketplace.git_sources import GitInstallRequest, install_from_github_repo, read_manifest_from_github_repo

MAX_PLUGIN_ARCHIVE_UPLOAD_BYTES = 100 * 1024 * 1024


def _staging_suffix_from_upload_name(name: str | None) -> str:
    n = (name or "").lower()
    if n.endswith(".tar.gz"):
        return ".tar.gz"
    if n.endswith(".tgz"):
        return ".tgz"
    if n.endswith(".zip"):
        return ".zip"
    return ".zip"


async def _execute_marketplace_operation(runtime: Any, op_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    ops_mgr = getattr(runtime, "operations", None)
    if ops_mgr is None:
        raise RuntimeError("Operations manager not available")

    from core.operations import OperationInitiator, OperationInitiatorKind

    initiator = OperationInitiator(
        kind=OperationInitiatorKind.ADMIN,
        user_id=None,
    )

    operation = await ops_mgr.create(
        op_type=op_type,
        params=params,
        initiator=initiator,
    )

    result = await ops_mgr.execute(operation)
    op = result.to_dict()
    # Normalize: if handler returned domain failure inside result, return ok:false + 4xx
    nested = op.get("result")
    if isinstance(nested, dict) and nested.get("status") == "failure":
        payload: Dict[str, Any] = {
            "ok": False,
            "status": 422,
            "error": nested.get("error") or "marketplace operation failed",
        }
        if "error_stage" in nested:
            payload["error_stage"] = nested.get("error_stage")
        if "user_message" in nested:
            payload["user_message"] = nested.get("user_message")
        payload["operation"] = op
        return payload
    if op.get("status") == "failed":
        return {
            "ok": False,
            "status": 500,
            "error": op.get("error") or "operation_failed",
            "operation": op,
        }

    plugin_name = params.get("plugin_name")
    message = None
    op_result = op.get("result")
    if isinstance(op_result, dict):
        data = op_result.get("data")
        if isinstance(data, dict):
            plugin_name = data.get("name") or data.get("plugin_name") or plugin_name
        message = op_result.get("message")

    return {"ok": True, "operation": op, "plugin_name": plugin_name, "message": message}


async def admin_marketplace_install(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    return await _execute_marketplace_operation(runtime, "marketplace.install", dict(body))


async def admin_marketplace_install_upload(runtime: Any, request: Any = None, **kwargs: Any) -> Dict[str, Any]:
    """
    Принять архив multipart (поле ``file``), сохранить во временный файл и выполнить ``marketplace.install``.

    Поля формы: ``file`` (обязательно), ``sha256`` (необязательно).
    """
    if request is None:
        raise ValueError("multipart request required")

    from modules.marketplace.upload_util import STAGING_PREFIX

    ct = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in ct:
        raise ValueError("Content-Type must be multipart/form-data")

    form = await request.form()
    up = form.get("file")
    if up is None:
        raise ValueError("multipart field 'file' is required")

    sha256_raw = form.get("sha256")
    sha256_opt = str(sha256_raw).strip() if sha256_raw else None
    if sha256_opt == "":
        sha256_opt = None
    require_signature_raw = form.get("require_signature")
    require_signature = True
    if require_signature_raw is not None:
        require_signature = str(require_signature_raw).strip().lower() not in ("0", "false", "no", "")

    filename = getattr(up, "filename", None) or "plugin.zip"
    suffix = _staging_suffix_from_upload_name(filename)
    import os

    fd, tmp_path = tempfile.mkstemp(prefix=STAGING_PREFIX, suffix=suffix)
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await up.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PLUGIN_ARCHIVE_UPLOAD_BYTES:
                    raise ValueError(
                        f"archive exceeds max size ({MAX_PLUGIN_ARCHIVE_UPLOAD_BYTES} bytes)"
                    )
                out.write(chunk)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise

    params: Dict[str, Any] = {
        "archive_path": tmp_path,
        "delete_archive_after": True,
        "require_signature": require_signature,
    }
    if sha256_opt is not None:
        params["sha256"] = sha256_opt
    return await _execute_marketplace_operation(runtime, "marketplace.install", params)


def _normalize_registry_body(body: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(body)
    if out.get("version_constraint") is None and out.get("version") is not None:
        out["version_constraint"] = out["version"]
    return out


async def admin_marketplace_install_from_registry(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    return await _execute_marketplace_operation(
        runtime, "marketplace.install_from_registry", _normalize_registry_body(dict(body))
    )


async def admin_marketplace_update_from_registry(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    return await _execute_marketplace_operation(
        runtime, "marketplace.update_from_registry", _normalize_registry_body(dict(body))
    )


async def admin_marketplace_install_from_git(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    """
    Install plugin from git repository (tarball over HTTPS).

    Body:
      - repo_url: str (https)
      - ref: str (branch/tag/sha), default "main"
      - subdir: Optional[str]
      - tarball_sha256: Optional[str]  (sha256 of downloaded tarball)
    """
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")

    repo_url = body.get("repo_url")
    if not isinstance(repo_url, str) or not repo_url.strip():
        raise ValueError("repo_url required")
    ref = body.get("ref") or "main"
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("ref must be non-empty string")
    subdir = body.get("subdir")
    if subdir is not None and not isinstance(subdir, str):
        raise ValueError("subdir must be string")
    tarball_sha256 = body.get("tarball_sha256")
    if tarball_sha256 is not None and not isinstance(tarball_sha256, str):
        raise ValueError("tarball_sha256 must be string")
    require_signature = bool(body.get("require_signature", True))
    require_sha256 = bool(body.get("require_sha256", False))
    if require_sha256 and (tarball_sha256 is None or not str(tarball_sha256).strip()):
        raise ValueError("tarball_sha256 required when require_sha256=true")

    req = GitInstallRequest(
        repo_url=repo_url.strip(),
        ref=ref.strip(),
        subdir=subdir.strip() if isinstance(subdir, str) and subdir.strip() else None,
        tarball_sha256=tarball_sha256.strip() if isinstance(tarball_sha256, str) and tarball_sha256.strip() else None,
    )

    # Reuse the existing installer instance from MarketplaceService wiring (plugins_dir is taken from config there),
    # but admin services run standalone, so instantiate based on runtime config similarly to MarketplaceService.
    plugins_dir_value = None
    cfg = getattr(runtime, "config", None) or getattr(runtime, "_config", None)
    if cfg is not None:
        plugins_dir_value = getattr(cfg, "plugins_dir", None)
        if plugins_dir_value is None and isinstance(cfg, dict):
            plugins_dir_value = cfg.get("plugins_dir")
    from modules.marketplace.installer import MarketplaceInstaller
    installer = MarketplaceInstaller(Path(str(plugins_dir_value or "plugins")))

    result = await install_from_github_repo(
        runtime=runtime, installer=installer, req=req, require_signature=require_signature
    )
    return {"ok": True, "result": result}


async def admin_marketplace_git_catalog(runtime: Any, body: Any = None, **kwargs: Any) -> list[Dict[str, Any]]:
    """
    Minimal catalog from git sources stored in storage namespace marketplace.git_sources.

    Body:
      - sources: optional list of { repo_url, ref?, subdir? } (if provided, does not persist)
    Returns:
      - ok: bool
      - items: list[dict] of validated plugin.json + source metadata
      - errors: list[dict] of {source, error}
    """
    sources = None
    if body is not None:
        if not isinstance(body, dict):
            raise ValueError("Request body must be JSON object")
        sources = body.get("sources")

    storage = getattr(runtime, "storage", None)
    if sources is None:
        # Load persisted sources
        try:
            stored = await storage.get("marketplace", "git_sources")  # type: ignore[func-returns-value]
        except Exception:
            stored = None
        sources = stored or []

    if not isinstance(sources, list):
        raise ValueError("sources must be a list")

    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        repo_url = src.get("repo_url")
        if not isinstance(repo_url, str) or not repo_url.strip():
            continue
        ref = src.get("ref") or "main"
        subdir = src.get("subdir")
        req = GitInstallRequest(
            repo_url=repo_url.strip(),
            ref=str(ref).strip() if ref else "main",
            subdir=str(subdir).strip() if isinstance(subdir, str) and subdir.strip() else None,
        )
        try:
            manifest = await read_manifest_from_github_repo(runtime=runtime, req=req)
            items.append({**manifest, "_source": {"repo_url": req.repo_url, "ref": req.ref, "subdir": req.subdir}})
        except Exception as e:
            errors.append({"source": {"repo_url": req.repo_url, "ref": req.ref, "subdir": req.subdir}, "error": str(e)})

    return items


async def admin_marketplace_git_sources_set(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    """Persist git sources list into storage marketplace.git_sources."""
    if body is None or not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    sources = body.get("sources")
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    storage = getattr(runtime, "storage", None)
    await storage.set("marketplace", "git_sources", sources)  # type: ignore[func-returns-value]
    return {"sources": sources, "count": len(sources)}


async def admin_marketplace_git_sources_get(runtime: Any, **kwargs: Any) -> Dict[str, Any]:
    """Get persisted git sources list from storage marketplace.git_sources."""
    storage = getattr(runtime, "storage", None)
    try:
        stored = await storage.get("marketplace", "git_sources")  # type: ignore[func-returns-value]
    except Exception:
        stored = None
    if not isinstance(stored, list):
        stored = []
    return {"sources": stored, "count": len(stored)}


async def admin_marketplace_remove(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    return await _execute_marketplace_operation(runtime, "marketplace.remove", dict(body))


async def admin_marketplace_update(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Request body must be JSON object")
    return await _execute_marketplace_operation(runtime, "marketplace.update", dict(body))


async def admin_marketplace_enable(runtime: Any, plugin_name: str, **kwargs: Any) -> Dict[str, Any]:
    return await _execute_marketplace_operation(runtime, "marketplace.enable", {"plugin_name": plugin_name})


async def admin_marketplace_disable(runtime: Any, plugin_name: str, **kwargs: Any) -> Dict[str, Any]:
    return await _execute_marketplace_operation(runtime, "marketplace.disable", {"plugin_name": plugin_name})


async def admin_marketplace_installed(runtime: Any, **kwargs: Any) -> Dict[str, Any]:
    op_result = await _execute_marketplace_operation(runtime, "marketplace.list_installed", {})
    if not op_result.get("ok", True):
        return op_result

    op = op_result.get("result") or {}
    data = (op.get("result") or {}).get("data") or {}
    installed = data.get("installed_plugins") or {}

    plugins = []
    for plugin_name, info in installed.items():
        if not isinstance(info, dict):
            continue
        plugins.append({
            "name": info.get("name", plugin_name),
            "version": info.get("version"),
            "enabled": info.get("enabled", True),
            "source": info.get("source"),
            "description": info.get("description"),
            "metadata": info.get("metadata"),
        })
    return {"ok": True, "result": plugins}


async def admin_marketplace_updates(runtime: Any, body: Any = None, **kwargs: Any) -> Dict[str, Any]:
    # Optional body params (e.g. registry_url override) are supported for symmetry.
    params: Dict[str, Any] = {}
    if body is not None:
        if not isinstance(body, dict):
            raise ValueError("Request body must be JSON object")
        params = dict(body)
    return await _execute_marketplace_operation(runtime, "marketplace.check_updates", params)

