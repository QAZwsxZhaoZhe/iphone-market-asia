"""Create the initial aggregation platform schema.

Revision ID: 0001_initial_platform
Revises:
Create Date: 2026-09-24
"""

from typing import Sequence

from alembic import op

from iphone_market.platform.models import Base


revision: str = "0001_initial_platform"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
