import sys
import tempfile
from pathlib import Path

import pytest

from core.module_discovery import ModuleDiscovery
from core.runtime.runtime_module import RuntimeModule


def _write_module(pkg_dir: Path, name: str, source: str) -> None:
    (pkg_dir / f"{name}.py").write_text(source, encoding="utf-8")


@pytest.mark.asyncio
async def test_module_discovery_single_subclass_without_naming_convention():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pkg_name = "tmp_module_discovery_single"
        pkg_dir = tmp_path / pkg_name
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")

        # module_name will be "single"
        _write_module(
            pkg_dir,
            "single",
            """
from core.runtime.runtime_module import RuntimeModule


class MySinglePlugin(RuntimeModule):
    @property
    def name(self) -> str:
        return "single"
    async def register(self) -> None:
        pass
""",
        )

        sys.path.insert(0, str(tmp_path))
        try:
            discovery = ModuleDiscovery(module_path_prefix=pkg_name)
            cls = await discovery.discover_module("single")
            assert cls is not None
            assert cls.__name__ == "MySinglePlugin"
        finally:
            sys.path.remove(str(tmp_path))


@pytest.mark.asyncio
async def test_module_discovery_explicit_runtime_module_class():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pkg_name = "tmp_module_discovery_explicit"
        pkg_dir = tmp_path / pkg_name
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")

        _write_module(
            pkg_dir,
            "explicit",
            """
from core.runtime.runtime_module import RuntimeModule


class SomeClass(RuntimeModule):
    @property
    def name(self) -> str:
        return "explicit"
    async def register(self) -> None:
        pass


__runtime_module_class__ = SomeClass
""",
        )

        sys.path.insert(0, str(tmp_path))
        try:
            discovery = ModuleDiscovery(module_path_prefix=pkg_name)
            cls = await discovery.discover_module("explicit")
            assert cls is not None
            assert cls.__name__ == "SomeClass"
        finally:
            sys.path.remove(str(tmp_path))


@pytest.mark.asyncio
async def test_module_discovery_ambiguous_multiple_subclasses_raises():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pkg_name = "tmp_module_discovery_ambiguous"
        pkg_dir = tmp_path / pkg_name
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")

        _write_module(
            pkg_dir,
            "ambiguous",
            """
from core.runtime.runtime_module import RuntimeModule


class First(RuntimeModule):
    @property
    def name(self) -> str:
        return "amb1"
    async def register(self) -> None:
        pass


class Second(RuntimeModule):
    @property
    def name(self) -> str:
        return "amb2"
    async def register(self) -> None:
        pass
""",
        )

        sys.path.insert(0, str(tmp_path))
        try:
            discovery = ModuleDiscovery(module_path_prefix=pkg_name)
            with pytest.raises(RuntimeError, match="Ambiguous RuntimeModule discovery"):
                await discovery.discover_module("ambiguous")
        finally:
            sys.path.remove(str(tmp_path))

