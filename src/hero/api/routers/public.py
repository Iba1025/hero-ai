"""Public tenant intake + status (P4-4) — no accounts, no login.

Trust boundary: everything here is reachable by anyone holding a building
link (unguessable building slug) or a ticket status link (unguessable
per-ticket slug). Responses expose NOTHING org-scoped beyond the building's
display name and the ticket's own plain-language status — no trade/urgency/
diagnosis/org ids ever cross this boundary.

Abuse basics (P4-4d): per-slug rate limits, photo count + size caps,
image-only presigns. No CAPTCHA at pilot scale (deliberate).
"""

from __future__ import annotations

import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hero.api.deps import get_db_session, get_graph
from hero.api.pipeline import run_and_persist
from hero.api.ratelimit import limiter
from hero.api.resume import NotAwaitingClarificationError, resume_with_answer
from hero.config import get_settings
from hero.storage.media import presigned_upload_url
from hero.storage.models import Building, Ticket
from hero.storage.repo import (
    create_media,
    create_ticket,
    get_building_by_slug,
    get_ticket_by_public_slug,
    list_ticket_events,
)

router = APIRouter()

# Plain language for tenants — never pipeline vocabulary (P4-4c).
_PLAIN_STATUS: dict[str, str] = {
    "open": "received",
    "clarifying": "question for you",
    "escalated": "looking into it",
    "diagnosed": "being handled",
    "resolved": "resolved",
}

_MAX_DESCRIPTION_CHARS = 4000
_MAX_CONTACT_CHARS = 200
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]")


class PublicBuildingResponse(BaseModel):
    name: str


class PublicPresignRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class PublicPresignResponse(BaseModel):
    upload_url: str
    object_key: str


class PublicPhoto(BaseModel):
    object_key: str
    content_type: str
    sha256: str | None = None  # best-effort: no crypto.subtle on http LAN phones


class PublicIntakeRequest(BaseModel):
    description: str
    contact: str
    photos: list[PublicPhoto] = Field(default_factory=list)


class PublicIntakeResponse(BaseModel):
    status_slug: str
    status_path: str  # SPA hash route for the confirmation screen


class PublicStatusResponse(BaseModel):
    state: str  # plain-language phrase — the contract of this endpoint
    question: str | None = None
    description: str
    created_at: str


class PublicAnswerRequest(BaseModel):
    answer: str


async def _require_building(session: AsyncSession, slug: str) -> Building:
    building = await get_building_by_slug(session, slug)
    if building is None:
        raise HTTPException(status_code=404, detail="Unknown building link")
    return building


async def _require_public_ticket(session: AsyncSession, status_slug: str) -> Ticket:
    ticket = await get_ticket_by_public_slug(session, status_slug)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Unknown status link")
    return ticket


def _rate_gate(key: str, *, max_events: int) -> None:
    if not limiter.allow(key, max_events=max_events):
        raise HTTPException(status_code=429, detail="Too many requests — try again later")


async def _pending_question(session: AsyncSession, ticket: Ticket) -> str | None:
    """The open CLARIFY question, from the ledger journal (no checkpointer read)."""
    if ticket.status != "clarifying":
        return None
    events = await list_ticket_events(session, ticket.id)
    for ev in reversed(events):
        if ev.state == "clarify_pending":
            q = ev.payload.get("question")
            return q if isinstance(q, str) else None
    return None


def _status_response(ticket: Ticket, question: str | None) -> PublicStatusResponse:
    return PublicStatusResponse(
        state=_PLAIN_STATUS.get(ticket.status, "looking into it"),
        question=question,
        description=ticket.description,
        created_at=ticket.created_at.isoformat(),
    )


@router.get("/buildings/{slug}", response_model=PublicBuildingResponse)
async def get_building(
    slug: str,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicBuildingResponse:
    """Validate a building link and return only its display name."""
    building = await _require_building(session, slug)
    return PublicBuildingResponse(name=building.name)


@router.post("/buildings/{slug}/presign", response_model=PublicPresignResponse)
async def public_presign(
    slug: str,
    request: PublicPresignRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicPresignResponse:
    """Presigned PUT for a tenant photo (INV-3: bytes go straight to R2).

    Image-only, size-capped at declaration time — the declared ContentType is
    part of the signature, so a mismatched upload is rejected by R2.
    """
    building = await _require_building(session, slug)
    settings = get_settings()
    _rate_gate(f"presign:{slug}", max_events=settings.public_presign_rate_per_hour)

    if not request.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image uploads are accepted")
    if not 0 < request.size_bytes <= settings.public_max_photo_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Photo too large (max {settings.public_max_photo_bytes // (1024 * 1024)} MB)",
        )

    safe_name = _FILENAME_SAFE.sub("_", request.filename.rsplit("/", 1)[-1])[-100:] or "photo"
    object_key = f"public-intake/{building.id}/{uuid.uuid4()}/{safe_name}"
    url = presigned_upload_url(settings, object_key=object_key, content_type=request.content_type)
    return PublicPresignResponse(upload_url=url, object_key=object_key)


@router.post("/buildings/{slug}/tickets", response_model=PublicIntakeResponse)
async def public_intake(
    slug: str,
    request: PublicIntakeRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicIntakeResponse:
    """Tenant files a problem: ticket lands in the building's org and runs the
    same pipeline as an operator-created ticket (hero.api.pipeline)."""
    building = await _require_building(session, slug)
    settings = get_settings()
    _rate_gate(f"intake:{slug}", max_events=settings.public_intake_rate_per_hour)

    description = request.description.strip()
    contact = request.contact.strip()
    if not description or len(description) > _MAX_DESCRIPTION_CHARS:
        raise HTTPException(status_code=422, detail="Please describe the problem")
    if not contact or len(contact) > _MAX_CONTACT_CHARS:
        raise HTTPException(status_code=422, detail="A phone number or email is required")
    if len(request.photos) > settings.public_max_photos:
        raise HTTPException(status_code=422, detail=f"At most {settings.public_max_photos} photos")
    for photo in request.photos:
        if not photo.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail="Only image uploads are accepted")
        if not photo.object_key.startswith("public-intake/"):
            raise HTTPException(status_code=422, detail="Unrecognized photo reference")

    status_slug = secrets.token_urlsafe(16)
    ticket = await create_ticket(
        session,
        org_id=building.org_id,
        building_id=building.id,
        description=description,
        tenant_contact=contact,
        public_slug=status_slug,
    )
    for photo in request.photos:
        await create_media(
            session,
            ticket_id=ticket.id,
            object_key=photo.object_key,
            media_type=photo.content_type,
            sha256=photo.sha256,
        )

    graph = await get_graph()
    await run_and_persist(
        graph,
        session,
        ticket,
        # MediaRef wants the coarse kind ("image"), not the MIME type —
        # content_type is validated image/* above. sha256 is best-effort.
        media=[
            {
                "object_key": p.object_key,
                "media_type": p.content_type.split("/")[0],
                "sha256": p.sha256,
            }
            for p in request.photos
        ],
        sensor_readings=[],
    )
    return PublicIntakeResponse(status_slug=status_slug, status_path=f"#/status/{status_slug}")


@router.get("/status/{status_slug}", response_model=PublicStatusResponse)
async def public_status(
    status_slug: str,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicStatusResponse:
    """Plain-language status for exactly the ticket this slug names."""
    ticket = await _require_public_ticket(session, status_slug)
    question = await _pending_question(session, ticket)
    return _status_response(ticket, question)


@router.post("/status/{status_slug}/answer", response_model=PublicStatusResponse)
async def public_answer(
    status_slug: str,
    request: PublicAnswerRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicStatusResponse:
    """Tenant answers the CLARIFY question — through the single resume path
    (hero.api.resume, spec §4), same as the operator endpoint."""
    ticket = await _require_public_ticket(session, status_slug)
    settings = get_settings()
    _rate_gate(f"answer:{status_slug}", max_events=settings.public_answer_rate_per_hour)

    answer = request.answer.strip()
    if not answer or len(answer) > _MAX_DESCRIPTION_CHARS:
        raise HTTPException(status_code=422, detail="Please write an answer")

    graph = await get_graph()
    try:
        result = await resume_with_answer(graph, session, ticket_id=ticket.id, answer=answer)
    except NotAwaitingClarificationError as exc:
        raise HTTPException(status_code=400, detail="No question is waiting") from exc

    next_question = result.get("pending_question")
    return _status_response(ticket, next_question if isinstance(next_question, str) else None)
