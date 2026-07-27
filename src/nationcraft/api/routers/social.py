"""Alliance, diplomacy, missions, notifications, rankings endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from nationcraft.api.dependencies import CurrentPlayer, SessionDep
from nationcraft.api.schemas.envelope import success
from nationcraft.application.dto.game import (
    AllianceCreateRequest,
    AllianceInviteRequest,
    DiplomacyRequest,
    MissionClaimRequest,
)
from nationcraft.application.services import (
    AllianceService,
    DiplomacyService,
    MissionService,
    NotificationService,
    RankingService,
)
from nationcraft.infrastructure.db.models import PlayerModel

router = APIRouter(prefix="/social", tags=["social"])


async def _resolve_country(session, player_id: int) -> int:  # type: ignore[no-untyped-def]
    p = await session.get(PlayerModel, player_id)
    if not p or not p.country_id:
        from nationcraft.core.exceptions import GameRuleError
        raise GameRuleError("player has no country")
    return p.country_id


# ---------- Alliances ----------

@router.post("/alliance/create", response_model=None)
async def create_alliance(
    req: AllianceCreateRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = AllianceService(session)
    a = await svc.create(cid, req.name, req.tag)
    return success({"id": a.id, "name": a.name, "tag": a.tag})


@router.post("/alliance/invite", response_model=None)
async def invite_to_alliance(
    req: AllianceInviteRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = AllianceService(session)
    # Lookup inviter's alliance.
    from sqlalchemy import select
    from nationcraft.infrastructure.db.models import AllianceMemberModel
    am = await session.scalar(
        select(AllianceMemberModel).where(AllianceMemberModel.country_id == cid)
    )
    if am is None:
        from nationcraft.core.exceptions import GameRuleError
        raise GameRuleError("not in an alliance")
    await svc.invite(am.alliance_id, cid, req.country_id)
    return success({"ok": True})


@router.post("/alliance/join/{alliance_id}", response_model=None)
async def join_alliance(
    alliance_id: int, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = AllianceService(session)
    await svc.join(alliance_id, cid)
    return success({"ok": True})


@router.post("/alliance/leave", response_model=None)
async def leave_alliance(session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = AllianceService(session)
    await svc.leave(cid)
    return success({"ok": True})


# ---------- Diplomacy ----------

@router.post("/diplomacy", response_model=None)
async def set_diplomacy(
    req: DiplomacyRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = DiplomacyService(session)
    d = await svc.set_status(cid, req.other_country_id, req.status)
    return success({"a": d.country_a_id, "b": d.country_b_id, "status": d.status.value})


@router.get("/diplomacy", response_model=None)
async def list_diplomacy(session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = DiplomacyService(session)
    rows = await svc.list_for_country(cid)
    return success([{
        "a": d.country_a_id, "b": d.country_b_id, "status": d.status.value,
    } for d in rows])


# ---------- Missions ----------

@router.get("/missions", response_model=None)
async def list_missions(session: SessionDep, player_id: CurrentPlayer) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = MissionService(session)
    rows = await svc.list_for_country(cid)
    return success([{
        "id": m.id, "key": m.key, "category": m.category.value,
        "status": m.status.value, "progress": m.progress,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
    } for m in rows])


@router.post("/mission/claim", response_model=None)
async def claim_mission(
    req: MissionClaimRequest, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    cid = await _resolve_country(session, player_id)
    svc = MissionService(session)
    rewards = await svc.claim(cid, req.mission_id)
    return success({"rewards": rewards})


# ---------- Notifications ----------

@router.get("/notifications", response_model=None)
async def list_notifications(
    session: SessionDep, player_id: CurrentPlayer,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    svc = NotificationService(session)
    rows = await svc.list_for_player(player_id, limit=limit)
    return success([{
        "id": n.id, "level": n.level.value, "title": n.title, "body": n.body,
        "data": n.data, "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat(),
    } for n in rows])


@router.post("/notifications/{nid}/read", response_model=None)
async def mark_read(
    nid: int, session: SessionDep, player_id: CurrentPlayer
) -> dict:
    svc = NotificationService(session)
    await svc.mark_read(nid)
    return success({"ok": True})


# ---------- Rankings ----------

@router.get("/rankings/{world_id}", response_model=None)
async def rankings(
    world_id: int, session: SessionDep, player_id: CurrentPlayer,
    metric: str = Query(default="population"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    svc = RankingService(session)
    rows = await svc.by_metric(world_id, metric, limit=limit)
    return success([r.model_dump() for r in rows])
