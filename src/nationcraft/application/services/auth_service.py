"""Authentication service: register, login, refresh, logout, sessions."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.application.dto.auth import (
    LoginRequest,
    PlayerDTO,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from nationcraft.domain.enums import PlayerRole
from nationcraft.infrastructure.db.models import PlayerModel, SessionModel
from nationcraft.infrastructure.security import (
    Argon2PasswordHasher,
    IssueTokens,
    VerifyToken,
)


class AuthService:
    """Handles registration, login, refresh, logout, and session revocation."""

    def __init__(
        self,
        session: AsyncSession,
        hasher: Argon2PasswordHasher | None = None,
        issuer: IssueTokens | None = None,
        verifier: VerifyToken | None = None,
    ) -> None:
        self.session = session
        self.hasher = hasher or Argon2PasswordHasher()
        self.issuer = issuer or IssueTokens()
        self.verifier = verifier or VerifyToken()

    async def register(self, req: RegisterRequest) -> TokenResponse:
        existing = await self.session.scalar(
            select(PlayerModel).where(PlayerModel.telegram_id == req.telegram_id)
        )
        if existing is not None:
            raise ConflictError("player already exists", code="player_exists")

        # Hash password ASYNC to avoid blocking the event loop.
        password_hash = await self.hasher.hash_async(req.password)
        player = PlayerModel(
            telegram_id=req.telegram_id,
            username=req.username,
            locale=req.locale,
            role=PlayerRole.PLAYER.value,
            password_hash=password_hash,
        )
        self.session.add(player)
        await self.session.flush()

        tokens = self.issuer.for_player(player.id, role=player.role)
        await self._save_session(player.id, tokens.refresh_token)
        await event_bus.publish(Event(
            type="player.registered",
            payload={"player_id": player.id, "username": player.username},
            player_id=player.id,
        ))
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=self.issuer.access_ttl,
            player=self._player_dto(player),
        )

    async def login(self, req: LoginRequest) -> TokenResponse:
        player = await self.session.scalar(
            select(PlayerModel).where(PlayerModel.telegram_id == req.telegram_id)
        )
        if player is None or not player.password_hash:
            raise AuthenticationError("invalid credentials")
        if player.is_banned:
            raise AuthenticationError("player is banned", code="player_banned")
        # Verify password ASYNC to avoid blocking the event loop.
        await self.hasher.verify_async(req.password, player.password_hash)

        await self.session.execute(
            update(PlayerModel)
            .where(PlayerModel.id == player.id)
            .values(last_login_at=datetime.now(timezone.utc))
        )
        tokens = self.issuer.for_player(player.id, role=player.role)
        await self._save_session(player.id, tokens.refresh_token)
        await event_bus.publish(Event(
            type="player.logged_in",
            payload={"player_id": player.id},
            player_id=player.id,
        ))
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=self.issuer.access_ttl,
            player=self._player_dto(player),
        )

    async def refresh(self, req: RefreshRequest) -> TokenResponse:
        try:
            payload = self.verifier(req.refresh_token, expected_type="refresh")
        except AuthenticationError:
            raise
        player_id = int(payload["sub"])
        player = await self.session.get(PlayerModel, player_id)
        if player is None or player.is_banned:
            raise AuthenticationError("invalid refresh target")

        # Verify the refresh token matches a stored, non-revoked session.
        token_hash = self._hash_token(req.refresh_token)
        sess = await self.session.scalar(
            select(SessionModel).where(
                SessionModel.refresh_token_hash == token_hash,
                SessionModel.revoked_at.is_(None),
                SessionModel.expires_at > datetime.now(timezone.utc),
            )
        )
        if sess is None:
            raise AuthenticationError("refresh token not recognized")

        # Rotate: revoke old, issue new.
        sess.revoked_at = datetime.now(timezone.utc)
        tokens = self.issuer.for_player(player.id, role=player.role)
        await self._save_session(player.id, tokens.refresh_token)
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=self.issuer.access_ttl,
            player=self._player_dto(player),
        )

    async def logout(self, req: LogoutRequest) -> None:
        token_hash = self._hash_token(req.refresh_token)
        await self.session.execute(
            update(SessionModel)
            .where(SessionModel.refresh_token_hash == token_hash)
            .values(revoked_at=datetime.now(timezone.utc))
        )

    async def revoke_all_sessions(self, player_id: int) -> int:
        result = await self.session.execute(
            update(SessionModel)
            .where(SessionModel.player_id == player_id, SessionModel.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
            .returning(SessionModel.id)
        )
        return len(list(result.scalars()))

    async def set_locale(self, player_id: int, locale: str) -> PlayerDTO:
        """Update the player's preferred locale. Used by the bot's /language command."""
        from nationcraft.core.config import settings
        supported = settings.supported_locales_list
        if locale not in supported:
            raise ValidationError(
                f"unsupported locale '{locale}'. Supported: {', '.join(supported)}",
                code="unsupported_locale",
            )
        # Use a SELECT to avoid stale identity-map entries from prior commits.
        from sqlalchemy import select
        player = await self.session.scalar(
            select(PlayerModel).where(PlayerModel.id == player_id)
        )
        if player is None:
            raise NotFoundError("player not found")
        player.locale = locale
        await self.session.flush()
        return self._player_dto(player)

    async def get_player(self, player_id: int) -> PlayerDTO:
        """Return the current player state (used by the bot to read locale, etc.)."""
        from sqlalchemy import select
        player = await self.session.scalar(
            select(PlayerModel).where(PlayerModel.id == player_id)
        )
        if player is None:
            raise NotFoundError("player not found")
        return self._player_dto(player)

    async def get_by_telegram_id(self, telegram_id: int) -> PlayerModel | None:
        """Look up a player by Telegram ID. Returns None if not found."""
        return await self.session.scalar(
            select(PlayerModel).where(PlayerModel.telegram_id == telegram_id)
        )

    async def reset_password(
        self, telegram_id: int, old_password: str, new_password: str
    ) -> None:
        """Reset a player's password after verifying the old one."""
        from sqlalchemy import select
        player = await self.session.scalar(
            select(PlayerModel).where(PlayerModel.telegram_id == telegram_id)
        )
        if player is None or not player.password_hash:
            raise AuthenticationError("invalid credentials")
        # Verify old password ASYNC.
        await self.hasher.verify_async(old_password, player.password_hash)
        # Set new password ASYNC.
        player.password_hash = await self.hasher.hash_async(new_password)
        await self.session.flush()
        # Revoke all existing sessions (force re-login everywhere).
        await self.revoke_all_sessions(player.id)
        await event_bus.publish(Event(
            type="player.password_reset",
            player_id=player.id,
            payload={"telegram_id": telegram_id},
        ))

    async def promote_to_admin(self, telegram_id: int, role: str = "admin") -> PlayerDTO:
        """Promote a player to moderator/admin/owner. Only owners can call this."""
        from sqlalchemy import select
        player = await self.session.scalar(
            select(PlayerModel).where(PlayerModel.telegram_id == telegram_id)
        )
        if player is None:
            raise NotFoundError("player not found")
        if role not in ("moderator", "admin", "owner"):
            raise ValidationError(
                f"invalid role '{role}'. Allowed: moderator, admin, owner",
                code="invalid_role",
            )
        player.role = role
        await self.session.flush()
        return self._player_dto(player)

    async def _save_session(self, player_id: int, refresh_token: str) -> None:
        self.session.add(SessionModel(
            player_id=player_id,
            refresh_token_hash=self._hash_token(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.issuer.refresh_ttl),
        ))
        await self.session.flush()

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _player_dto(p: PlayerModel) -> PlayerDTO:
        return PlayerDTO(
            id=p.id,
            telegram_id=p.telegram_id,
            username=p.username,
            locale=p.locale,
            role=p.role,
            is_banned=p.is_banned,
            world_id=p.world_id,
            country_id=p.country_id,
            last_login_at=p.last_login_at,
            created_at=p.created_at,
        )
