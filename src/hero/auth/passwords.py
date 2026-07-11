"""argon2id password hashing (P4-1).

argon2-cffi defaults to Argon2id with RFC-9106-derived parameters
(time_cost=3, memory_cost=64 MiB, parallelism=4) — no tuning knobs
exposed until profiling says otherwise.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password with argon2id."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time verify. Returns False on any mismatch or malformed hash."""
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False
    except Exception:
        # Malformed/legacy hash — treat as auth failure, never raise to caller.
        return False
