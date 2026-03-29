"""
Execution policy .

Policy — данные (выбор backend), а не код Core.
Core/Operations/Plugins/Automation не должны знать, как выбирается backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from .backend import BackendId


class ExecutionPolicy(Protocol):
    def select_backend(
        self,
        operation_type: str,
        plugin_name: Optional[str],
        metadata: Dict[str, Any],
    ) -> BackendId: ...


@dataclass
class StateExecutionPolicy:
    """
    Policy, читающий декларативные правила из runtime.state (или из storage через mirror).

    Формат (dict):
      execution:
        default: in_process
        plugins:
          yandex_smart_home: container
        operations:
          automation.run: process
    """

    runtime: Any
    state_key: str = "execution.policy"

    def _get_policy_dict(self) -> Dict[str, Any]:
        try:
            st = getattr(self.runtime, "state_engine", None) or getattr(self.runtime, "state", None)
            if st and hasattr(st, "get"):
                # StateEngine.get is async in this codebase; we avoid awaiting here.
                # Поэтому читаем policy через storage mirror (runtime.storage) синхронно? Нельзя.
                # Решение: policy держим в storage namespace "state" через StorageWithStateMirror и читаем через storage.get.
                pass
        except Exception:
            pass
        return {}

    def select_backend(
        self,
        operation_type: str,
        plugin_name: Optional[str],
        metadata: Dict[str, Any],
    ) -> BackendId:
        # В этой реализации policy читается из runtime.state через storage mirror.
        # Поскольку state_engine.get async, policy берём из runtime.storage ключа "execution_policy".
        policy = {}
        try:
            # runtime.storage is async; но policy.select_backend sync.
            # Поэтому policy прокидывается в metadata заранее (controller делает async fetch).
            policy = metadata.get("_execution_policy") or {}
        except Exception:
            policy = {}

        default_backend: BackendId = (policy.get("default") or "in_process")

        plugins = policy.get("plugins") or {}
        operations = policy.get("operations") or {}

        # 1) operation-specific override
        if operation_type in operations:
            return operations[operation_type]

        # 2) plugin-specific override
        if plugin_name and plugin_name in plugins:
            return plugins[plugin_name]

        return default_backend

