"""Exporter countries and units as lists an admin can change.

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-26

- etls.countries and etls.units: a name, whether it's offered (active), and
  its place in the list. The form's "Country" and "Unit" must be an active
  entry (checked on save and again on Submit).
- The app may add entries and change them, never delete them: an entry that
  is no longer wanted is switched off, so applications that used it still
  make sense.
- The facility letter keeps the name as text, as before: a renamed entry
  doesn't change what an earlier applicant wrote.
"""
import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"

# ECOWAS members at the time of writing. [CONFIRM] How goods from Burkina Faso,
# Mali and Niger (which left ECOWAS in 2025) are treated: not on the list for now.
COUNTRIES = [
    "Benin",
    "Cabo Verde",
    "Côte d’Ivoire",
    "Ghana",
    "Guinea",
    "Guinea-Bissau",
    "Liberia",
    "Nigeria",
    "Senegal",
    "Sierra Leone",
    "Togo",
]
# [CONFIRM] The units GRA expects on a facility letter.
UNITS = ["bags", "cartons", "tonnes", "kg", "litres", "pieces"]


def _create(name: str, values: list[str]) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.SmallInteger, sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.SmallInteger, nullable=False),
        sa.CheckConstraint("btrim(name) <> '' AND name = btrim(name)", name=f"{name}_name_trimmed"),
        schema="etls",
    )
    # "Ghana" and "ghana" are the same entry.
    op.execute(f"CREATE UNIQUE INDEX {name}_name_key ON etls.{name} (lower(name))")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON etls.{name} TO {APP_ROLE}")
    table = sa.table(name, sa.column("name"), sa.column("sort_order"), schema="etls")
    op.bulk_insert(table, [{"name": v, "sort_order": i + 1} for i, v in enumerate(values)])


def upgrade() -> None:
    _create("countries", COUNTRIES)
    _create("units", UNITS)


def downgrade() -> None:
    op.drop_table("units", schema="etls")
    op.drop_table("countries", schema="etls")
