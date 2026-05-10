"""Поля ответа API для ошибок MarketplaceInstaller (`error_stage`, `user_message`)."""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple

from modules.marketplace.installer import InstallerError

_MARKETPLACE_PREFIX = re.compile(r"^\[marketplace:([\w]+)\]\s*(.*)$", re.DOTALL)

_USER_MESSAGE_RU: dict[str, str] = {
    "archive": (
        "Проверьте путь к файлу и формат архива "
        "(поддерживаются .zip, .tar.gz и .tgz)."
    ),
    "extract": (
        "Не удалось разобрать архив: возможно файл повреждён "
        "или содержит небезопасные пути. Соберите пакет заново."
    ),
    "manifest": (
        "В корне архива нужен корректный plugin.json по схеме ядра "
        "(обязательны name, version, description, author, class_path и др.)."
    ),
    "trust": (
        "Проверка подписи плагина не прошла или не хватает файлов подписи."
    ),
    "policy": (
        "Политика ядра запретила установку (зависимости между плагинами или capabilities)."
    ),
    "conflict": (
        "Плагин с таким логическим именем уже установлен. Удалите старую версию "
        "или используйте сценарий обновления."
    ),
    "entrypoint": (
        "В архиве отсутствует файл модуля, соответствующий полю class_path в манифесте."
    ),
    "load": (
        "Файлы скопированы, но загрузка плагина в runtime не удалась (импорт или PluginManager)."
    ),
    "integrity": "Хеш архива не совпадает с переданным SHA256.",
    "runtime": (
        "Текущая версия ядра не удовлетворяет минимальным требованиям плагина (min_runtime)."
    ),
    "uninstall": (
        "Каталог установленного плагина не найден — возможно, он уже удалён вручную."
    ),
    "download": "Не удалось скачать пакет из registry или ответ некорректен.",
}


def parse_marketplace_error_message(message: str) -> Tuple[str, str]:
    """
    Из строки ошибки вида ``[marketplace:stage] detail`` вернуть (stage, detail).

    Если префикса нет — stage ``unknown``, в detail вся строка.
    """
    raw = message.strip()
    m = _MARKETPLACE_PREFIX.match(raw)
    if m:
        return m.group(1), (m.group(2).strip() or raw)
    return "unknown", raw


def installer_failure_payload(exc: InstallerError) -> Dict[str, str]:
    """
    Поля для тела операции marketplace (install / remove / update / registry после скачивания).

    Сохраняет ``error`` как полное техническое сообщение для логов и обратной совместимости.
    """
    msg = str(exc)
    parsed_stage, detail = parse_marketplace_error_message(msg)
    explicit = getattr(exc, "stage", None)
    stage = explicit if explicit is not None else parsed_stage

    hint = _USER_MESSAGE_RU.get(
        stage, "Установка или удаление плагина через marketplace не выполнены."
    )
    if detail:
        user_message = f"{hint}\nПодробнее: {detail}"
    else:
        user_message = hint

    return {
        "error": msg,
        "error_stage": stage,
        "user_message": user_message,
    }


def generic_marketplace_failure_payload(message: str) -> Dict[str, Any]:
    """Для исключений без типа InstallerError: разбор префикса или полный текст."""
    parsed_stage, _detail = parse_marketplace_error_message(message)
    if parsed_stage != "unknown":
        return installer_failure_payload(InstallerError(message, stage=parsed_stage))
    return {
        "error": message,
        "error_stage": "unknown",
        "user_message": f"Операция marketplace не выполнена.\nПодробнее: {message}",
    }
