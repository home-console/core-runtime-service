from __future__ import annotations

from pathlib import Path

from scripts import validate_plugin_sdk_usage


def test_plugin_sdk_usage_guard_passes_in_repo_root() -> None:
    root = Path(__file__).resolve().parents[1]
    assert validate_plugin_sdk_usage.main(["--root", str(root), "--enforce"]) == 0


def test_plugin_sdk_usage_forbids_runtime_service_registry(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(runtime):\n"
        "    return await runtime.service_registry.call('x')\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_runtime_api_methods(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(runtime):\n"
        "    return await runtime.storage_get('x', 'y')\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_runtime_logger_surface(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "def f(runtime):\n"
        "    return runtime.logger\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_runtime_any_attr(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(runtime):\n"
        "    return runtime.anything\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_getattr_runtime(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(runtime):\n"
        "    return getattr(runtime, 'storage_get')\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_allows_no_runtime_or_context_surfaces(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "ok_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 0


def test_plugin_sdk_usage_forbids_self_context_surfaces(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(self):\n"
        "    self.context.http.register(object())\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_self_context_attr(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(self):\n"
        "    ctx = self.context\n"
        "    return ctx\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_getattr_self_context(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(self):\n"
        "    return getattr(self, 'context')\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_globals_runtime(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f():\n"
        "    r = globals()['runtime']\n"
        "    return r\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_vars_runtime(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f():\n"
        "    r = vars()['runtime']\n"
        "    return r\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_dunder_dict_context(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(self):\n"
        "    return self.__dict__['context']\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_object_getattribute_context(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(self):\n"
        "    return object.__getattribute__(self, 'context')\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_builtins_globals_runtime(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f():\n"
        "    g = getattr(__builtins__, 'globals')()\n"
        "    return g['runtime']\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_inspect_currentframe_locals_context(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "import inspect\n"
        "\n"
        "async def f(self):\n"
        "    frame = inspect.currentframe()\n"
        "    return frame.f_locals['context']\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_import_inspect(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "import inspect\n"
        "async def f():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1


def test_plugin_sdk_usage_forbids_frame_locals_attr(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "bad_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        "async def f(frame):\n"
        "    return frame.f_locals\n",
        encoding="utf-8",
    )
    assert validate_plugin_sdk_usage.main(["--root", str(tmp_path), "--enforce"]) == 1

