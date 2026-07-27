"""Permission matrix.

Permissions are derived from :class:`PlayerRole`. Admins and owners
have all permissions; moderators have an extended subset; players only
have base permissions.
"""
from __future__ import annotations

from enum import StrEnum, auto
from functools import wraps

from nationcraft.core.exceptions import AuthorizationError
from nationcraft.domain.enums import PlayerRole


class Permission(StrEnum):
    PLAY = auto()
    CHAT = auto()
    TRADE = auto()
    DIPLOMACY = auto()
    WAR = auto()
    CREATE_ALLIANCE = auto()
    BROADCAST = auto()
    MANAGE_PLAYERS = auto()
    MANAGE_WORLDS = auto()
    MANAGE_PLUGINS = auto()
    VIEW_ANALYTICS = auto()
    MODERATE_CHAT = auto()


_ROLE_PERMISSIONS: dict[PlayerRole, set[Permission]] = {
    PlayerRole.PLAYER: {
        Permission.PLAY, Permission.CHAT, Permission.TRADE,
        Permission.DIPLOMACY, Permission.WAR, Permission.CREATE_ALLIANCE,
    },
    PlayerRole.MODERATOR: {
        Permission.PLAY, Permission.CHAT, Permission.TRADE,
        Permission.DIPLOMACY, Permission.WAR, Permission.CREATE_ALLIANCE,
        Permission.MODERATE_CHAT, Permission.VIEW_ANALYTICS,
    },
    PlayerRole.ADMIN: set(Permission),
    PlayerRole.OWNER: set(Permission),
}


def has_permission(role: PlayerRole, permission: Permission) -> bool:
    return permission in _ROLE_PERMISSIONS.get(role, set())


def require_permission(permission: Permission):
    """Decorator for service methods requiring a specific permission."""

    def _wrap(fn):
        @wraps(fn)
        async def _inner(*args, **kwargs):
            role_arg = kwargs.get("actor_role")
            if role_arg is None:
                for a in args:
                    if isinstance(a, PlayerRole):
                        role_arg = a
                        break
            if role_arg is None or not has_permission(role_arg, permission):
                raise AuthorizationError(
                    f"missing permission: {permission}", code="forbidden"
                )
            return await fn(*args, **kwargs)

        return _inner

    return _wrap
