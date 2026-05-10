"""Тест утилиты безопасного удаления стейджинг-архива."""

import tempfile
from pathlib import Path

from modules.marketplace.upload_util import STAGING_PREFIX, is_safe_staged_archive_path


def test_staged_allowed_in_tmp_with_prefix() -> None:
    tdir = Path(tempfile.gettempdir()).resolve()
    p = tdir / f"{STAGING_PREFIX}x.zip"
    p.write_bytes(b"x")
    try:
        assert is_safe_staged_archive_path(str(p)) is True
    finally:
        p.unlink(missing_ok=True)


def test_reject_wrong_dir() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"{STAGING_PREFIX}y.zip"
        p.write_bytes(b"z")
        assert is_safe_staged_archive_path(str(p)) is False


def test_reject_bad_prefix_in_tmp() -> None:
    tdir = Path(tempfile.gettempdir()).resolve()
    p = tdir / "other_prefix.zip"
    p.write_bytes(b"x")
    try:
        assert is_safe_staged_archive_path(str(p)) is False
    finally:
        p.unlink(missing_ok=True)
