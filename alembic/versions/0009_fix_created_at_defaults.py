"""fix created_at defaults frozen by string 'now()' (H4 / BL-20)

Revision ID: 0009
Revises: 0008

Migrations 0004/0005/0006/0008 passed the server_default as a plain string
rather than sa.text(). Postgres constant-folds a string-literal DEFAULT
(``'now()'``, quoted) to the timestamp at DDL
parse time, so every row in app_user, ticket_event, building,
conversation_message and rate_limit_event got created_at frozen at
migration-run time. That produced the rehearsal's "event 14:58 vs ticket
22:12" ledger incoherence, and made the rate-limit sliding window meaningless
(all events share one timestamp). This migration replaces the folded constant
with the real ``now()`` function. Rows written under the frozen default carry
unrecoverable timestamps and are left as-is.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None

AFFECTED_TABLES = (
    "app_user",
    "ticket_event",
    "building",
    "conversation_message",
    "rate_limit_event",
)


def upgrade() -> None:
    for table in AFFECTED_TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now()")


def downgrade() -> None:
    # The function default is correct for every prior revision too — never
    # reinstate the folded-constant bug.
    pass
