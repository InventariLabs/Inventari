"""``docs/ERD.md`` says what the models say.

The diagram is written by hand, and a hand-written diagram drifts: it drew a
profile -> type-config line the database never had, a notification belonging
to an organization when it belongs to a user, and left out the movement
journal. This test reads the document the way a reader does — the mermaid
block, the entity table, the list of tables left out — and holds it against
the SQLAlchemy metadata:

* every drawn entity names a table that exists, and the entity table lists
  exactly the entities that are drawn;
* every drawn relationship has a foreign key between the two tables, except a
  dotted line (``..``), which is the document's mark for a soft reference —
  and a dotted line must not hide a real foreign key either;
* a relationship drawn "many" on one end is not backed by a foreign key that
  is unique on its own: a foreign key alone does not make a table "many";
* the parent end of a line says whether the child may go without a parent:
  "exactly one" (``||``) needs a foreign key whose columns are all NOT NULL,
  and "zero or one" (``|o`` / ``o|``) needs one that can be NULL;
* every table inside the scope the document states (core models, warehouse,
  purchase orders, stock takes, approvals) is either drawn or named in the
  table of deliberate omissions, with a file that describes it.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_ERD = _REPO_ROOT / 'docs' / 'ERD.md'

#: Where a table's model lives decides whether the document owes it a box:
#: the core models and the four modules whose tables the scope line names.
_SCOPE_PREFIXES = (
    'app.models.',
    'app.core.template_models',
    'app.modules.warehouse.',
    'app.modules.purchase_orders.',
    'app.modules.stock_takes.',
    'app.modules.approvals.',
)

_RELATION = re.compile(
    r'^\s*(?P<left>[A-Z][A-Z0-9_]*)\s+(?P<lend>\S*?)(?P<line>--|\.\.)(?P<rend>\S*)\s+'
    r'(?P<right>[A-Z][A-Z0-9_]*)\s*:'
)
_BOX = re.compile(r'^\s*(?P<name>[A-Z][A-Z0-9_]*)\s*\{?\s*$')
_ENTITY_ROW = re.compile(
    r'^\|\s*\*\*(?P<name>[A-Z][A-Z0-9_]*)\*\*\s*\|\s*`(?P<table>\w+)`\s*\|'
)
_OMITTED_ROW = re.compile(r'^\|\s*`(?P<table>\w+)`\s*\|(?P<where>.*)\|\s*$')
_OMITTED_HEADING = '## Tables deliberately not drawn'


def _metadata():
    import app.modules as modules_pkg
    from app.database import Base

    # Importing registers the tables on ``Base.metadata``; nothing is used.
    importlib.import_module('app.core.template_models')
    importlib.import_module('app.models')
    root = Path(modules_pkg.__file__).parent
    for module_dir in sorted(root.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith('_'):
            continue
        name = f'app.modules.{module_dir.name}.models'
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
    return Base


def _model_facts() -> tuple[
    set[str], set[str], set[frozenset[str]], set[tuple], dict[tuple, list[bool]]
]:
    """Return the facts the diagram is held to.

    ``(all tables, tables in scope, linked pairs, unique foreign keys,
    NOT NULL flags of the foreign keys per (child, parent) pair)``.

    A table counts as outside the scope only when a mapped class says so; one
    with no mapper (a bare ``Table`` on the metadata) has no module to speak
    for it and is held to the document like the rest.
    """
    base = _metadata()
    tables = set(base.metadata.tables)
    owner: dict[str, set[str]] = {}
    for mapper in base.registry.mappers:
        owner.setdefault(mapper.local_table.name, set()).add(mapper.class_.__module__)
    in_scope = {
        table
        for table in tables
        if table not in owner
        or any(m.startswith(_SCOPE_PREFIXES) for m in owner[table])
    }
    links = {
        frozenset({table.name, fk.column.table.name})
        for table in base.metadata.tables.values()
        for fk in table.foreign_keys
    }
    # (child table, parent table) pairs whose every foreign key is, on its
    # own, unique in the child: that side can hold at most one row per parent.
    keys: dict[tuple[str, str], list[bool]] = {}
    for table in base.metadata.tables.values():
        single_unique = {
            next(iter(c.columns)).name
            for c in [*table.constraints, *table.indexes]
            if getattr(c, 'unique', True)
            and len(c.columns) == 1
            # a partial unique index limits some rows, not the table
            and getattr(c, 'dialect_options', {}).get('postgresql', {}).get('where')
            is None
            and type(c).__name__
            in {'UniqueConstraint', 'Index', 'PrimaryKeyConstraint'}
        }
        for fk in table.foreign_keys:
            alone = fk.parent.name in single_unique or bool(fk.parent.unique)
            keys.setdefault((table.name, fk.column.table.name), []).append(alone)
    one_row_per_parent = {pair for pair, flags in keys.items() if all(flags)}
    # Per (child, parent) pair, one flag per foreign key: True when the child
    # cannot leave it empty, i.e. every column of it is NOT NULL. A composite
    # key with one nullable column is not enforced (MATCH SIMPLE).
    mandatory: dict[tuple[str, str], list[bool]] = {}
    for table in base.metadata.tables.values():
        for fkc in table.foreign_key_constraints:
            mandatory.setdefault((table.name, fkc.referred_table.name), []).append(
                all(not column.nullable for column in fkc.columns)
            )
    return tables, in_scope, links, one_row_per_parent, mandatory


def _parse(text: str) -> dict:
    block = re.search(r'```mermaid\n(.*?)```', text, re.S)
    assert block, 'ERD.md has no mermaid block'
    drawn: set[str] = set()
    relations: list[tuple[str, str, str, str, str]] = []
    for line in block.group(1).splitlines():
        if line.strip().startswith('%%') or line.strip() == 'erDiagram':
            continue
        relation = _RELATION.match(line)
        if relation:
            drawn |= {relation['left'], relation['right']}
            relations.append(
                (
                    relation['left'],
                    relation['right'],
                    relation['line'],
                    relation['lend'],
                    relation['rend'],
                )
            )
            continue
        box = _BOX.match(line)
        if box:
            drawn.add(box['name'])

    entities = {}
    for line in text.splitlines():
        row = _ENTITY_ROW.match(line)
        if row:
            entities[row['name']] = row['table']

    omitted: dict[str, str] = {}
    if _OMITTED_HEADING in text:
        section = text.split(_OMITTED_HEADING, 1)[1]
        for line in section.splitlines():
            row = _OMITTED_ROW.match(line)
            if row:
                omitted[row['table']] = row['where']
    return {
        'drawn': drawn,
        'relations': relations,
        'entities': entities,
        'omitted': omitted,
    }


def _relation_problems(
    relation: tuple[str, str, str, str, str],
    table_of: dict[str, str],
    links: set[frozenset[str]],
    one_row_per_parent: set[tuple],
    mandatory: dict[tuple, list[bool]],
) -> list[str]:
    """What is wrong with one drawn line, given the foreign keys that exist."""
    left, right, line, lend, rend = relation
    a, b = table_of.get(left), table_of.get(right)
    if a is None or b is None:
        return []  # reported by the caller
    found: list[str] = []
    linked = frozenset({a, b}) in links
    if line == '--' and not linked:
        found.append(
            f'{left} -- {right}: no foreign key between {a} and {b}; '
            f'draw it dotted (..) if it is a soft reference'
        )
    if line == '..' and linked:
        found.append(
            f'{left} .. {right}: marked soft, but {a} and {b} do have '
            f'a foreign key; draw it solid'
        )
    # "Many" is drawn with a brace on the far end of the line: the table on
    # that end is the one holding the foreign key.
    for many, parent, mark in ((b, a, rend), (a, b, lend)):
        if ('{' in mark or '}' in mark) and (many, parent) in one_row_per_parent:
            found.append(
                f'{left} {line} {right}: drawn as many, but {many} has at '
                f'most one row per {parent} (its foreign key is unique)'
            )
    # The parent end says whether the child may go without a parent. "Exactly
    # one" (``||``) is true only of a foreign key whose columns are all NOT
    # NULL; "zero or one" (``|o`` / ``o|``) only of one that can be NULL. Where
    # two tables are joined by several keys, any one of them can back the line.
    # A dotted line has no key to read, and next to a one-to-one ``o|`` the
    # mark could just as well count children, so the far end must be many.
    if line == '--':
        for parent, child, mark, far in (
            (left, right, lend, rend),
            (right, left, rend, lend),
        ):
            flags = mandatory.get((table_of[child], table_of[parent]), [])
            if not flags:
                continue
            if mark == '||' and not any(flags):
                found.append(
                    f'{left} {line} {right}: a {child} may have no {parent} '
                    f'(its foreign key is nullable), so that end is optional '
                    f'(|o or o|), not exactly one'
                )
            if mark in ('|o', 'o|') and ('{' in far or '}' in far) and all(flags):
                found.append(
                    f'{left} {line} {right}: a {child} cannot be without a '
                    f'{parent} (its foreign key is NOT NULL), so that end is '
                    f'exactly one (||)'
                )
    return found


def problems(text: str) -> list[str]:
    """Every way ``text`` disagrees with the models; empty when it agrees."""
    tables, in_scope, links, one_row_per_parent, mandatory = _model_facts()
    doc = _parse(text)
    found: list[str] = []

    for entity in sorted(doc['drawn'] - set(doc['entities'])):
        found.append(f'{entity} is drawn but has no row in the entity table')
    for entity in sorted(set(doc['entities']) - doc['drawn']):
        found.append(f'{entity} is in the entity table but is not drawn')
    for entity, table in sorted(doc['entities'].items()):
        if table not in tables:
            found.append(f'{entity} names the table {table!r}, which does not exist')

    table_of = doc['entities']
    for relation in doc['relations']:
        found.extend(
            _relation_problems(relation, table_of, links, one_row_per_parent, mandatory)
        )

    drawn_tables = {table_of[e] for e in doc['drawn'] if e in table_of}
    for table, where in sorted(doc['omitted'].items()):
        if table not in tables:
            found.append(f'{table!r} is listed as left out but does not exist')
        if table in drawn_tables:
            found.append(f'{table!r} is both drawn and listed as left out')
        paths = re.findall(r'`([\w./-]+/[\w./-]+)`', where)
        if not any((_REPO_ROOT / p).exists() for p in paths):
            found.append(f'{table!r} is left out without a file that describes it')
    for table in sorted(in_scope - drawn_tables - set(doc['omitted'])):
        found.append(f'{table!r} is in scope but neither drawn nor listed as left out')
    return found


def test_the_erd_agrees_with_the_models() -> None:
    assert problems(_ERD.read_text(encoding='utf-8')) == []


class TestTheCheckHasTeeth:
    """The test is only worth having if each kind of drift turns it red."""

    @staticmethod
    def _mutated(old: str, new: str) -> list[str]:
        text = _ERD.read_text(encoding='utf-8')
        assert old in text, f'{old!r} is not in ERD.md any more; update this test'
        return problems(text.replace(old, new, 1))

    @pytest.mark.parametrize(
        'line, pair',
        [
            (
                'DOCUMENT_PROFILE ||--o{ DOCUMENT_TYPE_CONFIG : configures',
                'DOCUMENT_PROFILE -- DOCUMENT_TYPE_CONFIG',
            ),
            (
                'ORGANIZATION ||--o{ NOTIFICATION : receives',
                'ORGANIZATION -- NOTIFICATION',
            ),
        ],
    )
    def test_a_line_the_database_never_had_is_refused(
        self, line: str, pair: str
    ) -> None:
        found = self._mutated(
            '    ORGANIZATION |o--o{ USER : contains',
            f'    {line}\n    ORGANIZATION |o--o{{ USER : contains',
        )
        assert any(pair in p for p in found), found

    def test_a_deleted_box_is_refused(self) -> None:
        text = _ERD.read_text(encoding='utf-8')
        kept = '\n'.join(
            line
            for line in text.splitlines()
            if not re.search(r'\bSTOCK_MOVE\b', line.split(':')[0])
            or line.startswith('|')
        )
        found = problems(kept)
        assert any("'stock_moves' is in scope but neither drawn" in p for p in found)

    def test_a_solid_line_over_a_soft_reference_is_refused(self) -> None:
        found = self._mutated(
            'PURCHASE_ORDER_LINE |o..o{ DOCUMENT_LINE',
            'PURCHASE_ORDER_LINE |o--o{ DOCUMENT_LINE',
        )
        assert any('PURCHASE_ORDER_LINE -- DOCUMENT_LINE' in p for p in found), found

    def test_a_dotted_line_over_a_real_key_is_refused(self) -> None:
        found = self._mutated(
            'ORGANIZATION |o--o{ USER : contains',
            'ORGANIZATION |o..o{ USER : contains',
        )
        assert any('ORGANIZATION .. USER' in p for p in found), found

    def test_an_entity_without_a_table_is_refused(self) -> None:
        found = self._mutated('| `stock_moves` |', '| `stock_movements` |')
        assert any('stock_movements' in p for p in found), found

    def test_an_entity_row_missing_is_refused(self) -> None:
        text = _ERD.read_text(encoding='utf-8')
        kept = '\n'.join(
            line
            for line in text.splitlines()
            if not line.startswith('| **STOCK_MOVE**')
        )
        found = problems(kept)
        assert any('STOCK_MOVE is drawn but has no row' in p for p in found), found

    def test_an_omission_without_a_description_is_refused(self) -> None:
        text = _ERD.read_text(encoding='utf-8')
        row = next(
            line for line in text.splitlines() if line.startswith('| `event_outbox` |')
        )
        found = problems(text.replace(row, '| `event_outbox` | nowhere |'))
        assert any('event_outbox' in p and 'describes' in p for p in found), found

    @pytest.mark.parametrize(
        'old, new, pair',
        [
            (
                'DOCUMENT ||--o| DOCUMENT_SHIPMENT',
                'DOCUMENT ||--o{ DOCUMENT_SHIPMENT',
                'DOCUMENT -- DOCUMENT_SHIPMENT',
            ),
            (
                'ORGANIZATION ||--o| DOCUMENT_PROFILE',
                'ORGANIZATION ||--o{ DOCUMENT_PROFILE',
                'ORGANIZATION -- DOCUMENT_PROFILE',
            ),
        ],
    )
    def test_many_over_a_unique_key_is_refused(
        self, old: str, new: str, pair: str
    ) -> None:
        found = self._mutated(old, new)
        assert any(pair in p and 'drawn as many' in p for p in found), found

    @pytest.mark.parametrize(
        'old, new',
        [
            # The five lines a review found drawn "exactly one" over a key
            # that can be NULL, and one more of each kind.
            (
                'ORGANIZATION |o--o{ STORAGE_TYPE',
                'ORGANIZATION ||--o{ STORAGE_TYPE',
            ),
            (
                'STORAGE_LOCATION |o--o{ LOCATION_RELOCATION',
                'STORAGE_LOCATION ||--o{ LOCATION_RELOCATION',
            ),
            ('STOCK_ANCHOR |o--o{ ITEM', 'STOCK_ANCHOR ||--o{ ITEM'),
            (
                'STORAGE_LOCATION |o--o{ STOCK_TAKE_CLOSED_LOCATION',
                'STORAGE_LOCATION ||--o{ STOCK_TAKE_CLOSED_LOCATION',
            ),
            ('USER |o--o{ APPROVAL_DECISION', 'USER ||--o{ APPROVAL_DECISION'),
            (
                'STORAGE_LOCATION |o--o{ STORAGE_LOCATION',
                'STORAGE_LOCATION ||--o{ STORAGE_LOCATION',
            ),
            # The parent on the right-hand end is read the same way.
            ('ITEM }o--o| STOCK_LOT', 'ITEM }o--|| STOCK_LOT'),
        ],
    )
    def test_exactly_one_over_a_nullable_key_is_refused(
        self, old: str, new: str
    ) -> None:
        left, _, right = new.split()
        found = self._mutated(old, new)
        assert any(
            p.startswith(f'{left} -- {right}: ') and 'foreign key is nullable' in p
            for p in found
        ), found

    @pytest.mark.parametrize(
        'old, new',
        [
            ('DOCUMENT ||--o{ WMS_PICK_SESSION', 'DOCUMENT |o--o{ WMS_PICK_SESSION'),
            (
                'DOCUMENT_LINE ||--o{ WMS_PICK_LINE',
                'DOCUMENT_LINE |o--o{ WMS_PICK_LINE',
            ),
            (
                'APPROVAL_WORKFLOW ||--o{ APPROVAL_REQUEST',
                'APPROVAL_WORKFLOW |o--o{ APPROVAL_REQUEST',
            ),
            # The parent on the right-hand end is read the same way.
            ('DOCUMENT ||--o{ DOCUMENT_LINE', 'DOCUMENT_LINE }o--o| DOCUMENT'),
        ],
    )
    def test_optional_over_a_not_null_key_is_refused(self, old: str, new: str) -> None:
        left, _, right = new.split()
        found = self._mutated(old, new)
        assert any(
            p.startswith(f'{left} -- {right}: ') and 'foreign key is NOT NULL' in p
            for p in found
        ), found

    def test_a_table_with_no_mapper_is_still_owed_a_box(self) -> None:
        from sqlalchemy import Column, Table, Uuid

        base = _metadata()
        table = Table(
            'review_unmapped_core_table',
            base.metadata,
            Column('id', Uuid, primary_key=True),
        )
        try:
            found = problems(_ERD.read_text(encoding='utf-8'))
        finally:
            base.metadata.remove(table)
        assert any('review_unmapped_core_table' in p for p in found), found
