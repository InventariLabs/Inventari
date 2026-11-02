"""Unit tests for tenancy hardening lint checks."""

from app.core.architecture_lint._quality_checks_tenancy import (
    _check_escape_hatch_org_filter,
    _check_escape_hatch_query_scoping,
    _check_public_api_missing_org,
    _check_public_api_optional_org,
    _collect_public_api_missing_org_keys,
)

PUBLIC_API_SAMPLE = """
from uuid import UUID

class CoreThingsAPI:
    async def get_async(self, db, thing_id: UUID, organization_id: UUID | None = None):
        pass
"""

PUBLIC_API_REQUIRED_ORG = """
from uuid import UUID

class CoreThingsAPI:
    async def get_async(self, db, thing_id: UUID, organization_id: UUID):
        pass

    async def get_global_async(
        self, db, thing_id: UUID, organization_id: UUID, *, include_global: bool = False
    ):
        pass
"""

PUBLIC_API_KEYWORD_ONLY_NONE = """
from uuid import UUID

class CoreThingsAPI:
    async def get_async(self, db, thing_id: UUID, *, organization_id: UUID | None = None):
        pass
"""

PUBLIC_API_NONE_ANNOTATION_NO_DEFAULT = """
from uuid import UUID

class CoreThingsAPI:
    # Caller must pass explicitly (may still pass None) — not a silent bypass,
    # but flagged only when combined with a None default.
    async def get_async(self, db, organization_id: UUID | None):
        pass
"""


def _write(tmp_path, name, content):
    target = tmp_path / name
    target.write_text(content)
    return target


class TestPublicApiOptionalOrg:
    def test_flags_optional_org_with_none_default(self, tmp_path):
        _write(tmp_path, 'things.py', PUBLIC_API_SAMPLE)
        errors = _check_public_api_optional_org(tmp_path)
        assert len(errors) == 1
        assert errors[0].startswith('::error')
        assert 'get_async()' in errors[0]

    def test_flags_keyword_only_optional_org(self, tmp_path):
        _write(tmp_path, 'things.py', PUBLIC_API_KEYWORD_ONLY_NONE)
        errors = _check_public_api_optional_org(tmp_path)
        assert len(errors) == 1

    def test_passes_required_org_and_include_global(self, tmp_path):
        _write(tmp_path, 'things.py', PUBLIC_API_REQUIRED_ORG)
        assert _check_public_api_optional_org(tmp_path) == []

    def test_passes_none_annotation_without_default(self, tmp_path):
        _write(tmp_path, 'things.py', PUBLIC_API_NONE_ANNOTATION_NO_DEFAULT)
        assert _check_public_api_optional_org(tmp_path) == []

    def test_skips_dunder_init(self, tmp_path):
        _write(tmp_path, '__init__.py', PUBLIC_API_SAMPLE)
        assert _check_public_api_optional_org(tmp_path) == []

    def test_real_public_api_is_clean(self):
        from app.core.architecture_lint._constants import PUBLIC_API_ROOT

        assert _check_public_api_optional_org(PUBLIC_API_ROOT) == []


ESCAPE_HATCH_WITH_ORG = """
# architecture: allow_direct_db_access
# reason: complex analytics query needs direct database access

async def run(db, organization_id):
    return db.execute(query.where(table.c.organization_id == organization_id))
"""

ESCAPE_HATCH_NO_ORG = """
# architecture: allow_direct_db_access
# reason: complex analytics query needs direct database access

async def run(db):
    return db.execute(query)
"""

NO_MARKER = """
async def run(db):
    return db.execute(query)
"""


class TestEscapeHatchOrgFilter:
    def test_flags_escape_hatch_without_org_reference(self, tmp_path):
        _write(tmp_path, 'service.py', ESCAPE_HATCH_NO_ORG)
        entries = _check_escape_hatch_org_filter(tmp_path, set())
        assert len(entries) == 1
        assert entries[0].startswith('::error')

    def test_baselined_entry_is_notice(self, tmp_path):
        target = _write(tmp_path, 'service.py', ESCAPE_HATCH_NO_ORG)
        entries = _check_escape_hatch_org_filter(tmp_path, {str(target)})
        assert len(entries) == 1
        assert entries[0].startswith('::notice')

    def test_passes_when_org_referenced(self, tmp_path):
        _write(tmp_path, 'service.py', ESCAPE_HATCH_WITH_ORG)
        assert _check_escape_hatch_org_filter(tmp_path, set()) == []

    def test_ignores_files_without_marker(self, tmp_path):
        _write(tmp_path, 'service.py', NO_MARKER)
        assert _check_escape_hatch_org_filter(tmp_path, set()) == []

    def test_skips_alembic_env_files(self, tmp_path):
        """migrations/env.py is exempt — metadata tooling, no data queries."""
        env_dir = tmp_path / 'migrations'
        env_dir.mkdir()
        _write(env_dir, 'env.py', ESCAPE_HATCH_NO_ORG)
        # A sibling non-env escape hatch must still be flagged.
        _write(tmp_path, 'service.py', ESCAPE_HATCH_NO_ORG)
        entries = _check_escape_hatch_org_filter(tmp_path, set())
        assert len(entries) == 1
        assert 'env.py' not in entries[0]

    def test_skips_root_migrations_env(self, tmp_path):
        """Root migrations/env.py is exempt too."""
        env_dir = tmp_path / 'migrations'
        env_dir.mkdir()
        _write(env_dir, 'env.py', ESCAPE_HATCH_NO_ORG)
        assert _check_escape_hatch_org_filter(tmp_path, set()) == []

    def test_real_app_tree_matches_baseline(self):
        """Every non-baselined escape-hatch file references organization_id."""
        from app.core.architecture_lint._baselines import (
            _load_escape_hatch_org_filter_baseline,
        )
        from app.core.architecture_lint._constants import APP_ROOT

        entries = _check_escape_hatch_org_filter(
            APP_ROOT, _load_escape_hatch_org_filter_baseline()
        )
        errors = [entry for entry in entries if entry.startswith('::error')]
        assert errors == []


# ---------------------------------------------------------------------------
# Public_api methods addressed by an id but taking no organization
# ---------------------------------------------------------------------------

PUBLIC_API_MISSING_ORG = """
from uuid import UUID

class CoreUsersAPI:
    async def get_async(self, db, user_id: UUID):
        pass

    async def get_by_email_async(self, db, email: str):
        pass
"""

PUBLIC_API_MISSING_ORG_OPT_OUTS = """
from uuid import UUID

class CoreThingsAPI:
    async def get_async(self, db, thing_id: UUID, org_id: UUID):
        pass

    async def get_scoped_async(self, db, thing_id: UUID, organization_id: UUID):
        pass

    async def list_all_async(self, db, thing_id: UUID, *, include_global: bool = False):
        return db.query(thing_id, scope=None if include_global else 'org')

    async def list_for_user_async(self, db, user_id: UUID):
        pass

    async def list_async(self, db):
        pass

    def _private_helper(self, db, thing_id: UUID):
        pass
"""


class TestPublicApiMissingOrg:
    def test_flags_method_taking_an_id_without_org(self, tmp_path):
        _write(tmp_path, 'users.py', PUBLIC_API_MISSING_ORG)

        entries = _check_public_api_missing_org(tmp_path, set())

        assert len(entries) == 2
        assert all(entry.startswith('::error') for entry in entries)
        assert any('get_by_email_async()' in entry for entry in entries)

    def test_baselined_hit_is_a_notice(self, tmp_path):
        _write(tmp_path, 'users.py', PUBLIC_API_MISSING_ORG)

        baseline = _collect_public_api_missing_org_keys(tmp_path)

        entries = _check_public_api_missing_org(tmp_path, baseline)

        assert entries
        assert all(entry.startswith('::notice') for entry in entries)

    def test_org_param_and_explicit_opt_outs_are_clean(self, tmp_path):
        _write(tmp_path, 'things.py', PUBLIC_API_MISSING_ORG_OPT_OUTS)

        assert _check_public_api_missing_org(tmp_path, set()) == []

    def test_collected_keys_match_the_baseline_format(self, tmp_path):
        _write(tmp_path, 'users.py', PUBLIC_API_MISSING_ORG)

        keys = _collect_public_api_missing_org_keys(tmp_path)

        # Paths are relative to the app root in the real tree; under tmp_path
        # they stay absolute, so compare the tails.
        assert {key.rsplit('/', 1)[-1] for key in keys} == {
            'users.py::get_async',
            'users.py::get_by_email_async',
        }


MODULE_API_MISSING_ORG = """
from uuid import UUID

class ShoppingListsAPI:
    async def add_items_async(self, db, list_id: UUID, items: list):
        pass
"""

MODULE_INTERNAL_HELPER = """
from uuid import UUID

class _Internal:
    async def add_items_async(self, db, list_id: UUID, items: list):
        pass
"""


class TestTheRuleReachesModuleApis:
    """A module's own ``<name>_api.py`` is read by sibling modules under the
    same conditions as Core's facade: an id arrives from the caller, and
    whether it belongs to the caller's organization is the caller's word.
    Scanning only ``core/public_api`` was not a decision — it just left the
    modular half of the surface with nothing checking it.
    """

    def test_a_module_api_without_org_is_flagged(self, tmp_path):
        modules = tmp_path / 'modules' / 'shopping_lists'
        modules.mkdir(parents=True)
        (modules / 'shopping_lists_api.py').write_text(MODULE_API_MISSING_ORG)
        core = tmp_path / 'public_api'
        core.mkdir()

        entries = _check_public_api_missing_org(core, set(), tmp_path / 'modules')

        assert len(entries) == 1
        assert 'add_items_async()' in entries[0]
        assert entries[0].startswith('::error')

    def test_a_file_that_is_not_the_module_api_is_left_alone(self, tmp_path):
        modules = tmp_path / 'modules' / 'shopping_lists'
        modules.mkdir(parents=True)
        (modules / '_list_crud.py').write_text(MODULE_API_MISSING_ORG)
        core = tmp_path / 'public_api'
        core.mkdir()

        assert _check_public_api_missing_org(core, set(), tmp_path / 'modules') == []

    def test_module_tests_are_not_the_surface(self, tmp_path):
        tests = tmp_path / 'modules' / 'shopping_lists' / 'tests'
        tests.mkdir(parents=True)
        (tests / 'fake_api.py').write_text(MODULE_API_MISSING_ORG)
        core = tmp_path / 'public_api'
        core.mkdir()

        assert _check_public_api_missing_org(core, set(), tmp_path / 'modules') == []

    def test_without_a_modules_dir_the_rule_is_the_old_one(self, tmp_path):
        modules = tmp_path / 'modules' / 'shopping_lists'
        modules.mkdir(parents=True)
        (modules / 'shopping_lists_api.py').write_text(MODULE_API_MISSING_ORG)
        core = tmp_path / 'public_api'
        core.mkdir()

        assert _check_public_api_missing_org(core, set()) == []

    def test_collected_keys_cover_both_halves(self, tmp_path):
        core = tmp_path / 'public_api'
        core.mkdir()
        (core / 'users.py').write_text(PUBLIC_API_MISSING_ORG)
        modules = tmp_path / 'modules' / 'shopping_lists'
        modules.mkdir(parents=True)
        (modules / 'shopping_lists_api.py').write_text(MODULE_API_MISSING_ORG)

        keys = _collect_public_api_missing_org_keys(core, tmp_path / 'modules')

        assert {key.rsplit('/', 1)[-1] for key in keys} == {
            'users.py::get_async',
            'users.py::get_by_email_async',
            'shopping_lists_api.py::add_items_async',
        }


PUBLIC_API_DEAD_OPT_OUT = """
from uuid import UUID

class CoreThingsAPI:
    async def get_async(self, db, thing_id: UUID, *, include_global: bool = False):
        return await db.get(thing_id)
"""

PUBLIC_API_POSITIONAL_ONLY_ORG = """
from uuid import UUID

class CoreThingsAPI:
    async def get_async(self, db, thing_id: UUID, organization_id: UUID, /):
        pass
"""

PUBLIC_API_POSITIONAL_ONLY_OPTIONAL_ORG = """
from uuid import UUID

class CoreThingsAPI:
    async def get_async(self, db, organization_id: UUID | None = None, /):
        pass
"""


class TestOptOutMustBeUsed:
    """``include_global`` silences the rule only where the body consults it.

    Without this, the guard against a confused deputy switched off by adding
    one unread parameter to the signature. ``test_dead_opt_out`` fails on the
    old check; ``test_live_opt_out`` passes on both and is here to pin the
    behaviour that must survive.
    """

    def test_dead_opt_out_does_not_silence_the_rule(self, tmp_path):
        _write(tmp_path, 'things.py', PUBLIC_API_DEAD_OPT_OUT)

        entries = _check_public_api_missing_org(tmp_path, set())

        assert len(entries) == 1
        assert entries[0].startswith('::error')
        assert 'get_async()' in entries[0]

    def test_live_opt_out_still_silences_the_rule(self, tmp_path):
        _write(tmp_path, 'things.py', PUBLIC_API_MISSING_ORG_OPT_OUTS)

        assert _check_public_api_missing_org(tmp_path, set()) == []


class TestPositionalOnlyParameters:
    """A parameter before ``/`` exists for both guards.

    ``ast.arguments.posonlyargs`` is a separate list; skipping it made an
    org parameter declared positional-only invisible -- clean by the guard's
    reading, and equally clean if it had been missing altogether.
    ``test_positional_only_optional_org_is_flagged`` fails on the old check.
    ``test_positional_only_org_counts_as_present`` passes on both, but for
    two different reasons: the old check could not see the id parameter
    either, so it stayed quiet by blindness rather than by agreement.
    """

    def test_positional_only_org_counts_as_present(self, tmp_path):
        _write(tmp_path, 'things.py', PUBLIC_API_POSITIONAL_ONLY_ORG)

        assert _check_public_api_missing_org(tmp_path, set()) == []

    def test_positional_only_optional_org_is_flagged(self, tmp_path):
        _write(tmp_path, 'things.py', PUBLIC_API_POSITIONAL_ONLY_OPTIONAL_ORG)

        errors = _check_public_api_optional_org(tmp_path)

        assert len(errors) == 1
        assert errors[0].startswith('::error')


# ---------------------------------------------------------------------------
# Escape-hatch queries read one statement at a time
# ---------------------------------------------------------------------------

ESCAPE_HATCH_WORD_ELSEWHERE = """
# architecture: allow_direct_db_access
# reason: register aggregation needs direct database access

from sqlalchemy import select


async def list_scoped(db, organization_id):
    return await db.execute(select(Doc).where(Doc.organization_id == organization_id))


async def get_by_id(db, doc_id):
    # organization_id is written in this comment, and that used to be enough.
    return await db.execute(select(Doc).where(Doc.id == doc_id))
"""

ESCAPE_HATCH_CONDITIONS_VARIABLE = """
# architecture: allow_direct_db_access
# reason: register aggregation needs direct database access

from sqlalchemy import select


async def list_window(db, org_id, date_from):
    conditions = _window_conditions(org_id, date_from)
    return await db.execute(select(Doc).where(*conditions))
"""

ESCAPE_HATCH_DERIVED_IDS = """
# architecture: allow_direct_db_access
# reason: analytics query needs direct database access

from sqlalchemy import select


async def list_in_storages(db, organization_id):
    storage_ids = await get_internal_storage_ids_async(db, organization_id)
    return await db.execute(select(Item).where(Item.storage_id.in_(storage_ids)))
"""

ESCAPE_HATCH_FILTER_BY_ORG = """
# architecture: allow_direct_db_access
# reason: register aggregation needs direct database access

from sqlalchemy import select


async def list_for_org(db, organization_id):
    return await db.execute(select(Doc).filter_by(organization_id=organization_id))
"""

ESCAPE_HATCH_FILTER_BY_ID = """
# architecture: allow_direct_db_access
# reason: register aggregation needs direct database access

from sqlalchemy import select


async def get_by_id(db, doc_id):
    return await db.execute(select(Doc).filter_by(id=doc_id))
"""

ESCAPE_HATCH_JOIN_CONDITION = """
# architecture: allow_direct_db_access
# reason: analytics query needs direct database access

from sqlalchemy import select


async def get_item_for_partner(db, item_id, organization_id):
    return await db.execute(
        select(Item)
        .join(Partner, Partner.organization_id == organization_id)
        .where(Item.id == item_id)
    )
"""

ESCAPE_HATCH_LOOP_VARIABLE = """
# architecture: allow_direct_db_access
# reason: analytics query needs direct database access

from sqlalchemy import select


async def fan_out(db, organization_id):
    scoped = await db.execute(select(Row.item_id).where(Row.organization_id == organization_id))
    for item_id, _count in scoped.all():
        await db.execute(select(Item).where(Item.id == item_id))
"""

ESCAPE_HATCH_RAW_SQL = """
# architecture: allow_direct_db_access
# reason: reporting query needs direct database access

from sqlalchemy import text


async def report(db, organization_id):
    return await db.execute(text('SELECT * FROM items'))
"""

ESCAPE_HATCH_ORDER_BY_ORG = """
# architecture: allow_direct_db_access
# reason: register aggregation needs direct database access

from sqlalchemy import select


async def list_for_item(db, item_id):
    # Sorting by the tenant column names it without restricting anything.
    return await db.execute(
        select(Item).where(Item.id == item_id).order_by(Item.organization_id)
    )
"""

ESCAPE_HATCH_ORG_AS_COLUMN = """
# architecture: allow_direct_db_access
# reason: register aggregation needs direct database access

from sqlalchemy import select


async def owner_of_item(db, item_id):
    # The organization is what the row returns, not what selects the row.
    return await db.execute(select(Item.organization_id).where(Item.id == item_id))
"""

ESCAPE_HATCH_ORG_IN_DEAD_BRANCH = """
# architecture: allow_direct_db_access
# reason: register aggregation needs direct database access

from sqlalchemy import select


async def get_item(db, item_id, org):
    return await db.execute(
        select(Item).where(Item.id == item_id if True else Item.organization_id == org)
    )
"""

ESCAPE_HATCH_LAUNDERED_PREDICATE = """
# architecture: allow_direct_db_access
# reason: analytics query needs direct database access

from sqlalchemy import select


async def find_by_name(db, item_id, organization_id):
    label = str(organization_id)
    # `label` carries the organization; a name comparison is not a tenant filter.
    return await db.execute(select(Item).where(Item.id == item_id, Item.name == label))
"""


class TestEscapeHatchQueryScoping:
    """The filter is bound to the statement, not to the file.

    Every test here fails on the file-level check that came before it: that
    one only ever asked whether the word ``organization_id`` occurred
    somewhere in the source. The second half of the class asks the narrower
    question the first version of *this* check still answered by the word: the
    organization may occur in the statement -- in the columns it returns, in
    the ordering, in a branch that never runs, in a local that the filter then
    compares against something else entirely -- and the rows are still every
    organization's. Only the arguments of ``where()`` / ``filter()`` /
    ``filter_by()`` restrict them; a join's ``ON`` narrows the paired rows
    instead, which is not the same as narrowing the entity the statement
    selects (``test_a_join_condition_alone_does_not_scope_the_statement``).
    """

    def test_flags_query_whose_file_mentions_org_elsewhere(self, tmp_path):
        _write(tmp_path, 'register.py', ESCAPE_HATCH_WORD_ELSEWHERE)

        entries = _check_escape_hatch_query_scoping(tmp_path, set())

        assert len(entries) == 1
        assert entries[0].startswith('::error')
        assert 'get_by_id()' in entries[0]
        # ...and the file passes the older, file-level check.
        assert _check_escape_hatch_org_filter(tmp_path, set()) == []

    def test_org_in_the_ordering_does_not_scope(self, tmp_path):
        """``order_by(Item.organization_id)`` orders every tenant's rows."""
        _write(tmp_path, 'register.py', ESCAPE_HATCH_ORDER_BY_ORG)

        entries = _check_escape_hatch_query_scoping(tmp_path, set())

        assert len(entries) == 1
        assert entries[0].startswith('::error')
        assert 'list_for_item()' in entries[0]
        # ...and the file passes the older, file-level check.
        assert _check_escape_hatch_org_filter(tmp_path, set()) == []

    def test_org_in_the_result_columns_does_not_scope(self, tmp_path):
        """``select(Item.organization_id)`` reads the column; it filters nothing."""
        _write(tmp_path, 'register.py', ESCAPE_HATCH_ORG_AS_COLUMN)

        entries = _check_escape_hatch_query_scoping(tmp_path, set())

        assert len(entries) == 1
        assert entries[0].startswith('::error')
        assert 'owner_of_item()' in entries[0]
        # ...and the file passes the older, file-level check.
        assert _check_escape_hatch_org_filter(tmp_path, set()) == []

    def test_org_in_a_branch_that_never_runs_does_not_scope(self, tmp_path):
        """A comparison in the dead half of ``X if True else Y`` is not a proof:
        every ``X if flag else <org comparison>`` would otherwise pass."""
        _write(tmp_path, 'register.py', ESCAPE_HATCH_ORG_IN_DEAD_BRANCH)

        entries = _check_escape_hatch_query_scoping(tmp_path, set())

        assert len(entries) == 1
        assert entries[0].startswith('::error')
        assert 'get_item()' in entries[0]
        # ...and the file passes the older, file-level check.
        assert _check_escape_hatch_org_filter(tmp_path, set()) == []

    def test_derived_value_in_an_unrelated_predicate_does_not_scope(self, tmp_path):
        """``label = str(organization_id)`` is derived from the org, and
        ``Item.name == label`` still compares names: the value being org-derived
        says nothing about the column it is matched against."""
        _write(tmp_path, 'analytics.py', ESCAPE_HATCH_LAUNDERED_PREDICATE)

        entries = _check_escape_hatch_query_scoping(tmp_path, set())

        assert len(entries) == 1
        assert entries[0].startswith('::error')
        assert 'find_by_name()' in entries[0]
        # ...and the file passes the older, file-level check.
        assert _check_escape_hatch_org_filter(tmp_path, set()) == []

    def test_filter_list_built_next_door_counts_as_scoped(self, tmp_path):
        _write(tmp_path, 'register.py', ESCAPE_HATCH_CONDITIONS_VARIABLE)

        assert _check_escape_hatch_query_scoping(tmp_path, set()) == []

    def test_ids_fetched_for_the_org_count_as_scoped(self, tmp_path):
        _write(tmp_path, 'analytics.py', ESCAPE_HATCH_DERIVED_IDS)

        assert _check_escape_hatch_query_scoping(tmp_path, set()) == []

    def test_filter_by_with_the_org_scopes_the_query(self, tmp_path):
        """``filter_by(organization_id=...)`` is the same filter in the
        keyword spelling: read as a scope, not as a refusal."""
        _write(tmp_path, 'register.py', ESCAPE_HATCH_FILTER_BY_ORG)

        assert _check_escape_hatch_query_scoping(tmp_path, set()) == []

    def test_filter_by_on_another_column_does_not_scope(self, tmp_path):
        """Reading ``filter_by``'s keywords widens what counts, not what
        passes: a keyword that names no organization is still nobody's
        tenant filter. Passes before and after the keyword reading — it
        guards the widening rather than driving it."""
        _write(tmp_path, 'register.py', ESCAPE_HATCH_FILTER_BY_ID)

        entries = _check_escape_hatch_query_scoping(tmp_path, set())

        assert len(entries) == 1
        assert entries[0].startswith('::error')
        assert 'get_by_id()' in entries[0]

    def test_a_join_condition_alone_does_not_scope_the_statement(self, tmp_path):
        """An inner join's ``ON`` does narrow the paired rows, but not
        necessarily the rows of the entity the statement selects: with
        only ``Partner.organization_id == organization_id`` in the ``ON``
        every organization's item still comes back. The check reads the
        statement's filter clauses, which is where this codebase puts the
        tenant — a decision, pinned here so it is not read as a gap.
        Passes on both sides of this change: it holds the decision, it
        does not drive it."""
        _write(tmp_path, 'analytics.py', ESCAPE_HATCH_JOIN_CONDITION)

        entries = _check_escape_hatch_query_scoping(tmp_path, set())

        assert len(entries) == 1
        assert entries[0].startswith('::error')
        assert 'get_item_for_partner()' in entries[0]

    def test_id_out_of_a_loop_does_not_count(self, tmp_path):
        """The value is org-scoped; the statement is not, and it is the one
        that survives somebody moving the loop."""
        _write(tmp_path, 'analytics.py', ESCAPE_HATCH_LOOP_VARIABLE)

        entries = _check_escape_hatch_query_scoping(tmp_path, set())

        assert len(entries) == 1
        assert 'fan_out()' in entries[0]

    def test_raw_sql_is_read_too(self, tmp_path):
        _write(tmp_path, 'report.py', ESCAPE_HATCH_RAW_SQL)

        entries = _check_escape_hatch_query_scoping(tmp_path, set())

        assert len(entries) == 1
        assert 'text()' in entries[0]

    def test_baselined_function_is_a_notice(self, tmp_path):
        target = _write(tmp_path, 'register.py', ESCAPE_HATCH_WORD_ELSEWHERE)
        key = f'{target}::get_by_id'

        entries = _check_escape_hatch_query_scoping(tmp_path, {key})

        assert len(entries) == 1
        assert entries[0].startswith('::notice')

    def test_ignores_files_without_the_marker(self, tmp_path):
        _write(
            tmp_path,
            'plain.py',
            ESCAPE_HATCH_WORD_ELSEWHERE.replace(
                '# architecture: allow_direct_db_access', '# just a service'
            ),
        )

        assert _check_escape_hatch_query_scoping(tmp_path, set()) == []

    def test_real_app_tree_has_no_unscoped_escape_hatch_query(self):
        from app.core.architecture_lint._baselines import (
            _load_escape_hatch_query_scope_baseline,
        )
        from app.core.architecture_lint._constants import APP_ROOT

        baseline, baseline_errors = _load_escape_hatch_query_scope_baseline()
        assert baseline_errors == []
        entries = _check_escape_hatch_query_scoping(APP_ROOT, baseline)
        assert [entry for entry in entries if entry.startswith('::error')] == []
