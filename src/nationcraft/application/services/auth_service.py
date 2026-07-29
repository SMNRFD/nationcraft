"""Authentication service: register, login, refresh, logout, sessions."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.application.dto.auth import (
    LoginRequest,
    LogoutRequest,
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
        """Register a new player account.

        This method creates a new player with the provided Telegram ID, username,
        and password. It hashes the password using Argon2id, stores the player
        in the database, and issues a new access/refresh token pair.

        Args:
            req (RegisterRequest): Registration data including Telegram ID,
                username, password, and optional locale.

        Returns:
            TokenResponse: Access and refresh tokens along with player profile data.

        Raises:
            ConflictError: If a player with the given Telegram ID already exists.
            ValidationError: If the input data fails validation.
        """
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
        """Authenticate a player and create a new session.

        This method validates the player's credentials, updates the last login
        timestamp, issues new access and refresh tokens, and stores the session.

        Args:
            req (LoginRequest): Login credentials including Telegram ID and password.

        Returns:
            TokenResponse: Access and refresh tokens with player profile.

        Raises:
            AuthenticationError: If credentials are invalid or the account is banned.
        """
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
        """Refresh an expired access token using a valid refresh token.

        This method validates the refresh token, verifies it against the stored
        session, revokes the old session, and issues a new token pair.

        Args:
            req (RefreshRequest): The refresh token to validate.

        Returns:
            TokenResponse: A new set of access and refresh tokens.

        Raises:
            AuthenticationError: If the refresh token is invalid, expired, or revoked.
        """
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
        """Log out a player by revoking their refresh token.

        This method invalidates the session associated with the provided
        refresh token, effectively logging the player out from that device.

        Args:
            req (LogoutRequest): The refresh token to revoke.

        Raises:
            No exception is raised if the token is already revoked or missing.
        """
        token_hash = self._hash_token(req.refresh_token)
        await self.session.execute(
            update(SessionModel)
            .where(SessionModel.refresh_token_hash == token_hash)
            .values(revoked_at=datetime.now(timezone.utc))
        )

    async def revoke_all_sessions(self, player_id: int) -> int:
        """Revoke all active sessions for a given player.

        This method forces a logout from all devices by revoking every
        non-revoked session associated with the player ID.

        Args:
            player_id (int): The ID of the player whose sessions should be revoked.

        Returns:
            int: The number of sessions that were revoked.
        """
        result = await self.session.execute(
            update(SessionModel)
            .where(SessionModel.player_id == player_id, SessionModel.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
            .returning(SessionModel.id)
        )
        return len(list(result.scalars()))

    async def set_locale(self, player_id: int, locale: str) -> PlayerDTO:
        """Update the player's preferred locale.

        This method changes the locale setting for a player, which affects
        language and regional formatting throughout the game.

        Args:
            player_id (int): The ID of the player to update.
            locale (str): The new locale code (e.g., 'en', 'fa').

        Returns:
            PlayerDTO: The updated player profile.

        Raises:
            ValidationError: If the locale is not in the supported list.
            NotFoundError: If the player does not exist.
        """
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
        """Retrieve the current state of a player.

        This method returns the player's profile data, including locale,
        role, and other metadata used by the bot and API.

        Args:
            player_id (int): The ID of the player to fetch.

        Returns:
            PlayerDTO: The player profile data.

        Raises:
            NotFoundError: If no player exists with the given ID.
        """
        from sqlalchemy import select
        player = await self.session.scalar(
            select(PlayerModel).where(PlayerModel.id == player_id)
        )
        if player is None:
            raise NotFoundError("player not found")
        return self._player_dto(player)

    async def get_by_telegram_id(self, telegram_id: int) -> PlayerModel | None:
        """Look up a player by their Telegram ID.

        This method is primarily used by the bot to find or verify players
        during Telegram interactions.

        Args:
            telegram_id (int): The Telegram user ID to search for.

        Returns:
            PlayerModel | None: The player model if found, otherwise None.
        """
        return await self.session.scalar(
            select(PlayerModel).where(PlayerModel.telegram_id == telegram_id)
        )

    async def reset_password(
        self, telegram_id: int, old_password: str, new_password: str
    ) -> None:
        """Reset a player's password after verifying the old one.

        This method validates the old password, hashes the new one,
        updates the database, and revokes all existing sessions to force
        re-authentication on all devices.

        Args:
            telegram_id (int): The Telegram ID of the player.
            old_password (str): The current password for verification.
            new_password (str): The new password to set.

        Raises:
            AuthenticationError: If the old password is incorrect or the
                player does not exist.
        """
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
        """Promote a player to a higher role (moderator, admin, or owner).

        This method updates the player's role, granting them elevated
        permissions. It is typically invoked by an existing owner.

        Args:
            telegram_id (int): The Telegram ID of the player to promote.
            role (str, optional): The new role. Must be one of:
                'moderator', 'admin', 'owner'. Defaults to 'admin'.

        Returns:
            PlayerDTO: The updated player profile.

        Raises:
            NotFoundError: If the player does not exist.
            ValidationError: If the role is not in the allowed list.
        """
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
        """Store a new session for the player."""
        self.session.add(SessionModel(
            player_id=player_id,
            refresh_token_hash=self._hash_token(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.issuer.refresh_ttl),
        ))
        await self.session.flush()

    @staticmethod
    def _hash_token(token: str) -> str:
        """Hash a token using SHA256 for storage."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _player_dto(p: PlayerModel) -> PlayerDTO:
        """Convert a PlayerModel to a PlayerDTO."""
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
