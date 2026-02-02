"""
Product API (BFF) — пользовательский API поверх Core Runtime.

Отдельный слой для User UI / Mobile / Mini-app.
Не использует Inspector; вызывает доменные сервисы через service_registry.call().
"""

from .module import ProductApiModule

__all__ = ["ProductApiModule"]
