"""Add orders, payments, refunds, settlements and ledger.

Revision ID: 0003_orders_payments
Revises: 0002_identity_commerce
Create Date: 2026-09-24
"""

from typing import Sequence

from alembic import op

from iphone_market.platform.models import (
    LedgerAccount,
    LedgerEntry,
    LedgerJournal,
    MerchantSettlement,
    Order,
    OrderEvent,
    PaymentEvent,
    PaymentIntent,
    Refund,
)


revision: str = "0003_orders_payments"
down_revision: str | None = "0002_identity_commerce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_TABLES = (
    Order.__table__,
    OrderEvent.__table__,
    PaymentIntent.__table__,
    PaymentEvent.__table__,
    Refund.__table__,
    LedgerAccount.__table__,
    LedgerJournal.__table__,
    LedgerEntry.__table__,
    MerchantSettlement.__table__,
)


def upgrade() -> None:
    # Later metadata revisions can create newer tables on fresh databases.
    # checkfirst preserves compatibility with those installations.
    for table in _NEW_TABLES:
        table.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        table.drop(bind=op.get_bind(), checkfirst=True)
