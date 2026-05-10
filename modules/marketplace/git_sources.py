from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import socket
import asyncio
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import urlparse

from modules.marketplace.installer import InstallerError, MarketplaceInstaller
from modules.marketplace.upload_util import STAGING_PREFIX

logger = logging.getLogger(__name__)

MAX_TARBALL_BYTES = 100 * 1024 * 1024


def _merr(stage: str, message: str) -> InstallerError:
    # reuse same error envelope format as installer for consistent payload mapping
    return InstallerError(f"[marketplace:{stage}] {message}", stage=stage)


def _allowed_hosts(runtime: Any) -> set[str]:
    """
    Allowlist hosts for git/tarball downloads.

    Config option:
      - Config.marketplace_allowed_git_hosts (list[str]) or dict key same name
    """
    # NOTE: GitHub tarball downloads use codeload.github.com.
    default = {"github.com", "codeload.github.com", "gitlab.com"}
    cfg = getattr(runtime, "config", None) or getattr(runtime, "_config", None)
    raw = None
    if cfg is not None:
        raw = getattr(cfg, "marketplace_allowed_git_hosts", None)
        if raw is None and isinstance(cfg, dict):
            raw = cfg.get("marketplace_allowed_git_hosts")
    if isinstance(raw, (list, tuple, set)) and all(isinstance(x, str) for x in raw):
        return {x.strip() for x in raw if x and x.strip()}
    return default


def _expand_allowed_hosts(hosts: set[str]) -> set[str]:
    """
    Expand allowlist with known download hosts for supported providers.

    - github.com → codeload.github.com (tarball endpoint)
    """
    expanded = set(hosts)
    if "github.com" in expanded:
        expanded.add("codeload.github.com")
    return expanded


def _reject_obviously_unsafe_host(host: str) -> None:
    h = host.strip().lower()
    if not h:
        raise _merr("download", "empty host")
    if h in {"localhost", "localhost.localdomain"} or h.endswith(".localhost"):
        raise _merr("download", "localhost is not allowed")
    # literal IP checks
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            raise _merr("download", f"ip not allowed: {h}")
    except ValueError:
        pass


async def _dns_must_resolve_to_public_ip(host: str) -> None:
    """
    Best-effort DNS safety: if resolution hits private ranges — reject.

    Runs in a thread to avoid blocking the event loop.
    """

    def _resolve() -> list[tuple]:
        return socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)

    try:
        infos = await asyncio.to_thread(_resolve)
    except OSError:
        return
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            raise _merr("download", f"host resolves to non-public ip: {host!r}")


def github_tarball_url(repo_url: str, ref: str) -> str:
    """
    Convert a github repo URL to tarball URL.
    Supports: https://github.com/owner/repo(.git)
    """
    parsed = urlparse(repo_url)
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        raise _merr("download", f"unsupported github repo URL: {repo_url!r}")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise _merr("download", f"invalid github repo URL: {repo_url!r}")
    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"


async def _fetch_https_bytes(
    url: str,
    *,
    max_bytes: int,
    fetcher: Optional[Callable[[str, int], Awaitable[bytes]]] = None,
) -> bytes:
    if fetcher is not None:
        return await fetcher(url, max_bytes)

    # default implementation: aiohttp if available, else urllib via thread
    try:
        import aiohttp  # type: ignore
    except Exception:
        aiohttp = None  # type: ignore

    if aiohttp is not None:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, ssl=True, allow_redirects=False) as resp:
                if resp.status != 200:
                    raise _merr("download", f"HTTP {resp.status} from {url!r}")
                if resp.content_length and resp.content_length > max_bytes:
                    raise _merr("download", f"tarball too large (Content-Length > {max_bytes})")
                buf = bytearray()
                async for chunk in resp.content.iter_chunked(65536):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise _merr("download", f"tarball exceeds limit ({max_bytes} bytes)")
                return bytes(buf)

    import urllib.request
    import asyncio

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
            raise _merr("download", f"redirect not allowed (HTTP {code})")

    def _read() -> bytes:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(url) as r:  # noqa: S310
            data = r.read(max_bytes + 1)
            return data

    data = await asyncio.to_thread(_read)
    if len(data) > max_bytes:
        raise _merr("download", f"tarball exceeds limit ({max_bytes} bytes)")
    return data


def _safe_extract_tar_gz(archive_path: Path, target_dir: Path) -> Path:
    """
    Extract tar.gz safely.

    Returns the extraction root directory that contains the repo contents.
    GitHub tarballs typically have a single top-level directory.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tf:
        members = tf.getmembers()
        # basic safety: reject symlinks/dev
        for m in members:
            if m.issym() or m.islnk() or m.isdev():
                raise _merr("extract", f"unsafe tar member: {m.name!r}")
        # Python 3.14+ requires explicit extraction policy; keep compatibility with older versions.
        try:
            tf.extractall(target_dir, filter="data")  # noqa: S202 (we validate members above)
        except TypeError:
            tf.extractall(target_dir)  # noqa: S202 (we validate members above)
    # find the single top directory (best effort)
    children = [p for p in target_dir.iterdir() if p.is_dir()]
    if len(children) == 1:
        return children[0]
    return target_dir


def _zip_dir(src_dir: Path, zip_path: Path) -> None:
    import zipfile

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src_dir.rglob("*")):
            if p.is_dir():
                continue
            rel = p.relative_to(src_dir)
            zf.write(p, arcname=str(rel))


def _find_plugin_root(repo_root: Path, subdir: Optional[str]) -> Path:
    root = repo_root
    if subdir:
        # normalize
        candidate = (repo_root / subdir).resolve()
        if repo_root.resolve() not in candidate.parents and candidate != repo_root.resolve():
            raise _merr("manifest", f"subdir escapes repo root: {subdir!r}")
        root = candidate
    if not (root / "plugin.json").is_file():
        raise _merr("manifest", f"plugin.json not found under {str(root)!r}")
    return root


@dataclass(frozen=True, slots=True)
class GitInstallRequest:
    repo_url: str
    ref: str = "main"
    subdir: Optional[str] = None
    tarball_sha256: Optional[str] = None


async def install_from_github_repo(
    *,
    runtime: Any,
    installer: MarketplaceInstaller,
    req: GitInstallRequest,
    require_signature: bool = True,
    fetcher: Optional[Callable[[str, int], Awaitable[bytes]]] = None,
) -> Dict[str, Any]:
    """
    Download repo tarball via HTTPS, package plugin dir as zip, install through MarketplaceInstaller.
    """
    parsed = urlparse(req.repo_url)
    if parsed.scheme != "https":
        raise _merr("download", "repo_url must be https")
    _reject_obviously_unsafe_host(parsed.netloc)
    # When fetcher is injected (tests/custom transport), avoid env-dependent DNS lookups.
    if fetcher is None:
        await _dns_must_resolve_to_public_ip(parsed.netloc)
    allowed = _expand_allowed_hosts(_allowed_hosts(runtime))
    if parsed.netloc not in allowed:
        raise _merr("download", f"host not allowed: {parsed.netloc!r}")

    if parsed.netloc == "github.com":
        tar_url = github_tarball_url(req.repo_url, req.ref)
    else:
        raise _merr("download", f"unsupported git host for tarball flow: {parsed.netloc!r}")

    tar_parsed = urlparse(tar_url)
    if tar_parsed.scheme != "https" or not tar_parsed.netloc:
        raise _merr("download", "invalid tarball URL")
    _reject_obviously_unsafe_host(tar_parsed.netloc)
    if fetcher is None:
        await _dns_must_resolve_to_public_ip(tar_parsed.netloc)
    if tar_parsed.netloc not in allowed:
        raise _merr("download", f"download host not allowed: {tar_parsed.netloc!r}")

    tar_bytes = await _fetch_https_bytes(tar_url, max_bytes=MAX_TARBALL_BYTES, fetcher=fetcher)
    if req.tarball_sha256:
        got = hashlib.sha256(tar_bytes).hexdigest()
        if got != req.tarball_sha256:
            raise _merr("integrity", f"SHA256 mismatch: expected {req.tarball_sha256}, got {got}")

    tmp = Path(tempfile.mkdtemp(prefix="marketplace_git_"))
    tar_path = tmp / "repo.tar.gz"
    tar_path.write_bytes(tar_bytes)
    try:
        extract_root = tmp / "repo"
        repo_root = _safe_extract_tar_gz(tar_path, extract_root)
        plugin_root = _find_plugin_root(repo_root, req.subdir)
        if require_signature:
            manifest_text = (plugin_root / "plugin.json").read_text(encoding="utf-8")
            try:
                manifest_obj = json.loads(manifest_text)
            except Exception:
                raise _merr("manifest", "plugin.json is not valid JSON")
            if not manifest_obj.get("public_key") or not (plugin_root / "plugin.sig").is_file():
                raise _merr("trust", "signature required: expected public_key in plugin.json and plugin.sig file")

        staged_zip = Path(tempfile.gettempdir()) / f"{STAGING_PREFIX}git_{os.getpid()}_{abs(hash(req.repo_url))}.zip"
        _zip_dir(plugin_root, staged_zip)
        # install and cleanup staged zip using existing delete_archive_after flow
        result = await installer.install_from_file(
            staged_zip,
            sha256=None,
            runtime=runtime,
            require_signature=require_signature,
        )
        return result
    finally:
        try:
            import shutil

            shutil.rmtree(tmp)
        except OSError:
            logger.debug("git install: tmp cleanup failed", exc_info=True)


async def read_manifest_from_github_repo(
    *,
    runtime: Any,
    req: GitInstallRequest,
    fetcher: Optional[Callable[[str, int], Awaitable[bytes]]] = None,
) -> Dict[str, Any]:
    """Download tarball and return validated plugin.json dict (no install)."""
    from modules.plugins.schema import validate_plugin_json

    parsed = urlparse(req.repo_url)
    if parsed.scheme != "https":
        raise _merr("download", "repo_url must be https")
    _reject_obviously_unsafe_host(parsed.netloc)
    # When fetcher is injected (tests/custom transport), avoid env-dependent DNS lookups.
    if fetcher is None:
        await _dns_must_resolve_to_public_ip(parsed.netloc)
    allowed = _expand_allowed_hosts(_allowed_hosts(runtime))
    if parsed.netloc not in allowed:
        raise _merr("download", f"host not allowed: {parsed.netloc!r}")
    if parsed.netloc != "github.com":
        raise _merr("download", f"unsupported git host: {parsed.netloc!r}")

    tar_url = github_tarball_url(req.repo_url, req.ref)
    tar_parsed = urlparse(tar_url)
    if tar_parsed.scheme != "https" or not tar_parsed.netloc:
        raise _merr("download", "invalid tarball URL")
    _reject_obviously_unsafe_host(tar_parsed.netloc)
    if fetcher is None:
        await _dns_must_resolve_to_public_ip(tar_parsed.netloc)
    if tar_parsed.netloc not in allowed:
        raise _merr("download", f"download host not allowed: {tar_parsed.netloc!r}")
    tar_bytes = await _fetch_https_bytes(tar_url, max_bytes=MAX_TARBALL_BYTES, fetcher=fetcher)
    tmp = Path(tempfile.mkdtemp(prefix="marketplace_git_manifest_"))
    tar_path = tmp / "repo.tar.gz"
    tar_path.write_bytes(tar_bytes)
    try:
        extract_root = tmp / "repo"
        repo_root = _safe_extract_tar_gz(tar_path, extract_root)
        plugin_root = _find_plugin_root(repo_root, req.subdir)
        data = json.loads((plugin_root / "plugin.json").read_text(encoding="utf-8"))
        return validate_plugin_json(data)
    finally:
        try:
            import shutil

            shutil.rmtree(tmp)
        except OSError:
            logger.debug("git manifest: tmp cleanup failed", exc_info=True)

