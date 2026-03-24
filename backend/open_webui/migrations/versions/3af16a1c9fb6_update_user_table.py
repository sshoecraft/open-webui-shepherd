"""update user table

Revision ID: 3af16a1c9fb6
Revises: 018012973d35
Create Date: 2025-08-21 02:07:18.078283

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3af16a1c9fb6"
down_revision: Union[str, None] = "018012973d35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table, column):
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        result = conn.execute(sa.text(
            "SELECT 1 FROM pragma_table_info(:table) WHERE name = :column"
        ), {"table": table, "column": column})
    else:
        result = conn.execute(sa.text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"
        ), {"table": table, "column": column})
    return result.fetchone() is not None


def upgrade() -> None:
    for col_name, col_type in [
        ("username", sa.String(length=50)),
        ("bio", sa.Text()),
        ("gender", sa.Text()),
        ("date_of_birth", sa.Date()),
    ]:
        if not column_exists("user", col_name):
            op.add_column("user", sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    op.drop_column("user", "username")
    op.drop_column("user", "bio")
    op.drop_column("user", "gender")
    op.drop_column("user", "date_of_birth")
