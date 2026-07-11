"""Auth — argon2id password hashing + JWT session tokens (P4-1).

No self-signup: users are seeded via `python -m hero.auth seed`.
Sessions are stateless HS256 JWTs in an httponly cookie; revocation =
rotate JWT_SECRET_KEY (acceptable for the design-partner pilot).
"""

from hero.auth.passwords import hash_password, verify_password
from hero.auth.tokens import SessionClaims, decode_session_token, issue_session_token

__all__ = [
    "SessionClaims",
    "decode_session_token",
    "hash_password",
    "issue_session_token",
    "verify_password",
]
