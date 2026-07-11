"""JWT session tokens — HS256, stateless (P4-1).

Claims: sub (user id), org (org id), role, iat, exp. The org and role
claims are what the API layer scopes queries with — they are signed, so
a tampered cookie fails verification rather than escalating privileges.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

_ALGORITHM = "HS256"


class TokenError(Exception):
    """Invalid, expired, or tampered session token."""


@dataclass(frozen=True)
class SessionClaims:
    user_id: str
    org_id: str
    role: str


def issue_session_token(
    *,
    user_id: str,
    org_id: str,
    role: str,
    secret: str,
    expires_in_seconds: int,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "org": org_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in_seconds),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_session_token(token: str, *, secret: str) -> SessionClaims:
    """Decode + verify. Raises TokenError on anything invalid."""
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.InvalidTokenError as exc:  # covers expiry, bad signature, malformed
        raise TokenError(str(exc)) from exc
    try:
        return SessionClaims(
            user_id=str(payload["sub"]),
            org_id=str(payload["org"]),
            role=str(payload["role"]),
        )
    except KeyError as exc:
        raise TokenError(f"missing claim: {exc}") from exc
