"""Alliance service."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nationcraft.core.events import Event, event_bus
from nationcraft.core.exceptions import ConflictError, GameRuleError, NotFoundError
from nationcraft.domain.entities import Alliance
from nationcraft.domain.enums import AllianceRole
from nationcraft.infrastructure.db.models import (
    AllianceMemberModel,
    AllianceModel,
    CountryModel,
)


class AllianceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, leader_country_id: int, name: str, tag: str) -> Alliance:
        leader = await self.session.get(CountryModel, leader_country_id)
        if leader is None:
            raise NotFoundError("leader country not found")
        # Already in an alliance?
        existing = await self.session.scalar(
            select(AllianceMemberModel).where(AllianceMemberModel.country_id == leader_country_id)
        )
        if existing is not None:
            raise ConflictError("country already in an alliance")
        alliance = AllianceModel(
            world_id=leader.world_id, name=name, tag=tag.upper(),
            leader_id=leader_country_id, treasury=0.0,
        )
        self.session.add(alliance)
        await self.session.flush()
        self.session.add(AllianceMemberModel(
            alliance_id=alliance.id, country_id=leader_country_id,
            role=AllianceRole.LEADER.value,
        ))
        await self.session.flush()
        await event_bus.publish(Event(
            type="alliance.created", world_id=leader.world_id,
            payload={"alliance_id": alliance.id, "name": name, "leader_id": leader_country_id},
        ))
        return Alliance(
            id=alliance.id, world_id=alliance.world_id, name=alliance.name,
            tag=alliance.tag, leader_id=alliance.leader_id, treasury=alliance.treasury,
            created_at=alliance.created_at,
        )

    async def invite(self, alliance_id: int, inviter_id: int, invitee_id: int) -> None:
        alliance = await self.session.get(AllianceModel, alliance_id)
        if alliance is None:
            raise NotFoundError("alliance not found")
        # Verify inviter is officer+.
        inviter = await self.session.scalar(
            select(AllianceMemberModel).where(
                AllianceMemberModel.alliance_id == alliance_id,
                AllianceMemberModel.country_id == inviter_id,
            )
        )
        if inviter is None or inviter.role not in (AllianceRole.LEADER.value, AllianceRole.OFFICER.value):
            raise GameRuleError("insufficient alliance permissions")
        existing = await self.session.scalar(
            select(AllianceMemberModel).where(
                AllianceMemberModel.country_id == invitee_id
            )
        )
        if existing is not None:
            raise ConflictError("country already in an alliance")
        await event_bus.publish(Event(
            type="alliance.invited", world_id=alliance.world_id,
            payload={"alliance_id": alliance_id, "inviter_id": inviter_id, "invitee_id": invitee_id},
        ))

    async def join(self, alliance_id: int, country_id: int) -> None:
        existing = await self.session.scalar(
            select(AllianceMemberModel).where(AllianceMemberModel.country_id == country_id)
        )
        if existing is not None:
            raise ConflictError("already in an alliance")
        self.session.add(AllianceMemberModel(
            alliance_id=alliance_id, country_id=country_id,
            role=AllianceRole.MEMBER.value,
        ))
        await self.session.flush()

    async def leave(self, country_id: int) -> None:
        m = await self.session.scalar(
            select(AllianceMemberModel).where(AllianceMemberModel.country_id == country_id)
        )
        if m is None:
            raise NotFoundError("country not in any alliance")
        await self.session.delete(m)
        await self.session.flush()
