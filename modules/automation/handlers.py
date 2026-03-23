"""
Обработчики событий для automation модуля.
"""

from typing import Any, Dict

from .registry import get_event_handlers


async def handle_external_state_reported(runtime, data: Dict[str, Any]) -> None:
    """
    Обрабатывает событие external.device_state_reported.

    Поведение:
    - Проверяет наличие external_id в payload
    - Ищет mapping для external_id через storage (devices_mappings namespace)
    - Если mapping найден, создаёт operation (оркестрация), не вызывая доменные сервисы напрямую

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

    # Если соответствие найдено — создаём operation (D2: automation = orchestration)
    if internal_id:
        try:
            ops_mgr = getattr(runtime, "operations", None)
            if not ops_mgr:
                return

            device = await runtime.storage.get("devices", internal_id)
            current_reported = {}
            if isinstance(device, dict):
                current_reported = device.get("state", {}).get("reported", {})

            # skip duplicate reported_state to prevent automation spam
            if current_reported == data.get("state"):
                return

            bridge_data = dict(data)
            bridge_data["source_event"] = "external.device_state_reported"
            bridge_data["internal_id"] = internal_id
            bridge_data["reported_state"] = data.get("state")
            bridge_data["raw"] = data

            handlers = get_event_handlers("external.device_state_reported")
            if not handlers:
                return

            from core.operations import OperationInitiator, OperationInitiatorKind

            # Automation не исполняет действия сама — только описывает intent через operations.
            for handler in handlers:
                op = handler(bridge_data)
                if op:
                    await ops_mgr.create(
                        **op,
                        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM),
                    )
        except Exception:
            # Automation best-effort: не ломаем event loop из-за ошибок оркестрации
            pass
