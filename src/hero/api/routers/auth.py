"""Auth endpoints — POST /auth/login, POST /auth/logout, GET /auth/me (P4-1).

Session = HS256 JWT in an httponly cookie. No self-signup: users are
seeded via `python -m hero.auth seed` (admin CLI).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hero.api.deps import SESSION_COOKIE, AuthUser, get_current_user, get_db_session
from hero.auth import issue_session_token, verify_password
from hero.config import get_settings
from hero.storage.repo import get_user_by_email

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class MeResponse(BaseModel):
    user_id: str
    org_id: str
    role: str


@router.post("/login", response_model=MeResponse)
async def login(
    request: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> MeResponse:
    """Verify email+password, set the httponly session cookie."""
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise HTTPException(status_code=503, detail="Auth not configured (JWT_SECRET_KEY unset)")

    user = await get_user_by_email(session, request.email)
    # Same 401 for unknown email and wrong password — no account enumeration.
    if user is None or not verify_password(user.password_hash, request.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = issue_session_token(
        user_id=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
        secret=settings.jwt_secret_key,
        expires_in_seconds=settings.jwt_expiry_seconds,
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.jwt_expiry_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
    )
    return MeResponse(user_id=str(user.id), org_id=str(user.org_id), role=user.role)


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "logged_out"}


@router.get("/me", response_model=MeResponse)
async def me(user: AuthUser = Depends(get_current_user)) -> MeResponse:  # noqa: B008
    return MeResponse(user_id=str(user.id), org_id=str(user.org_id), role=user.role)
