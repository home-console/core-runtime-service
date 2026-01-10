"""
Обработчики событий для automation модуля.
"""

from typing import Any, Dict


async def handle_external_state_reported(runtime, data: Dict[str, Any]) -> None:
    """
    Обрабатывает событие external.device_state_reported.

    Поведение:
    - Проверяет наличие external_id в payload
    - Ищет mapping для external_id через storage (devices_mappings namespace)
    - Если mapping найден, логирует сообщение через service_registry

    Args:
        runtime: экземпляр CoreRuntime
        data: payload события с ключом external_id
    """
    # Ожидаем payload с ключом external_id
    external_id = data.get("external_id")
    if not external_id:
        return

    # Получаем mapping из storage (devices_mappings namespace)
    # Используем storage напрямую, как в devices модуле
    try:
        mapping = await runtime.storage.get("devices_mappings", external_id)
    except Exception:
        # Если storage недоступен — ничего не делаем
        return

    # mapping теперь dict с ключом "internal_id"
    if mapping and isinstance(mapping, dict):
        internal_id = mapping.get("internal_id")
    else:
        internal_id = None

    # Если соответствие найдено — логируем факт получения изменения состояния
    if internal_id:
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="info",
                message=f"automation: internal device {internal_id} received state change",
                plugin="automation_module",
                context={"external_event": data},
            )
        except Exception:
            # В логах ошибок нет необходимости ломать поток
            pass
