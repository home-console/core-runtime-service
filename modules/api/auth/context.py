"""
RequestContext — контекст авторизации для HTTP запроса.
"""

from dataclasses import dataclass, field
from typing import Optional, Set


@dataclass
class RequestContext:
    """
    Контекст авторизации для HTTP запроса.
    
    Передаётся через request.state в FastAPI.
    Не проникает в CoreRuntime или доменные модули.
    
    Поддерживает users, sessions и JWT tokens.
    """
    subject: str  # Идентификатор субъекта (например, "api_key:key_id", "user:user_id", "session:session_id")
    scopes: Set[str] = field(default_factory=set)  # Множество разрешений (Set для O(1) проверки и защиты от timing attacks)
    is_admin: bool = False  # Административные права
    source: str = "unknown"  # Источник авторизации ("api_key", "session", "jwt", "oauth")
    user_id: Optional[str] = None  # ID пользователя (для users, sessions и JWT)
    session_id: Optional[str] = None  # ID сессии (для sessions)
    
    def __post_init__(self):
        """Нормализует scopes в Set для эффективной проверки."""
        if isinstance(self.scopes, list):
            self.scopes = set(self.scopes)
        elif not isinstance(self.scopes, set):
            self.scopes = set()
