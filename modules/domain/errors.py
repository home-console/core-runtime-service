"""Domain-level errors — не зависят ни от security, ни от credentials."""


class CredentialAccessDenied(Exception):
    """Доступ к учётной записи запрещён политикой."""

    def __init__(self, credential_id: str, reason: str = ""):
        self.credential_id = credential_id
        self.reason = reason
        super().__init__(f"Access denied to credential '{credential_id}': {reason}")


class TrustViolation(Exception):
    """Нарушение уровня доверия."""


class PolicyViolation(Exception):
    """Нарушение политики доступа."""

