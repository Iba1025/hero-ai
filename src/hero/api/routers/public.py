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
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hero.api import background
from hero.api.deps import get_chat_vlm, get_db_session, get_graph, get_session_factory
from hero.api.pipeline import resume_ticket_pipeline, run_ticket_pipeline
from hero.api.ratelimit import allow as rate_allow
from hero.config import get_settings
from hero.nova.bridge import handle_tenant_message, record_opening
from hero.nova.guardrails import check_message
from hero.storage.media import presigned_upload_url
from hero.storage.models import Building, ConversationMessage, Ticket
from hero.storage.repo import (
    append_conversation_message,
    create_media,
    create_ticket,
    get_building_by_slug,
    get_ticket_by_public_slug,
    has_conversation,
    list_conversation_messages,
    list_ticket_events,
    update_pipeline_status,
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
    # BL-17 (H1): true while the pipeline is working in the background —
    # deliberately a plain boolean, no pipeline vocabulary across this boundary.
    working: bool = False


class PublicAnswerRequest(BaseModel):
    answer: str


# ── Nova chat (Phase 5 STEP 3, DEC-23/24) ───────────────────────────────────


class PublicChatMessage(BaseModel):
    """One transcript entry. `kind` is chat-envelope vocabulary (render hint:
    escalation/redirect banners vs ordinary bubbles) — never pipeline
    vocabulary, and no guardrail internals cross the boundary."""

    sender: str
    kind: str
    body: str
    created_at: str


class PublicChatStartRequest(BaseModel):
    message: str
    contact: str
    photos: list[PublicPhoto] = Field(default_factory=list)


class PublicChatStartResponse(BaseModel):
    # None when the opener was redirected (DEC-24): nothing was created.
    status_slug: str | None
    status_path: str | None
    reply: PublicChatMessage


class PublicChatMessageRequest(BaseModel):
    message: str
    # BL-22 (M scope): mid-chat photo attach — pointers only (INV-3). The
    # photos join the ticket's media + transcript; they do NOT feed a run
    # already in flight (mid-run evidence injection is future work).
    photos: list[PublicPhoto] = Field(default_factory=list)


class PublicChatReplyResponse(BaseModel):
    reply: PublicChatMessage
    working: bool


class PublicConversationResponse(BaseModel):
    state: str
    working: bool
    messages: list[PublicChatMessage]


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


async def _rate_gate(session: AsyncSession, key: str, *, max_events: int) -> None:
    """Postgres-backed sliding window (Phase 5 STEP 3, BL-15) — commits the
    event immediately, so it must run before any other write in the handler."""
    if not await rate_allow(session, key, max_events=max_events):
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


def _status_response(
    ticket: Ticket, question: str | None, *, working: bool | None = None
) -> PublicStatusResponse:
    if working is None:
        working = ticket.pipeline_status in ("queued", "running")
    state = "working on it" if working else _PLAIN_STATUS.get(ticket.status, "looking into it")
    return PublicStatusResponse(
        state=state,
        question=None if working else question,
        description=ticket.description,
        created_at=ticket.created_at.isoformat(),
        working=working,
    )


@router.get("/buildings/{slug}", response_model=PublicBuildingResponse)
async def get_building(
    slug: str,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicBuildingResponse:
    """Validate a building link and return only its display name."""
    building = await _require_building(session, slug)
    return PublicBuildingResponse(name=building.name)


def _presign_photo(
    building_id: uuid.UUID, request: PublicPresignRequest, settings: Any
) -> PublicPresignResponse:
    """Shared presign core (INV-3: bytes go straight to R2). Image-only,
    size-capped at declaration time — the declared ContentType is part of
    the signature, so a mismatched upload is rejected by R2."""
    if not request.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image uploads are accepted")
    if not 0 < request.size_bytes <= settings.public_max_photo_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Photo too large (max {settings.public_max_photo_bytes // (1024 * 1024)} MB)",
        )

    safe_name = _FILENAME_SAFE.sub("_", request.filename.rsplit("/", 1)[-1])[-100:] or "photo"
    object_key = f"public-intake/{building_id}/{uuid.uuid4()}/{safe_name}"
    url = presigned_upload_url(settings, object_key=object_key, content_type=request.content_type)
    return PublicPresignResponse(upload_url=url, object_key=object_key)


@router.post("/buildings/{slug}/presign", response_model=PublicPresignResponse)
async def public_presign(
    slug: str,
    request: PublicPresignRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicPresignResponse:
    """Presigned PUT for an intake photo — building link holders."""
    building = await _require_building(session, slug)
    settings = get_settings()
    await _rate_gate(session, f"presign:{slug}", max_events=settings.public_presign_rate_per_hour)
    return _presign_photo(building.id, request, settings)


@router.post("/status/{status_slug}/presign", response_model=PublicPresignResponse)
async def public_status_presign(
    status_slug: str,
    request: PublicPresignRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicPresignResponse:
    """Presigned PUT for a mid-chat photo (BL-22) — status link holders.
    Same image-only/size caps as the intake presign; keys live under the
    ticket's building so downstream validation is identical."""
    ticket = await _require_public_ticket(session, status_slug)
    settings = get_settings()
    await _rate_gate(
        session, f"presign:{status_slug}", max_events=settings.public_presign_rate_per_hour
    )
    return _presign_photo(ticket.building_id, request, settings)


def _validate_intake(
    description: str, contact: str, photos: list[PublicPhoto], settings: Any
) -> tuple[str, str]:
    """Shared form/chat intake validation. Returns (description, contact) stripped."""
    description = description.strip()
    contact = contact.strip()
    if not description or len(description) > _MAX_DESCRIPTION_CHARS:
        raise HTTPException(status_code=422, detail="Please describe the problem")
    if not contact or len(contact) > _MAX_CONTACT_CHARS:
        raise HTTPException(status_code=422, detail="A phone number or email is required")
    _validate_photos(photos, settings)
    return description, contact


def _validate_photos(photos: list[PublicPhoto], settings: Any) -> None:
    if len(photos) > settings.public_max_photos:
        raise HTTPException(status_code=422, detail=f"At most {settings.public_max_photos} photos")
    for photo in photos:
        if not photo.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail="Only image uploads are accepted")
        if not photo.object_key.startswith("public-intake/"):
            raise HTTPException(status_code=422, detail="Unrecognized photo reference")


async def _create_public_ticket(
    session: AsyncSession,
    building: Building,
    *,
    description: str,
    contact: str,
    photos: list[PublicPhoto],
) -> tuple[uuid.UUID, str]:
    """Ticket + media rows for a public intake (form or chat). Does not commit."""
    status_slug = secrets.token_urlsafe(16)
    ticket = await create_ticket(
        session,
        org_id=building.org_id,
        building_id=building.id,
        description=description,
        tenant_contact=contact,
        public_slug=status_slug,
    )
    for photo in photos:
        await create_media(
            session,
            ticket_id=ticket.id,
            object_key=photo.object_key,
            media_type=photo.content_type,
            sha256=photo.sha256,
        )
    return ticket.id, status_slug  # capture id before commit — no lazy refresh later


async def _spawn_pipeline(ticket_id: uuid.UUID, photos: list[PublicPhoto]) -> None:
    """BL-17 (H1): respond immediately; the graph runs in a background task."""
    graph = await get_graph()
    background.spawn(
        run_ticket_pipeline(
            graph,
            ticket_id,
            # MediaRef wants the coarse kind ("image"), not the MIME type —
            # content_type is validated image/* upstream. sha256 is best-effort.
            media=[
                {
                    "object_key": p.object_key,
                    "media_type": p.content_type.split("/")[0],
                    "sha256": p.sha256,
                }
                for p in photos
            ],
            sensor_readings=[],
            session_factory=get_session_factory(),
        )
    )


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
    await _rate_gate(session, f"intake:{slug}", max_events=settings.public_intake_rate_per_hour)

    description, contact = _validate_intake(
        request.description, request.contact, request.photos, settings
    )
    ticket_id, status_slug = await _create_public_ticket(
        session, building, description=description, contact=contact, photos=request.photos
    )
    await session.commit()
    await _spawn_pipeline(ticket_id, request.photos)
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
    """Tenant answers the CLARIFY question. The answer is accepted immediately
    (BL-17/H1) and resumed in a background task — through the single resume
    path (hero.api.resume, spec §4), same as the operator endpoint."""
    ticket = await _require_public_ticket(session, status_slug)
    settings = get_settings()
    await _rate_gate(
        session, f"answer:{status_slug}", max_events=settings.public_answer_rate_per_hour
    )

    answer = request.answer.strip()
    if not answer or len(answer) > _MAX_DESCRIPTION_CHARS:
        raise HTTPException(status_code=422, detail="Please write an answer")

    if ticket.pipeline_status == "running":
        raise HTTPException(status_code=409, detail="We're already working on it")
    question = await _pending_question(session, ticket)
    if ticket.status != "clarifying" or question is None:
        raise HTTPException(status_code=400, detail="No question is waiting")

    ticket_id = ticket.id
    await update_pipeline_status(session, ticket_id, "running")
    await session.commit()

    graph = await get_graph()
    background.spawn(
        resume_ticket_pipeline(
            graph, ticket_id, answer=answer, session_factory=get_session_factory()
        )
    )
    return _status_response(ticket, None, working=True)


# ── Nova chat endpoints (Phase 5 STEP 3, DEC-23/24) ─────────────────────────


def _chat_message(m: ConversationMessage) -> PublicChatMessage:
    return PublicChatMessage(
        sender=m.sender, kind=m.kind, body=m.body, created_at=m.created_at.isoformat()
    )


@router.post("/buildings/{slug}/conversations", response_model=PublicChatStartResponse)
async def public_chat_start(
    slug: str,
    request: PublicChatStartRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicChatStartResponse:
    """Tenant opens a Nova conversation. The first allowed message IS the
    intake: same ticket, same org, same full pipeline as the form (DEC-23 —
    depth unchanged; Nova acknowledges with fixed copy while the run works).

    Guardrails run before anything is created: a redirected opener (legal/
    medical/safety/injection — DEC-24) gets fixed copy and creates NOTHING;
    a hazard opener creates the ticket, stamps it escalated immediately, and
    still runs the pipeline so the ledger records the run honestly.
    """
    building = await _require_building(session, slug)
    settings = get_settings()
    await _rate_gate(session, f"intake:{slug}", max_events=settings.public_intake_rate_per_hour)

    message, contact = _validate_intake(request.message, request.contact, request.photos, settings)

    decision = check_message(message)
    if decision.action == "redirect":
        # Not a maintenance report — fixed copy, no ticket, no model, no rows.
        return PublicChatStartResponse(
            status_slug=None,
            status_path=None,
            reply=PublicChatMessage(
                sender="nova",
                kind="redirect",
                body=decision.reply or "",
                created_at=datetime.now(UTC).isoformat(),
            ),
        )

    ticket_id, status_slug = await _create_public_ticket(
        session, building, description=message, contact=contact, photos=request.photos
    )
    reply = await record_opening(session, ticket_id=ticket_id, message=message, decision=decision)
    reply_out = _chat_message(reply)
    await session.commit()
    await _spawn_pipeline(ticket_id, request.photos)
    return PublicChatStartResponse(
        status_slug=status_slug, status_path=f"#/status/{status_slug}", reply=reply_out
    )


@router.get("/status/{status_slug}/messages", response_model=PublicConversationResponse)
async def public_conversation(
    status_slug: str,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicConversationResponse:
    """The full transcript for exactly the ticket this slug names — the chat
    UI reloads and polls this (async diagnosis arrives as a message)."""
    ticket = await _require_public_ticket(session, status_slug)
    messages = await list_conversation_messages(session, ticket.id)
    working = ticket.pipeline_status in ("queued", "running")
    state = "working on it" if working else _PLAIN_STATUS.get(ticket.status, "looking into it")
    return PublicConversationResponse(
        state=state, working=working, messages=[_chat_message(m) for m in messages]
    )


@router.post("/status/{status_slug}/messages", response_model=PublicChatReplyResponse)
async def public_chat_message(
    status_slug: str,
    request: PublicChatMessageRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PublicChatReplyResponse:
    """One tenant chat message, routed by the bridge (hero.nova.bridge):
    guardrails first, then — when the run is parked at CLARIFY — the message
    is the clarify answer, resumed through the single resume path exactly
    like POST /answer. Everything else gets a conversational reply."""
    ticket = await _require_public_ticket(session, status_slug)
    settings = get_settings()
    await _rate_gate(
        session, f"chat:{status_slug}", max_events=settings.public_message_rate_per_hour
    )

    message = request.message.strip()
    if not message or len(message) > _MAX_DESCRIPTION_CHARS:
        raise HTTPException(status_code=422, detail="Please write a message")
    _validate_photos(request.photos, settings)
    if not await has_conversation(session, ticket.id):
        # Form-intake tickets keep the status page + POST /answer flow.
        raise HTTPException(status_code=400, detail="This ticket has no conversation")

    # BL-22: mid-chat photos join the ticket's media + transcript BEFORE the
    # text turn (so the transcript reads photo → message → reply). A redirected
    # message keeps nothing (DEC-24 spirit: not a maintenance report). Photos
    # do NOT feed a run already in flight — mid-run evidence injection is
    # future work (single-resume-path rule).
    if request.photos and check_message(message).action != "redirect":
        for photo in request.photos:
            await create_media(
                session,
                ticket_id=ticket.id,
                object_key=photo.object_key,
                media_type=photo.content_type,
                sha256=photo.sha256,
            )
        count = len(request.photos)
        await append_conversation_message(
            session,
            ticket_id=ticket.id,
            sender="tenant",
            kind="photo",
            body=f"{count} photo{'s' if count > 1 else ''} attached",
        )

    question = await _pending_question(session, ticket)
    turn = await handle_tenant_message(
        get_chat_vlm(),
        session,
        ticket=ticket,
        message=message,
        pending_question=question,
        settings=settings,
    )
    reply_out = _chat_message(turn.nova)

    if turn.resume_answer is not None:
        ticket_id = ticket.id
        await update_pipeline_status(session, ticket_id, "running")
        await session.commit()
        graph = await get_graph()
        background.spawn(
            resume_ticket_pipeline(
                graph, ticket_id, answer=turn.resume_answer, session_factory=get_session_factory()
            )
        )
        return PublicChatReplyResponse(reply=reply_out, working=True)

    await session.commit()
    working = ticket.pipeline_status in ("queued", "running")
    return PublicChatReplyResponse(reply=reply_out, working=working)
