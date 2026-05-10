import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.marketplace.git_sources import GitInstallRequest, read_manifest_from_github_repo


def _make_github_tarball_bytes(*, topdir: str, plugin_dir: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        # plugin.json
        manifest = (
            '{"name":"x_plugin","version":"1.0.0","description":"d","author":"a","class_path":"plugin.X"}'
        ).encode("utf-8")
        info = tarfile.TarInfo(name=f"{topdir}/{plugin_dir}/plugin.json")
        info.size = len(manifest)
        tf.addfile(info, io.BytesIO(manifest))
        # plugin.py
        py = b"from core.kernel.base_plugin import BasePlugin\nclass X(BasePlugin):\n    pass\n"
        info2 = tarfile.TarInfo(name=f"{topdir}/{plugin_dir}/plugin.py")
        info2.size = len(py)
        tf.addfile(info2, io.BytesIO(py))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_read_manifest_from_github_repo_uses_subdir_and_validates() -> None:
    runtime = SimpleNamespace(config={"marketplace_allowed_git_hosts": ["github.com"]})

    tar_bytes = _make_github_tarball_bytes(topdir="o-r", plugin_dir="plugins/myplugin")

    async def _fetch(url: str, max_bytes: int) -> bytes:  # noqa: ANN001
        assert "codeload.github.com" in url
        assert max_bytes > 0
        return tar_bytes

    req = GitInstallRequest(
        repo_url="https://github.com/owner/repo",
        ref="main",
        subdir="plugins/myplugin",
    )
    manifest = await read_manifest_from_github_repo(runtime=runtime, req=req, fetcher=_fetch)
    assert manifest["name"] == "x_plugin"


@pytest.mark.asyncio
async def test_read_manifest_allows_codeload_when_github_allowed() -> None:
    runtime = SimpleNamespace(config={"marketplace_allowed_git_hosts": ["github.com"]})
    tar_bytes = _make_github_tarball_bytes(topdir="o-r", plugin_dir="plugins/myplugin")

    async def _fetch(url: str, max_bytes: int) -> bytes:  # noqa: ANN001
        # tarball url is hosted on codeload.github.com
        assert "codeload.github.com" in url
        return tar_bytes

    req = GitInstallRequest(
        repo_url="https://github.com/owner/repo",
        ref="main",
        subdir="plugins/myplugin",
    )
    manifest = await read_manifest_from_github_repo(runtime=runtime, req=req, fetcher=_fetch)
    assert manifest["name"] == "x_plugin"

