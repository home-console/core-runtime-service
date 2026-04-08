"""
ModuleSpec — спецификация модуля для bootstrap.

Вынесен в отдельный модуль чтобы ModuleDependencySorter мог его импортировать
без циклического импорта через core.module.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class ModuleSpec:
    """Спецификация модуля с флагом обязательности. Используется на уровне приложения (bootstrap)."""
    name: str
    required: bool = True
    # Декларативные зависимости: этот модуль должен быть загружен/запущен до текущего.
    # Используется для детерминированного порядка boot-time.
    dependencies: List[str] = field(default_factory=list)
