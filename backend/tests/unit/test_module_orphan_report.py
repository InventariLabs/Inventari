"""Naming the tables of a module that may not import the Core Base.

The report exists to say what an uninstall leaves behind, and the first
line of it is the module's own tables. Reading them off the module's
files is the only source available — nothing records, per table, which
module created it.

The architecture lint already walks module files for ``__tablename__``,
and reusing that walk reported *zero* tables for every community module.
It skips models built on a ``DeclarativeBase`` of their own, on the
grounds that core Alembic does not track them — and a community module
cannot use any other kind, because the AST validator forbids it from
importing ``app.database`` at all.
"""

from __future__ import annotations

from app.cli._module_orphans import _tablenames_in

_OWN_BASE = """\
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Claim(Base):
    __tablename__ = 'warranty_claims'

    id: Mapped[int] = mapped_column(primary_key=True)
"""

_CORE_BASE = """\
from app.database import Base


class Thing(Base):
    __tablename__ = 'core_things'
"""

_MIGRATION = """\
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table('warranty_claims', sa.Column('id', sa.Integer()))
    op.create_table('warranty_claim_notes', sa.Column('id', sa.Integer()))
"""

_HELPER_MIGRATION = """\
from alembic import op
import sqlalchemy as sa
from app.core.migration_helpers import create_table_if_absent


def upgrade() -> None:
    op.create_table('warranty_claims', sa.Column('id', sa.Integer()))
    create_table_if_absent(
        'warranty_claim_extra',
        sa.Column('id', sa.Integer(), primary_key=True),
    )
    op.create_table_if_absent('warranty_claim_alias', sa.Column('id', sa.Integer()))
"""

_RAW_SQL_MIGRATION = """\
from alembic import op


def upgrade() -> None:
    op.execute("CREATE TABLE warranty_claim_logs (id integer primary key)")
    op.execute(
        "CREATE TABLE IF NOT EXISTS warranty_claim_archives (id integer primary key)"
    )
    op.execute("DROP TABLE warranty_claim_temp")
"""


class TestTablesAreFoundWhereverTheyAreDeclared:
    def test_a_model_on_its_own_declarative_base_counts(self):
        assert _tablenames_in(_OWN_BASE) == {'warranty_claims'}

    def test_a_model_on_the_core_base_counts_too(self):
        assert _tablenames_in(_CORE_BASE) == {'core_things'}

    def test_a_migration_names_tables_no_model_maps(self):
        # A join table or an audit trail can exist without a model; the
        # uninstall keeps it either way, so the report has to see it.
        assert _tablenames_in(_MIGRATION) == {
            'warranty_claims',
            'warranty_claim_notes',
        }

    def test_a_table_created_through_the_if_absent_helper_counts(self):
        """The migrations of this repository create tables through
        ``create_table_if_absent``, not only ``op.create_table`` — a
        walker that reads only the second named part of the schema and
        the uninstall summary then claimed a drop the database never
        made, with the helper's table still sitting in it."""
        assert _tablenames_in(_HELPER_MIGRATION) == {
            'warranty_claims',
            'warranty_claim_extra',
            'warranty_claim_alias',
        }

    def test_a_table_created_by_raw_sql_in_execute_counts(self):
        """``op.execute('CREATE TABLE …')`` makes a table just as really
        as a helper call; the string is the only place the name appears.
        A DROP in the same string form names nothing."""
        assert _tablenames_in(_RAW_SQL_MIGRATION) == {
            'warranty_claim_logs',
            'warranty_claim_archives',
        }

    def test_a_file_with_no_tables_says_so(self):
        assert _tablenames_in('x = 1\n') == set()
