"""
Capability — строковый контракт обещания поведения.

SDK не содержит registry. Core регистрирует/проверяет capabilities.
"""

from typing import Final

# Capability идентифицируется строкой (например "oauth:yandex", "yandex:session_cookies").
CapabilityId: Final = str

"""
Правила:
- capability — это обещание поведения, не реализация.
- capability ≠ plugin (несколько плагинов могут предоставлять один capability).
- плагин зависит от capability по ID, не от имени плагина.
- SDK не содержит CapabilityRegistry; Core владеет реестром.
"""
