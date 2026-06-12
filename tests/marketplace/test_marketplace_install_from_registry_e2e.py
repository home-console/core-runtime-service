from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import ssl
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp.web
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import NameOID

from core.kernel.base_plugin import BasePlugin
from core.operations.models import Operation, OperationInitiator, OperationInitiatorKind
from core.runtime.runtime_context import RuntimeContext
from modules.marketplace.services import MarketplaceService
from sdk.testing import Noop


def _make_self_signed_tls_context(tmpdir: Path) -> ssl.SSLContext:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    san = x509.SubjectAlternativeName(
        [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=30))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_path = tmpdir / "test-cert.pem"
    key_path = tmpdir / "test-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx.load_cert_chain(str(cert_path), str(key_path))
    return ssl_ctx


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sign_registry_zip(path: Path) -> tuple[str, str, str]:
    """Подпись как в marketplace-api: Ed25519 over SHA256 digest bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    digest_bytes = digest.digest()
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    sig_b64 = base64.b64encode(priv.sign(digest_bytes)).decode("ascii")
    pub_b64 = base64.b64encode(pub.public_bytes_raw()).decode("ascii")
    return digest.hexdigest(), sig_b64, pub_b64


def _build_plugin_zip(out_zip: Path) -> None:
    plugin_json = {
        "name": "e2e_plugin",
        "version": "1.0.0",
        "description": "e2e",
        "author": "test",
        "class_path": "plugin.E2EPlugin",
    }
    plugin_py = """
from core.kernel.base_plugin import BasePlugin, PluginMetadata

class E2EPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="e2e_plugin",
            version="1.0.0",
            description="e2e",
            author="test",
        )
""".lstrip()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "plugin.json").write_text(json.dumps(plugin_json), encoding="utf-8")
        (root / "plugin.py").write_text(plugin_py, encoding="utf-8")

        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(root / "plugin.json", arcname="plugin.json")
            zf.write(root / "plugin.py", arcname="plugin.py")


class _MemStorage:
    """Storage double: supports namespace API and legacy flat keys used in tests/mocks."""

    def __init__(self) -> None:
        self._by_ns: Dict[tuple[str, str], object] = {}
        self._legacy: Dict[str, object] = {}

    async def get(self, a: str, b: Optional[Any] = None) -> Any:
        if b is None:
            return self._legacy.get(a)

        # Namespace API: ("marketplace", "installed")
        if "." not in a and isinstance(b, str) and "." not in b:
            return self._by_ns.get((a, b))

        # Legacy KV API: ("marketplace.installed", default_dict)
        return self._legacy.get(a, b)

    async def set(self, a: str, b: Any, c: Any = None) -> None:
        # Legacy KV API: key includes a dot
        if c is None or "." in a:
            self._legacy[a] = b
            return

        # Namespace API: (namespace, key, value)
        self._by_ns[(a, b)] = c


class _RecordingPluginManager:
    def __init__(self) -> None:
        self.loaded: list[Any] = []

    async def load_plugin(self, plugin: Any) -> None:
        self.loaded.append(plugin)


class _MinimalRuntime:
    def __init__(self, *, storage: _MemStorage, plugin_manager: _RecordingPluginManager, plugins_dir: Path):
        self.storage = storage
        self.plugin_manager = plugin_manager
        self.config = type("Cfg", (), {"plugins_dir": str(plugins_dir)})()

    def create_context(self) -> RuntimeContext:
        # BasePlugin prefers create_context() over guessing attribute names on a fake runtime.
        return RuntimeContext(
            storage=self.storage,
            services=Noop(),
            http=Noop(),
            capabilities=Noop(),
            operations=Noop(),
            state=Noop(),
            event_bus=Noop(),
        )


@pytest.mark.asyncio
async def test_install_from_registry_end_to_end_https_localhost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MARKETPLACE_ALLOW_LOCALHOST", "true")

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    zip_path = tmp_path / "e2e_plugin.zip"
    _build_plugin_zip(zip_path)
    sha, sig_b64, pub_b64 = _sign_registry_zip(zip_path)

    ssl_ctx = _make_self_signed_tls_context(tmp_path)

    app = aiohttp.web.Application()
    ZIP_PATH_KEY = aiohttp.web.AppKey("zip_path", Path)
    app[ZIP_PATH_KEY] = zip_path

    # Mutable release state referenced by closure so handlers see updates
    # without mutating the started app (avoids DeprecationWarning).
    release_state: Dict[str, Any] = {"sha256": sha, "sig_b64": sig_b64, "pub_b64": pub_b64}

    async def registry_index(request: aiohttp.web.Request) -> aiohttp.web.Response:
        base = f"{request.url.scheme}://{request.host}"
        payload = {
            "registry_version": 1,
            "updated_at": "2026-01-01T00:00:00Z",
            "plugins": {
                "e2e_plugin": {
                    "channels": {
                        "stable": {
                            "version": "1.0.0",
                            "url": f"{base}/e2e_plugin.zip",
                            "sha256": release_state["sha256"],
                            "signature": release_state["sig_b64"],
                            "public_key": release_state["pub_b64"],
                        }
                    },
                    "versions": {},
                }
            },
        }
        return aiohttp.web.json_response(payload)

    async def plugin_zip(request: aiohttp.web.Request) -> aiohttp.web.FileResponse:
        return aiohttp.web.FileResponse(path=request.app[ZIP_PATH_KEY])

    app.router.add_get("/registry/index.json", registry_index)
    app.router.add_get("/e2e_plugin.zip", plugin_zip)

    # Tests use self-signed localhost certs; disable aiohttp SSL verification for client sessions in marketplace code.
    _orig_client_session = aiohttp.ClientSession

    def _insecure_client_session(*args: Any, **kwargs: Any):
        kwargs.setdefault("connector", aiohttp.TCPConnector(ssl=False))
        return _orig_client_session(*args, **kwargs)

    import modules.marketplace.registry_client as registry_client_mod
    import modules.marketplace.installer as installer_mod

    monkeypatch.setattr(registry_client_mod, "aiohttp", aiohttp, raising=False)
    monkeypatch.setattr(installer_mod, "aiohttp", aiohttp, raising=False)
    monkeypatch.setattr(aiohttp, "ClientSession", _insecure_client_session)

    # Disable registry index caching so second call with updated release_state
    # actually re-fetches the index instead of returning stale cached data.
    monkeypatch.setattr(registry_client_mod.RegistryClient, "_is_cache_fresh", lambda self: False)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host="127.0.0.1", port=0, ssl_context=ssl_ctx)
    await site.start()

    try:
        assert site._server is not None
        sock = site._server.sockets[0]
        port = int(sock.getsockname()[1])

        storage = _MemStorage()
        pm = _RecordingPluginManager()
        runtime = _MinimalRuntime(storage=storage, plugin_manager=pm, plugins_dir=plugins_dir)

        svc = MarketplaceService(runtime)
        op = Operation(
            operation_id="op-test",
            op_type="marketplace.install_from_registry",
            params={
                "plugin_name": "e2e_plugin",
                "registry_url": f"https://127.0.0.1:{port}/registry/index.json",
                "channel": "stable",
            },
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN),
        )

        result = await svc.handle_install_from_registry(op)
        assert result["status"] == "success"

        installed = await storage.get("marketplace", "installed")
        assert isinstance(installed, dict)
        assert "e2e_plugin" in installed
        assert installed["e2e_plugin"]["version"] == "1.0.0"

        assert len(pm.loaded) == 1
        assert isinstance(pm.loaded[0], BasePlugin)
        assert pm.loaded[0].metadata.name == "e2e_plugin"

        # Same version, new archive (dev replace flow)
        zip_path.unlink(missing_ok=True)
        _build_plugin_zip(zip_path)
        sha2, sig2, pub2 = _sign_registry_zip(zip_path)
        release_state["sha256"] = sha2
        release_state["sig_b64"] = sig2
        release_state["pub_b64"] = pub2

        op_up = Operation(
            operation_id="op-update",
            op_type="marketplace.update_from_registry",
            params={
                "plugin_name": "e2e_plugin",
                "version_constraint": "1.0.0",
                "registry_url": f"https://127.0.0.1:{port}/registry/index.json",
                "channel": "stable",
            },
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN),
        )
        up = await svc.handle_update_from_registry(op_up)
        assert up["status"] == "success", up
        assert len(pm.loaded) >= 1
    finally:
        await runner.cleanup()
