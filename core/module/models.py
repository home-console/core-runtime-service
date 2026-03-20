"""
Module Manager Models — specification and configuration types (D2).

Data structures for module specification and bootstrapping.
"""

from dataclasses import dataclass


@dataclass
class ModuleSpec:
    """Спецификация модуля с флагом обязательности. Используется на уровне приложения (bootstrap)."""
    name: str
    required: bool = True
