"""
Чтение master key из внешней среды.

Приоритет: RUNTIME_MASTER_KEY_FILE → RUNTIME_MASTER_KEY.

Использовать в modules/*, core/* и app/* вместо
прямого os.getenv("RUNTIME_MASTER_KEY").
"""
from __future__ import annotations

import os
from pathlib import Path


def resolve_master_key_passphrase() -> str:
    """
    Вернуть мастер-ключ для SecretStore.

    RUNTIME_MASTER_KEY_FILE позволяет передавать ключ через файл
    (docker secret / bind-mount) без появления значения в env.
    """
    file_path = (os.getenv("RUNTIME_MASTER_KEY_FILE") or "").strip()
    if file_path:
        try:
            val = Path(file_path).expanduser().read_text(encoding="utf-8").strip()
            if val:
                return val
        except OSError as e:
            raise RuntimeError(
                f"Failed to read RUNTIME_MASTER_KEY_FILE={file_path!r}: {e}"
            ) from e
    val = (os.getenv("RUNTIME_MASTER_KEY") or "").strip()
    if not val:
        raise RuntimeError(
            "RUNTIME_MASTER_KEY is required (or provide RUNTIME_MASTER_KEY_FILE)"
        )
    return val


def has_master_key() -> bool:
    try:
        resolve_master_key_passphrase()
        return True
    except RuntimeError:
        return False
