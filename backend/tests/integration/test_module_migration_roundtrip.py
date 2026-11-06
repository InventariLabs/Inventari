"""Parametrized round-trip test for all module migrations.

For each module with ``migrations/versions/``, verifies:
1. ``upgrade head`` creates the module's tables
2. ``downgrade base`` removes them
3. The version table is separate from core ``alembic_version`` (checked in
   the same item as 1: both need the same freshly migrated schema)
4. Running ``upgrade head`` twice is idempotent (no error)
5. Migrated table columns match the SQLAlchemy model definitions — their
   names, and for a numeric column its width too: a name check saw
   ``system_quantity`` match while carrying a third of the digits the model
   copied from ``items.quantity``
6. So do its indexes, unique constraints and foreign keys — a dropped index
   used to pass unnoticed, which is how the trigram indexes went missing
7. ``001_initial`` re-runs cleanly against a schema that already exists, the
   reconciliation case that crash-looped the backend

This is the CI-level guard that auto-discovers new modules. No manual
list to maintain — any module with ``migrations/versions/*.py`` (excluding
``__init__.py``) is included automatically.
"""

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Numeric, UniqueConstraint, create_engine, inspect, text

from app.core.architecture_lint._quality_checks import _collect_module_tablenames
from app.core.db_isolation import isolated_db_url as _isolated_db_url
from app.core.module_migrations import (
    get_version_table_name,
    run_module_migrations,
)

MODULES_ROOT = Path(__file__).resolve().parents[2] / 'app' / 'modules'


def _discover_modules_with_migrations() -> list[tuple[str, set[str]]]:
    """Return ``[(module_name, {table_names})]`` for modules with versions/."""
    result: list[tuple[str, set[str]]] = []
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith('_'):
            continue
        versions_dir = module_dir / 'migrations' / 'versions'
        if not versions_dir.is_dir():
            continue
        version_files = [
            f for f in versions_dir.glob('*.py') if f.name != '__init__.py'
        ]
        if not version_files:
            continue
        tables = _collect_module_tablenames(module_dir)
        if tables:
            result.append((module_dir.name, tables))
    return result


MODULES = _discover_modules_with_migrations()


def _module_id(module_name: str, tables: set[str]) -> str:
    return module_name


@pytest.fixture(scope='class')
def isolated_db_url(request):
    """An empty database for one module's round-trip test."""
    with _isolated_db_url('rt') as url:
        yield url


def _create_core_tables(db_url: str, module_name: str, module_tables: set[str]) -> None:
    """Create all Base.metadata tables, then drop module-owned ones via CASCADE.

    This avoids mutating the global ``Base.metadata`` (thread-safe under
    parallel execution). Cross-module FKs (e.g. items.source_document_id →
    documents.id) are handled by CASCADE, which removes the FK constraint
    from the core table when the module table is dropped.

    Also drops the module's alembic version table so each test starts fresh.
    """
    import app.core.template_models
    import app.models  # noqa: F401
    from app.database import Base

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    version_table = get_version_table_name(module_name)
    with engine.connect() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{version_table}" CASCADE'))
        for table_name in sorted(module_tables):
            conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
        conn.commit()
    engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize(
    'module_name,expected_tables',
    MODULES,
    ids=[m[0] for m in MODULES],
)
class TestModuleMigrationRoundTrip:
    """Round-trip: upgrade creates tables, downgrade removes them."""

    def test_upgrade_creates_tables(
        self, module_name, expected_tables, isolated_db_url
    ):
        """Module upgrade@head creates its tables and a version table of its own."""
        _create_core_tables(isolated_db_url, module_name, expected_tables)
        run_module_migrations(module_name, 'upgrade', db_url=isolated_db_url)

        engine = create_engine(isolated_db_url)
        insp = inspect(engine)
        actual_tables = set(insp.get_table_names())
        engine.dispose()

        for table in expected_tables:
            assert table in actual_tables, (
                f'Module {module_name}: table "{table}" missing after upgrade'
            )
        # The version table is the module's own, never core ``alembic_version``.
        assert get_version_table_name(module_name) in actual_tables
        assert 'alembic_version' not in actual_tables

    def test_downgrade_removes_tables(
        self, module_name, expected_tables, isolated_db_url
    ):
        """Module downgrade@base removes all module tables."""
        _create_core_tables(isolated_db_url, module_name, expected_tables)
        run_module_migrations(module_name, 'upgrade', db_url=isolated_db_url)
        run_module_migrations(
            module_name, 'downgrade', db_url=isolated_db_url, revision='base'
        )

        engine = create_engine(isolated_db_url)
        insp = inspect(engine)
        actual_tables = set(insp.get_table_names())
        engine.dispose()

        for table in expected_tables:
            assert table not in actual_tables, (
                f'Module {module_name}: table "{table}" still exists after downgrade'
            )

    def test_idempotent_upgrade(self, module_name, expected_tables, isolated_db_url):
        """Running upgrade@head twice does not fail."""
        _create_core_tables(isolated_db_url, module_name, expected_tables)
        run_module_migrations(module_name, 'upgrade', db_url=isolated_db_url)
        # Second upgrade should be a no-op, not raise.
        run_module_migrations(module_name, 'upgrade', db_url=isolated_db_url)

        engine = create_engine(isolated_db_url)
        insp = inspect(engine)
        actual_tables = set(insp.get_table_names())
        engine.dispose()

        for table in expected_tables:
            assert table in actual_tables, (
                f'Module {module_name}: table "{table}" '
                'missing after idempotent upgrade'
            )

    def test_schema_matches_model(self, module_name, expected_tables, isolated_db_url):
        """Migrated table columns match SQLAlchemy model definitions."""
        import importlib

        # Ensure module models are registered in Base.metadata.
        try:
            importlib.import_module(f'app.modules.{module_name}.models')
        except ModuleNotFoundError:
            pass

        from app.database import Base

        _create_core_tables(isolated_db_url, module_name, expected_tables)
        run_module_migrations(module_name, 'upgrade', db_url=isolated_db_url)

        engine = create_engine(isolated_db_url)
        insp = inspect(engine)

        mismatches: list[str] = []
        for table_name in sorted(expected_tables):
            if table_name not in Base.metadata.tables:
                mismatches.append(
                    f'  {table_name}: not found in Base.metadata (model not imported?)'
                )
                continue
            db_col_defs = {col['name']: col for col in insp.get_columns(table_name)}
            db_cols = set(db_col_defs)
            model_col_defs = {
                col.name: col for col in Base.metadata.tables[table_name].columns
            }
            model_cols = set(model_col_defs)
            if db_cols != model_cols:
                missing_in_db = model_cols - db_cols
                missing_in_model = db_cols - model_cols
                parts = [f'  {table_name}:']
                if missing_in_db:
                    parts.append(f'    in model but not in DB: {sorted(missing_in_db)}')
                if missing_in_model:
                    parts.append(
                        f'    in DB but not in model: {sorted(missing_in_model)}'
                    )
                mismatches.append('\n'.join(parts))
                continue
            for col_name in sorted(model_cols):
                model_type = model_col_defs[col_name].type
                db_type = db_col_defs[col_name]['type']
                if not isinstance(model_type, Numeric):
                    continue
                if not isinstance(db_type, Numeric):
                    mismatches.append(
                        f'  {table_name}.{col_name}: model is numeric, DB has {db_type}'
                    )
                    continue
                if (model_type.precision, model_type.scale) != (
                    db_type.precision,
                    db_type.scale,
                ):
                    mismatches.append(
                        f'  {table_name}.{col_name}: model numeric'
                        f'({model_type.precision}, {model_type.scale}) but the '
                        f'migration built {db_type}'
                    )

        engine.dispose()

        assert not mismatches, (
            f'Module {module_name}: schema/model column mismatches:\n'
            + '\n'.join(mismatches)
        )

    def test_schema_matches_model_structures(
        self, module_name, expected_tables, isolated_db_url
    ):
        """Indexes, unique constraints and foreign keys — not only column names.

        The column check above cannot see a dropped index, and showed that
               is not hypothetical: seven trigram indexes fell out of the migration
               chain and CI stayed green the whole time.

               Indexes are checked model ⊆ db. A migration is allowed to add an index
               the model does not declare — ``po_partner_pricelist`` has one, and a
               pure performance index has no business in the model. The reverse, a
               model index absent from the migrated schema, is the regression.

               Unique constraints and foreign keys are compared both ways: those carry
               semantics the application relies on, and an extra one in the database is
               as much a surprise as a missing one. They are compared by columns rather
               than by name, since Alembic and SQLAlchemy generate different names for
               the same constraint.
        """
        import importlib

        try:
            importlib.import_module(f'app.modules.{module_name}.models')
        except ModuleNotFoundError:
            pass

        from app.database import Base

        _create_core_tables(isolated_db_url, module_name, expected_tables)
        run_module_migrations(module_name, 'upgrade', db_url=isolated_db_url)

        engine = create_engine(isolated_db_url)
        insp = inspect(engine)

        mismatches: list[str] = []
        for table_name in sorted(expected_tables):
            if table_name not in Base.metadata.tables:
                continue
            table = Base.metadata.tables[table_name]

            # Postgres backs every UNIQUE constraint with an index, which
            # get_indexes reports as `duplicates_constraint`. Those belong to
            # the unique-constraint comparison below, not here.
            db_indexes = {
                (idx['name'], bool(idx.get('unique')), tuple(idx['column_names']))
                for idx in insp.get_indexes(table_name)
                if not idx.get('duplicates_constraint')
            }
            model_indexes = {
                (idx.name, bool(idx.unique), tuple(col.name for col in idx.columns))
                for idx in table.indexes
            }
            if missing := model_indexes - db_indexes:
                mismatches.append(
                    f'  {table_name}: index in model but not in DB: {sorted(missing)}'
                )

            # A unique index is a rule, not a performance aid: the module test
            # databases are built with create_all, so a migration-only one is
            # enforced nowhere those tests run.
            model_index_names = {idx.name for idx in table.indexes}
            if extra_unique := sorted(
                name
                for name, unique, _cols in db_indexes
                if unique and name not in model_index_names
            ):
                mismatches.append(
                    f'  {table_name}: unique index in DB but not in model: '
                    f'{extra_unique}'
                )

            db_unique = {
                tuple(sorted(uq['column_names']))
                for uq in insp.get_unique_constraints(table_name)
            }
            model_unique = {
                tuple(sorted(col.name for col in constraint.columns))
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            }
            if db_unique != model_unique:
                mismatches.append(
                    f'  {table_name}: unique constraints differ — '
                    f'in model only: {sorted(model_unique - db_unique)}, '
                    f'in DB only: {sorted(db_unique - model_unique)}'
                )

            db_fks = {
                (
                    tuple(fk['constrained_columns']),
                    fk['referred_table'],
                    tuple(fk['referred_columns']),
                )
                for fk in insp.get_foreign_keys(table_name)
            }
            model_fks = {
                (
                    tuple(element.parent.name for element in constraint.elements),
                    constraint.referred_table.name,
                    tuple(element.column.name for element in constraint.elements),
                )
                for constraint in table.foreign_key_constraints
            }
            if db_fks != model_fks:
                mismatches.append(
                    f'  {table_name}: foreign keys differ — '
                    f'in model only: {sorted(model_fks - db_fks)}, '
                    f'in DB only: {sorted(db_fks - model_fks)}'
                )

        engine.dispose()

        assert not mismatches, (
            f'Module {module_name}: migrated schema does not match the model:\n'
            + '\n'.join(mismatches)
        )


def _create_everything(db_url: str, module_name: str) -> None:
    """Full schema from the models — core *and* the module's own tables.

    The reconciliation case: an instance that predates the module-migration
    split, where the core baseline already created these tables. Only the
    version table is removed, so the module's baseline migration runs against a
    schema that is already there.
    """
    import importlib

    import app.core.template_models
    import app.models  # noqa: F401

    try:
        importlib.import_module(f'app.modules.{module_name}.models')
    except ModuleNotFoundError:
        pass

    from app.database import Base

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(
            text(
                f'DROP TABLE IF EXISTS "{get_version_table_name(module_name)}" CASCADE'
            )
        )
        conn.commit()
    engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize(
    'module_name,expected_tables',
    MODULES,
    ids=[m[0] for m in MODULES],
)
class TestBaselineIsIdempotent:
    """``001_initial`` must fill gaps, not fail on what already exists.

    Before the guards, this is precisely what crash-looped the backend: the
    baseline ran against tables the core migration had already created and died
    on ``relation already exists`` — on every restart, forever.

    Scope is deliberately ``001_initial`` only. Later revisions carry real
    schema changes; making those skip silently would hide a failed upgrade
    instead of surfacing it, which is ``db doctor``'s job.
    """

    def test_baseline_reruns_against_an_existing_schema(
        self, module_name, expected_tables, isolated_db_url
    ):
        _create_everything(isolated_db_url, module_name)

        run_module_migrations(
            module_name, 'upgrade', db_url=isolated_db_url, revision='001_initial'
        )  # must not raise

        engine = create_engine(isolated_db_url)
        actual = set(inspect(engine).get_table_names())
        engine.dispose()

        assert expected_tables <= actual
        assert get_version_table_name(module_name) in actual

    def test_baseline_is_repeatable_from_scratch(
        self, module_name, expected_tables, isolated_db_url
    ):
        """The other direction: guards must not turn a real create into a no-op."""
        from app.core.migration_doctor import ordered_revisions, revision_ddl

        # Only what 001_initial itself creates — later revisions add more tables,
        # and this test never runs them.
        baseline_tables = revision_ddl(ordered_revisions(module_name)[0].path).tables
        assert baseline_tables, f'{module_name}: 001_initial creates no tables'

        _create_core_tables(isolated_db_url, module_name, expected_tables)

        run_module_migrations(
            module_name, 'upgrade', db_url=isolated_db_url, revision='001_initial'
        )
        run_module_migrations(
            module_name, 'stamp', db_url=isolated_db_url, revision='base'
        )
        run_module_migrations(
            module_name, 'upgrade', db_url=isolated_db_url, revision='001_initial'
        )

        engine = create_engine(isolated_db_url)
        actual = set(inspect(engine).get_table_names())
        engine.dispose()

        assert baseline_tables <= actual


MAKER_TABLES = dict(MODULES)['maker']


@pytest.mark.integration
class TestMakerMigration003Backfill:
    """End-to-end backfill of 003 + FK constraints from 005.

    Builds the pre-003 maker schema, seeds legacy ``maker_bom_lines`` rows
    (with ``qty_per_unit`` + ``unit`` strings), then upgrades to head and
    asserts the 003 backfill results and the 005 FK constraints.
    """

    def test_backfill_from_legacy_bom_lines(self, isolated_db_url):  # noqa: PLR0915 - migration roundtrip backfill test; refactor tracked separately
        """Legacy lines get recipes + resolved uom_id; 005 adds the FKs."""
        _create_core_tables(isolated_db_url, 'maker', MAKER_TABLES)
        # Pre-003 schema: maker_bom_lines has qty_per_unit/unit but none of
        # recipe_id/qty_per_batch/uom_id yet.
        run_module_migrations(
            'maker',
            'upgrade',
            db_url=isolated_db_url,
            revision='002_cancel_reason_produced_item',
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        parent_id = uuid.uuid4()
        child_kg_id = uuid.uuid4()
        child_unknown_id = uuid.uuid4()
        category_id = uuid.uuid4()
        uom_kg_id = uuid.uuid4()
        location_id = uuid.uuid4()
        order_id = uuid.uuid4()

        engine = create_engine(isolated_db_url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO organizations '
                    '(id, name, enabled_modules, settings, created_at) '
                    "VALUES (:id, :name, '[]'::json, '{}'::json, NOW())"
                ),
                {'id': org_id, 'name': 'Roundtrip Org'},
            )
            conn.execute(
                text(
                    'INSERT INTO users '
                    '(id, email, hashed_password, role, created_at, updated_at) '
                    "VALUES (:id, 'roundtrip@example.com', 'x', 'user', NOW(), NOW())"
                ),
                {'id': user_id},
            )
            conn.execute(
                text('INSERT INTO uom_categories (id, name) VALUES (:id, :name)'),
                {'id': category_id, 'name': 'Weight'},
            )
            conn.execute(
                text(
                    'INSERT INTO uoms '
                    '(id, category_id, name, symbol, factor, is_reference, '
                    ' is_system, rounding) '
                    "VALUES (:id, :category_id, 'Kilogram', 'kg', 1.0, TRUE, TRUE, 0.01)"
                ),
                {'id': uom_kg_id, 'category_id': category_id},
            )
            for template_id, name in (
                (parent_id, 'Parent'),
                (child_kg_id, 'Child KG'),
                (child_unknown_id, 'Child Unknown'),
            ):
                conn.execute(
                    text(
                        'INSERT INTO product_templates '
                        '(id, organization_id, name, created_at, updated_at) '
                        'VALUES (:id, :org_id, :name, NOW(), NOW())'
                    ),
                    {'id': template_id, 'org_id': org_id, 'name': name},
                )
            conn.execute(
                text(
                    'INSERT INTO storage_locations '
                    '(id, organization_id, name, created_at, created_by) '
                    'VALUES (:id, :org_id, :name, NOW(), :user_id)'
                ),
                {
                    'id': location_id,
                    'org_id': org_id,
                    'name': 'Production Out',
                    'user_id': user_id,
                },
            )
            conn.execute(
                text(
                    'INSERT INTO maker_bom_lines '
                    '(id, organization_id, parent_template_id, child_template_id, '
                    ' qty_per_unit, unit, created_at, updated_at) '
                    'VALUES (:id, :org_id, :parent_id, :child_id, :qty, :unit, '
                    'NOW(), NOW())'
                ),
                [
                    {
                        'id': uuid.uuid4(),
                        'org_id': org_id,
                        'parent_id': parent_id,
                        'child_id': child_kg_id,
                        'qty': 2.5,
                        'unit': 'kg',
                    },
                    {
                        'id': uuid.uuid4(),
                        'org_id': org_id,
                        'parent_id': parent_id,
                        'child_id': child_unknown_id,
                        'qty': 3,
                        'unit': 'unknown',
                    },
                ],
            )
            conn.execute(
                text(
                    'INSERT INTO maker_production_orders '
                    '(id, organization_id, output_template_id, planned_qty, '
                    ' output_storage_location_id, created_at) '
                    'VALUES (:id, :org_id, :output_id, 10, :location_id, NOW())'
                ),
                {
                    'id': order_id,
                    'org_id': org_id,
                    'output_id': parent_id,
                    'location_id': location_id,
                },
            )

        # Upgrade to head (005) — runs the 003 backfill + FK constraints.
        run_module_migrations('maker', 'upgrade', db_url=isolated_db_url)

        with engine.connect() as conn:
            recipes = (
                conn.execute(
                    text(
                        'SELECT id, output_template_id, batch_yield_qty, is_default '
                        'FROM maker_recipes ORDER BY output_template_id'
                    )
                )
                .mappings()
                .all()
            )
            lines = (
                conn.execute(
                    text(
                        'SELECT child_template_id, recipe_id, qty_per_batch, uom_id '
                        'FROM maker_bom_lines ORDER BY child_template_id'
                    )
                )
                .mappings()
                .all()
            )
            orders = (
                conn.execute(text('SELECT recipe_id FROM maker_production_orders'))
                .mappings()
                .all()
            )

            # One default recipe per legacy parent template, yield = 1.
            assert len(recipes) == 1
            recipe = recipes[0]
            assert recipe['output_template_id'] == parent_id
            assert recipe['is_default'] is True
            assert recipe['batch_yield_qty'] == Decimal('1')

            # Both lines linked to the recipe; qty_per_batch preserved.
            assert len(lines) == 2
            by_child = {row['child_template_id']: row for row in lines}
            kg_line = by_child[child_kg_id]
            unknown_line = by_child[child_unknown_id]
            assert kg_line['recipe_id'] == recipe['id']
            assert unknown_line['recipe_id'] == recipe['id']
            assert kg_line['qty_per_batch'] == Decimal('2.5')
            assert unknown_line['qty_per_batch'] == Decimal('3')

            # uom_id resolved for known symbol, NULL for unknown.
            assert kg_line['uom_id'] == uom_kg_id
            assert unknown_line['uom_id'] is None

            # Production order linked to the default recipe.
            assert len(orders) == 1
            assert orders[0]['recipe_id'] == recipe['id']

            # 005: FK constraints present with the model-generated names.
            insp = inspect(engine)
            bom_fk_names = {
                fk['name'] for fk in insp.get_foreign_keys('maker_bom_lines')
            }
            order_fk_names = {
                fk['name'] for fk in insp.get_foreign_keys('maker_production_orders')
            }
        engine.dispose()

        assert 'maker_bom_lines_recipe_id_fkey' in bom_fk_names
        assert 'maker_bom_lines_uom_id_fkey' in bom_fk_names
        assert 'maker_production_orders_recipe_id_fkey' in order_fk_names


@pytest.mark.integration
class TestMakerMigration011Backfill:
    """End-to-end backfill of 011: the orders 009 left NULL get numbered.

    009 declined to backfill — a number the row never had is not invented
    afterwards — and the reversal (2026-08-29) requires every order to carry
    one. Builds the maker schema at 010, seeds NULL-number orders across two
    organizations and two years plus one number issued at creation, upgrades
    to head, and asserts the assigned numbers.
    """

    def test_backfill_numbers_per_org_and_year(self, isolated_db_url):
        """NULL rows get PR/{year}/{seq:04d}; issued numbers are continued."""
        _create_core_tables(isolated_db_url, 'maker', MAKER_TABLES)
        run_module_migrations(
            'maker',
            'upgrade',
            db_url=isolated_db_url,
            revision='010_add_short_at_create',
        )

        org_a, org_b = uuid.uuid4(), uuid.uuid4()
        user_id = uuid.uuid4()
        template_a, template_b = uuid.uuid4(), uuid.uuid4()
        loc_a, loc_b = uuid.uuid4(), uuid.uuid4()
        issued_id = uuid.uuid4()
        a_2025_first = uuid.uuid4()
        a_2025_second = uuid.uuid4()
        a_2026 = uuid.uuid4()
        b_first = uuid.uuid4()
        b_second = uuid.uuid4()
        # Same-instant pair: the tiebreak is the raw UUID, sorted here the way
        # Postgres sorts them so the expectation does not guess.
        tie_low, tie_high = sorted((uuid.uuid4(), uuid.uuid4()))

        def _order(order_id, org, template, loc, created_at, number=None):
            return {
                'id': order_id,
                'org': org,
                'template': template,
                'loc': loc,
                'created_at': created_at,
                'number': number,
            }

        utc = UTC
        orders = [
            # org A — one number issued at creation, legacy NULLs after it.
            _order(
                issued_id,
                org_a,
                template_a,
                loc_a,
                datetime(2025, 6, 1, tzinfo=utc),
                'PR/2025/0007',
            ),
            _order(
                a_2025_first,
                org_a,
                template_a,
                loc_a,
                datetime(2025, 3, 10, tzinfo=utc),
            ),
            _order(
                a_2025_second,
                org_a,
                template_a,
                loc_a,
                datetime(2025, 5, 20, tzinfo=utc),
            ),
            _order(a_2026, org_a, template_a, loc_a, datetime(2026, 1, 15, tzinfo=utc)),
            _order(
                tie_low,
                org_a,
                template_a,
                loc_a,
                datetime(2026, 2, 1, 8, 0, tzinfo=utc),
            ),
            _order(
                tie_high,
                org_a,
                template_a,
                loc_a,
                datetime(2026, 2, 1, 8, 0, tzinfo=utc),
            ),
            # org B — nothing issued; its sequence starts from one.
            _order(b_first, org_b, template_b, loc_b, datetime(2025, 7, 4, tzinfo=utc)),
            _order(
                b_second, org_b, template_b, loc_b, datetime(2025, 8, 2, tzinfo=utc)
            ),
        ]

        engine = create_engine(isolated_db_url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO users '
                    '(id, email, hashed_password, role, created_at, updated_at) '
                    "VALUES (:id, 'backfill@example.com', 'x', 'user', NOW(), NOW())"
                ),
                {'id': user_id},
            )
            for org_id, template_id, loc_id, name in (
                (org_a, template_a, loc_a, 'Backfill Org A'),
                (org_b, template_b, loc_b, 'Backfill Org B'),
            ):
                conn.execute(
                    text(
                        'INSERT INTO organizations '
                        '(id, name, enabled_modules, settings, created_at) '
                        "VALUES (:id, :name, '[]'::json, '{}'::json, NOW())"
                    ),
                    {'id': org_id, 'name': name},
                )
                conn.execute(
                    text(
                        'INSERT INTO product_templates '
                        '(id, organization_id, name, created_at, updated_at) '
                        'VALUES (:id, :org, :name, NOW(), NOW())'
                    ),
                    {'id': template_id, 'org': org_id, 'name': f'Template {name}'},
                )
                conn.execute(
                    text(
                        'INSERT INTO storage_locations '
                        '(id, organization_id, name, created_at, created_by) '
                        'VALUES (:id, :org, :name, NOW(), :user)'
                    ),
                    {
                        'id': loc_id,
                        'org': org_id,
                        'name': f'Output {name}',
                        'user': user_id,
                    },
                )
            conn.execute(
                text(
                    'INSERT INTO maker_production_orders '
                    '(id, organization_id, output_template_id, planned_qty, '
                    ' output_storage_location_id, number, created_at) '
                    'VALUES (:id, :org, :template, 10, :loc, :number, :created_at)'
                ),
                orders,
            )

        # Head = 011: the backfill numbers every NULL.
        run_module_migrations('maker', 'upgrade', db_url=isolated_db_url)

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    'SELECT id, organization_id, number, created_at '
                    'FROM maker_production_orders ORDER BY created_at, id'
                )
            ).all()

        by_id = {row[0]: row for row in rows}
        expected = {
            issued_id: 'PR/2025/0007',
            a_2025_first: 'PR/2025/0008',
            a_2025_second: 'PR/2025/0009',
            a_2026: 'PR/2026/0001',
            tie_low: 'PR/2026/0002',
            tie_high: 'PR/2026/0003',
            b_first: 'PR/2025/0001',
            b_second: 'PR/2025/0002',
        }
        assert {row_id: by_id[row_id][2] for row_id in expected} == expected

        # Every number says the year the order was created, in UTC.
        for _row_id, _org_id, number, created_at in rows:
            assert number is not None
            assert re.fullmatch(
                rf'PR/{created_at.astimezone(UTC).year}/\d{{4}}', number
            )
        # No collision: a number is unique within its organization.
        assert len({(row[1], row[2]) for row in rows}) == len(rows)

        run_module_migrations(
            'maker',
            'downgrade',
            db_url=isolated_db_url,
            revision='010_add_short_at_create',
        )
        with engine.connect() as conn:
            after_downgrade = dict(
                conn.execute(
                    text('SELECT id, number FROM maker_production_orders')
                ).all()
            )
        run_module_migrations('maker', 'upgrade', db_url=isolated_db_url)
        with engine.connect() as conn:
            after_reupgrade = dict(
                conn.execute(
                    text('SELECT id, number FROM maker_production_orders')
                ).all()
            )
        engine.dispose()

        numbered = {row[0]: row[2] for row in rows}
        # Downgrade is a documented no-op — the numbers stay.
        assert after_downgrade == numbered
        # Re-upgrade finds nothing NULL and changes nothing.
        assert after_reupgrade == numbered


SHOPPING_LISTS_TABLES = dict(MODULES)['shopping_lists']


@pytest.mark.integration
class TestShoppingListsFreshInstall:
    """Fresh install: the full core chain runs before module migrations.

    The archived core migration ``e4f5a6b7c8d9`` pre-creates ``shopping_list_history``
    (with the same ``ix_*`` index names the module migration uses). The
    all-or-nothing stamp check in ``_upgrade_all_modules`` then fails
    (``shopping_lists``/``shopping_list_items`` are missing), so the module's
    ``001_initial`` runs from scratch and must skip the pre-created table
    instead of crashing on ``DuplicateTable``.
    """

    def test_module_upgrade_after_full_core_upgrade(self, isolated_db_url, monkeypatch):
        """Module upgrade succeeds when core already created the history table."""
        from alembic import command
        from alembic.config import Config

        monkeypatch.setenv('DATABASE_URL', isolated_db_url)
        command.upgrade(Config('alembic.ini'), 'head')

        # Fresh-install path: no stamp (tables partially present) → module
        # migrations run from scratch. Must not raise DuplicateTable.
        run_module_migrations('shopping_lists', 'upgrade', db_url=isolated_db_url)

        engine = create_engine(isolated_db_url)
        insp = inspect(engine)
        actual_tables = set(insp.get_table_names())
        history_indexes = {
            ix['name'] for ix in insp.get_indexes('shopping_list_history')
        }
        engine.dispose()

        for table in SHOPPING_LISTS_TABLES:
            assert table in actual_tables, (
                f'Fresh install: table "{table}" missing after module upgrade'
            )
        assert 'ix_shopping_list_history_organization_id' in history_indexes
        assert 'ix_shopping_list_history_original_list_id' in history_indexes


EQUIPMENT_TABLES = dict(MODULES)['equipment']


@pytest.mark.integration
class TestEquipmentAttestationDowngrade:
    """migration 004 must be reversible after it has been used.

    Grouped envelopes (one response per person) leave ``assignment_id``
    NULL, so a downgrade that blindly restores NOT NULL fails on any
    database where a campaign has run — which is every database that used
    the feature the migration was written for.
    """

    def test_downgrade_after_grouped_response(self, isolated_db_url):
        _create_core_tables(isolated_db_url, 'equipment', EQUIPMENT_TABLES)
        run_module_migrations('equipment', 'upgrade', db_url=isolated_db_url)

        org_id = uuid.uuid4()
        campaign_id = uuid.uuid4()
        user_id = uuid.uuid4()
        grouped_id = uuid.uuid4()
        empty_id = uuid.uuid4()
        item_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        location_id = uuid.uuid4()

        engine = create_engine(isolated_db_url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO organizations '
                    '(id, name, enabled_modules, settings, created_at) '
                    "VALUES (:id, 'Attestation Org', '[]'::json, '{}'::json, NOW())"
                ),
                {'id': org_id},
            )
            conn.execute(
                text(
                    'INSERT INTO users '
                    '(id, email, hashed_password, role, created_at, updated_at) '
                    "VALUES (:id, :email, 'x', 'admin', NOW(), NOW())"
                ),
                {'id': user_id, 'email': f'{user_id}@example.com'},
            )
            conn.execute(
                text(
                    'INSERT INTO audit_campaigns '
                    '(id, organization_id, name, status, scope_type, '
                    'reminder_days_before, created_by, deadline, created_at) '
                    "VALUES (:id, :org, 'Campaign', 'ACTIVE', 'ALL', 3, :user, "
                    'NOW(), NOW())'
                ),
                {'id': campaign_id, 'org': org_id, 'user': user_id},
            )
            conn.execute(
                text(
                    'INSERT INTO storage_locations '
                    '(id, organization_id, name, created_by, created_at) '
                    "VALUES (:id, :org, 'Server Room', :user, NOW())"
                ),
                {'id': location_id, 'org': org_id, 'user': user_id},
            )
            conn.execute(
                text(
                    'INSERT INTO items '
                    '(id, organization_id, storage_location_id, name, quantity, '
                    'added_date, is_deleted, is_catalog_entry, created_at, '
                    'updated_at) '
                    "VALUES (:id, :org, :loc, 'Laptop', 1, CURRENT_DATE, false, "
                    'false, NOW(), NOW())'
                ),
                {'id': item_id, 'org': org_id, 'loc': location_id},
            )
            conn.execute(
                text(
                    'INSERT INTO equipment_assignments '
                    '(id, organization_id, item_id, assigned_to_name, '
                    'checked_out_at, checked_out_by) '
                    "VALUES (:id, :org, :item, 'Anna Kowalska', NOW(), :user)"
                ),
                {
                    'id': assignment_id,
                    'org': org_id,
                    'item': item_id,
                    'user': user_id,
                },
            )
            # One grouped response with two items, one with none at all.
            for response_id in (grouped_id, empty_id):
                conn.execute(
                    text(
                        'INSERT INTO audit_responses '
                        '(id, organization_id, campaign_id, assignment_id, token, '
                        'token_expires_at, assignee_email, assignee_name, status, '
                        'created_at) '
                        'VALUES (:id, :org, :campaign, NULL, :token, '
                        "NOW() + INTERVAL '30 days', :email, 'Anna Kowalska', "
                        "'PENDING', NOW())"
                    ),
                    {
                        'id': response_id,
                        'org': org_id,
                        'campaign': campaign_id,
                        'token': f'token-{response_id}',
                        'email': f'{response_id}@example.com',
                    },
                )
            for _ in range(2):
                conn.execute(
                    text(
                        'INSERT INTO audit_response_items '
                        '(id, response_id, assignment_id, item_id, item_name, '
                        'status, created_at) '
                        "VALUES (:id, :response, :assignment, :item, 'Laptop', "
                        "'PENDING', NOW())"
                    ),
                    {
                        'id': uuid.uuid4(),
                        'response': grouped_id,
                        'assignment': assignment_id,
                        'item': item_id,
                    },
                )

        run_module_migrations(
            'equipment',
            'downgrade',
            db_url=isolated_db_url,
            revision='003_lowercase_assigned_to_email',
        )

        with engine.connect() as conn:
            remaining = conn.execute(
                text('SELECT id, assignment_id FROM audit_responses')
            ).all()
            nullable = conn.execute(
                text(
                    'SELECT is_nullable FROM information_schema.columns '
                    "WHERE table_name = 'audit_responses' "
                    "AND column_name = 'assignment_id'"
                )
            ).scalar()
        engine.dispose()

        assert nullable == 'NO', 'downgrade must restore the NOT NULL constraint'
        kept = {row[0]: row[1] for row in remaining}
        assert grouped_id in kept, 'a grouped response must survive with an assignment'
        assert kept[grouped_id] == assignment_id
        assert empty_id not in kept, (
            'a grouped response with no items cannot be represented in the old '
            'schema and must be dropped rather than block the downgrade'
        )
