"""``db stamp-baseline`` sets aside a module chain's pending work, and nothing else.

The stamp runs before the module chains do, so a column a pending module
revision adds is missing from the database for a good reason. Everything else
the schema comparison reports — a column the database lost, an index nobody
creates — is still a reason to refuse: no chain run after the stamp fixes it.
The comparison entries are built here the way ``compare_metadata`` shapes them.
"""

import pytest
from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, Table

from app.cli.commands_db import _unexplained_gaps
from app.core.migration_doctor import RevisionChanges

pytestmark = pytest.mark.unit

_metadata = MetaData()
Table('owners', _metadata, Column('id', Integer, primary_key=True))
_gadgets = Table(
    'gadgets',
    _metadata,
    Column('id', Integer, primary_key=True),
    Column('size', Integer),
    Column('owner_id', Integer, ForeignKey('owners.id')),
    Column('notes', Integer),
)

_PENDING = RevisionChanges(
    added=frozenset({('gadgets', 'size')}),
    dropped=frozenset({('gadgets', 'colour')}),
    altered=frozenset({('gadgets', 'owner_id')}),
    names=frozenset({'ix_gadgets_by_notes'}),
)


def _add_column(name: str):
    return ('add_column', None, 'gadgets', _gadgets.c[name])


def _remove_column(name: str):
    return ('remove_column', None, 'gadgets', Column(name, Integer))


def _modify_nullable(name: str):
    return [('modify_nullable', None, 'gadgets', name, {}, True, False)]


def _fk_on(name: str):
    return next(fk for fk in _gadgets.foreign_key_constraints if name in fk.column_keys)


@pytest.mark.parametrize(
    'gap',
    [
        _add_column('size'),
        _remove_column('colour'),
        _modify_nullable('owner_id'),
        ('add_index', Index('ix_gadgets_size', _gadgets.c.size)),
        ('add_index', Index('ix_gadgets_by_notes', _gadgets.c.notes)),
        ('add_fk', _fk_on('owner_id')),
    ],
    ids=[
        'added column',
        'dropped column',
        'altered column',
        'its index',
        'named index',
        'its key',
    ],
)
def test_a_pending_module_revisions_work_is_set_aside(gap):
    assert _unexplained_gaps([gap], _PENDING) == []


@pytest.mark.parametrize(
    'gap',
    [
        _add_column('notes'),
        # A revision that only alters a column cannot recreate a lost one.
        _add_column('owner_id'),
        _remove_column('size'),
        _modify_nullable('notes'),
        _modify_nullable('size'),
        ('add_index', Index('ix_gadgets_notes', _gadgets.c.notes)),
        (
            'add_index',
            Index('ix_gadgets_size_notes', _gadgets.c.size, _gadgets.c.notes),
        ),
        ('remove_table', _gadgets),
    ],
    ids=[
        'lost column',
        'lost altered column',
        'spare added column',
        'altered column',
        'altered added column',
        'index',
        'half-pending index',
        'table',
    ],
)
def test_anything_else_is_still_a_reason_to_refuse(gap):
    assert _unexplained_gaps([gap], _PENDING) == [gap]
