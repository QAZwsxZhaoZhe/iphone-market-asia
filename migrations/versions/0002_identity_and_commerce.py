"""Add identity, merchants, inventory and seller listings.

Revision ID: 0002_identity_commerce
Revises: 0001_initial_platform
Create Date: 2026-09-24
"""

from typing import Sequence

from alembic import op

from iphone_market.platform.models import (
    AuthSession,
    InventoryItem,
    Merchant,
    SellerListing,
    User,
    UserRole,
)


revision: str = "0002_identity_commerce"
down_revision: str | None = "0001_initial_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_TABLES = (
    User.__table__,
    UserRole.__table__,
    AuthSession.__table__,
    Merchant.__table__,
    InventoryItem.__table__,
    SellerListing.__table__,
)


def upgrade() -> None:
    # Revision 0001 is intentionally dynamic and may already create current
    # metadata on a fresh database. checkfirst keeps this migration idempotent.
    for table in _NEW_TABLES:
        table.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        table.drop(bind=op.get_bind(), checkfirst=True)
