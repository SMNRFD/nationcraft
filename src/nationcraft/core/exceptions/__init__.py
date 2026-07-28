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


# Error codes that indicate a transient/network failure (the user can
# retry). Used by bot handlers to decide whether to clear the FSM state
# or keep it so the user can retry without re-entering the flow.
_TRANSIENT_CODES = frozenset({
    "api_timeout",
    "api_unreachable",
    "api_error",  # non-JSON response (e.g. 502 Bad Gateway from uvicorn)
})


def is_transient_error(exc: NationCraftError) -> bool:
    """Return True if *exc* represents a transient/network error.

    Bot handlers use this to decide whether to clear the FSM state:
    - Transient errors (502, 503, timeout, DNS failure) → keep state,
      let the user retry by re-sending their input.
    - Definitive errors (wrong password, banned, player_exists) →
      clear state, force the user to restart the flow.
    """
    if not isinstance(exc, NationCraftError):
        return False
    # 502/503/504 status codes are transient.
    if exc.status_code in (502, 503, 504):
        return True
    return exc.code in _TRANSIENT_CODES
