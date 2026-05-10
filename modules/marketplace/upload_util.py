"""Безопасное удаление временного архива после marketplace.install (upload endpoint)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

STAGING_PREFIX = "hc_mp_upload_"


def is_safe_staged_archive_path(path_str: str) -> bool:
    """Разрешить удаление только файлов, созданных upload-хендлером во временном каталоге."""
    try:
        path = Path(path_str).resolve()
        tmp = Path(tempfile.gettempdir()).resolve()
    except OSError:
        return False
    try:
        parent_ok = path.parent == tmp
    except OSError:
        return False
    if not parent_ok or not path.name.startswith(STAGING_PREFIX):
        return False
    return path.is_file()
