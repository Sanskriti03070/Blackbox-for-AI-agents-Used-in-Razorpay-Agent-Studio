"""Initial foundation migration with no domain tables.

Revision ID: 20260822_0001
Revises:
Create Date: 2026-08-22 00:00:00
"""

from collections.abc import Sequence

revision: str = "20260822_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
