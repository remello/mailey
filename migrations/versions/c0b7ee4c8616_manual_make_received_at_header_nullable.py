"""manual_make_received_at_header_nullable

Revision ID: c0b7ee4c8616
Revises: 24439b3156c7
Create Date: 2024-04-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # Import for TIMESTAMP type

# revision identifiers, used by Alembic.
revision: str = 'c0b7ee4c8616'
down_revision: Union[str, None] = '24439b3156c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('emails', 'received_at_header',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True)


def downgrade() -> None:
    op.alter_column('emails', 'received_at_header',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False)
