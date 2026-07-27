"""Domain-level exception hierarchy."""
from __future__ import annotations


class NationCraftError(Exception):
    """Base exception for all application errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str = "", *, code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message or self.code)
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.message = message or self.code


class ValidationError(NationCraftError):
    status_code = 422
    code = "validation_error"


class NotFoundError(NationCraftError):
    status_code = 404
    code = "not_found"


class ConflictError(NationCraftError):
    status_code = 409
    code = "conflict"


class AuthenticationError(NationCraftError):
    status_code = 401
    code = "authentication_failed"


class AuthorizationError(NationCraftError):
    status_code = 403
    code = "forbidden"


class RateLimitError(NationCraftError):
    status_code = 429
    code = "rate_limited"


class PluginError(NationCraftError):
    status_code = 500
    code = "plugin_error"


class GameRuleError(NationCraftError):
    """Player attempted an action that violates game rules."""
    status_code = 400
    code = "game_rule_violation"


class InsufficientResourcesError(GameRuleError):
    code = "insufficient_resources"


class EconomyError(NationCraftError):
    code = "economy_error"
