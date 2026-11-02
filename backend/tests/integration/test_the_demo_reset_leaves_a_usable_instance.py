"""What ``demo reset`` has to leave behind, beyond exiting zero.

Three defects on this branch had the same shape: the command reported success
and the instance was not usable. It stopped on the setup wizard; it left the
kitchen modules off while seeding rows into them; it finished a production run
that reported no result. None of them was visible from the exit code, and none
of them had a test — the only cover the reset had was its refusal guard, which
is the half that runs when nothing happens.

So this file tests the half that does happen. Two of the three functions below
are the ones those defects lived in, and the orchestration test asserts the
property that matters more than any of them: the schema is not dropped unless
the guard let the command through.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import commands_demo
from app.cli.commands_demo import (
    DEMO_EXTRA_MODULES,
    LAST_RESET_KEY,
    DemoGuardError,
    _enable_extra_modules,
    _record_reset_time,
)
from app.core.contracts import UserContextDTO
from app.models.organization import Organization
from app.models.user import User

pytestmark = pytest.mark.integration


async def _an_organization(db: AsyncSession, *, modules: list[str]) -> tuple:
    org = Organization(
        id=uuid.uuid4(), name='Demo Reset Test Org', enabled_modules=list(modules)
    )
    db.add(org)
    await db.flush()
    user = User(
        id=uuid.uuid4(),
        email=f'demo-reset-{uuid.uuid4().hex[:8]}@example.com',
        hashed_password='x',
        full_name='Demo Administrator',
        role='admin',
        is_active=True,
        organization_id=org.id,
    )
    db.add(user)
    await db.flush()
    return org, user


class TestTheExtrasAreSwitchedOn:
    """The warehouse profile leaves the kitchen off; the demo turns it back on.

    This is the function the "Module Not Enabled over rows that already exist"
    defect lived in. The interesting cases are both about *which* modules move,
    not how many.
    """

    async def test_the_missing_modules_are_enabled(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        org, user = await _an_organization(db, modules=['core', 'items'])
        context = UserContextDTO(
            id=user.id,
            email=user.email,
            role=user.role,
            organization_id=org.id,
            is_superuser=False,
        )

        await _enable_extra_modules(db, org, context)

        enabled = set(org.enabled_modules or [])
        missing = set(DEMO_EXTRA_MODULES) - enabled
        assert not missing, (
            f'{sorted(missing)} were not switched on, so their screens would '
            f'say "Module Not Enabled" over rows the seeder writes anyway.'
        )
        assert {'core', 'items'} <= enabled, 'the modules already on were dropped'

    async def test_a_module_already_on_is_not_enabled_twice(
        self, real_async_db_session: AsyncSession
    ):
        """Enabling runs module lifecycle hooks; running them again is not free.

        The guard is a set difference, and this is the test that fails if it is
        ever written as "enable the whole list".
        """
        db = real_async_db_session
        already = ['core', *DEMO_EXTRA_MODULES]
        org, user = await _an_organization(db, modules=already)
        context = UserContextDTO(
            id=user.id,
            email=user.email,
            role=user.role,
            organization_id=org.id,
            is_superuser=False,
        )

        calls: list[list[str]] = []

        async def _spy(modules, organization_id, **kwargs):
            calls.append([m.metadata.name for m in modules])

        from unittest.mock import patch

        import app.services.module_lifecycle_service as lifecycle
        from app.core.llm import registry

        original = lifecycle.enable_modules_async
        lifecycle.enable_modules_async = _spy
        try:
            # The server's own model must not decide this test: vision joins
            # the extras only when it is served, and that is tested below.
            with patch.object(registry, 'env_fallback_serves', return_value=False):
                await _enable_extra_modules(db, org, context)
        finally:
            lifecycle.enable_modules_async = original

        assert calls == [], (
            f'the lifecycle executor ran for {calls} on an organization that '
            f'already had every extra enabled.'
        )


class TestImageRecognitionFollowsTheServersModel:
    """The photo tab is on from the first screen — when the server can serve it.

    The demo serves vision from the model in its ``.env``, so an organization
    that has to find Settings > Modules to switch it on never sees the photo
    tab in Quick Add. A demo without a vision-capable model must not show a
    tab whose button is disabled, which is why the answer is conditional.
    """

    async def _enable(self, db: AsyncSession, serves: bool) -> list[str]:
        from unittest.mock import patch

        from app.core.llm import registry

        org, user = await _an_organization(
            db, modules=['core', 'items', *DEMO_EXTRA_MODULES]
        )
        context = UserContextDTO(
            id=user.id,
            email=user.email,
            role=user.role,
            organization_id=org.id,
            is_superuser=False,
        )
        with patch.object(registry, 'env_fallback_serves', return_value=serves) as ask:
            await _enable_extra_modules(db, org, context)
        ask.assert_called_with('vision.extract')
        return list(org.enabled_modules or [])

    async def test_vision_is_enabled_when_the_server_model_serves_it(
        self, real_async_db_session: AsyncSession
    ):
        enabled = await self._enable(real_async_db_session, serves=True)
        assert 'vision' in enabled, (
            'the server model serves vision.extract but the module stayed off, '
            'so Quick Add shows no photo tab until the visitor finds Settings'
        )

    async def test_vision_stays_off_when_the_server_model_does_not_serve_it(
        self, real_async_db_session: AsyncSession
    ):
        enabled = await self._enable(real_async_db_session, serves=False)
        assert 'vision' not in enabled, (
            'vision was switched on although the server has no model for it, '
            'so the photo tab would offer a button that cannot work'
        )


class TestTheRebuildTimeIsRecorded:
    """The instance says how old it is without anyone reading container logs."""

    def test_the_timestamp_lands_on_the_organization(self, setup_test_db):
        """Read back through the same door the function writes through.

        ``_record_reset_time`` opens its own ``SessionLocal`` and commits there,
        so the pytest session fixture — a transaction that is rolled back —
        cannot see the write and the function cannot see the fixture's rows.
        The round trip therefore goes through ``SessionLocal`` at both ends,
        which is also the only shape that proves the commit really happened.

        Going around every fixture is also why the test asks for
        ``setup_test_db`` itself: nothing else in its setup would provision
        the worker database, and on a scoped run whose worker has not served
        another database test, ``SessionLocal`` would open one that does not
        exist. A full suite hides that by provisioning the worker first.
        """
        from app.database import SessionLocal

        org_id = uuid.uuid4()
        with SessionLocal() as db:
            db.add(Organization(id=org_id, name='Demo Reset Stamp Org'))
            db.commit()

        try:
            _record_reset_time()

            with SessionLocal() as db:
                stamped = db.scalars(select(Organization)).all()
                assert any(
                    (row.settings or {}).get(LAST_RESET_KEY) for row in stamped
                ), (
                    'no organization carries the rebuild time, so the instance '
                    'cannot say how old it is'
                )
        finally:
            with SessionLocal() as db:
                db.query(Organization).filter(Organization.id == org_id).delete()
                db.commit()


class TestTheGuardStandsInFrontOfTheDrop:
    """The property worth more than every other test in this file.

    ``demo reset`` drops the schema. Everything else it does is recoverable by
    running it again; that one step is not, and it runs unattended. So the
    ordering is asserted directly: a refused guard must leave ``_drop_schema``
    uncalled.
    """

    def test_a_refused_guard_never_reaches_the_drop(self, monkeypatch):
        dropped: list[bool] = []

        def _refuse() -> None:
            raise DemoGuardError('not a demo instance')

        monkeypatch.setattr(commands_demo, 'guard_demo_instance', _refuse)
        monkeypatch.setattr(commands_demo, '_drop_schema', lambda: dropped.append(True))
        monkeypatch.setattr(
            commands_demo,
            '_clear_the_uploads',
            lambda: pytest.fail('the uploads were emptied after a refusal'),
        )
        monkeypatch.setattr(
            commands_demo,
            '_seed_everything',
            lambda *a, **k: pytest.fail('seeding ran after a refusal'),
        )

        import typer

        with pytest.raises(typer.Exit) as excinfo:
            commands_demo.reset(
                items=1, admin_email='a@example.com', admin_password='x'
            )

        assert excinfo.value.exit_code == 1
        assert dropped == [], 'the schema was dropped on an instance that refused'

    def test_the_happy_path_drops_then_seeds_then_records(self, monkeypatch):
        """And in that order — seeding a schema that is about to be dropped is a no-op.

        The uploaded files go between the drop and the seed: once the rows are
        gone nothing points at them, and the seed writes files of its own. The
        whole destructive part runs under the migration lock, so a backend
        starting beside the rebuild waits instead of migrating into the drop.
        """
        order: list[str] = []

        @contextlib.contextmanager
        def _lock():
            order.append('lock')
            yield
            order.append('unlock')

        monkeypatch.setattr(commands_demo, 'hold_migration_lock', _lock)
        monkeypatch.setattr(commands_demo, 'guard_demo_instance', lambda: None)
        monkeypatch.setattr(commands_demo, '_drop_schema', lambda: order.append('drop'))
        monkeypatch.setattr(
            commands_demo, '_clear_the_uploads', lambda: order.append('uploads')
        )
        monkeypatch.setattr(
            commands_demo,
            '_seed_everything',
            lambda *a, **k: (order.append('seed'), {'items_total': 3})[1],
        )
        monkeypatch.setattr(
            commands_demo,
            '_cap_the_ai_requests',
            lambda: (order.append('cap'), 20)[1],
        )
        monkeypatch.setattr(
            commands_demo, '_record_reset_time', lambda: order.append('record')
        )

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        # The ceiling goes after the seed: before it, the schema the limits
        # live in does not exist yet.
        assert order == ['lock', 'drop', 'uploads', 'seed', 'cap', 'record', 'unlock']


class TestTheWizardIsAnswered:
    """A visitor must not be asked to choose somebody else's workflow.

    The defect this covers: ``demo reset`` exited zero and the instance opened
    on "Choose your workflow". On a public demo that is wrong twice over — the
    visitor is asked a question about an organization that is not theirs, and
    whoever answers it first changes what everybody after them sees until the
    next rebuild.
    """

    async def test_onboarding_is_completed_and_the_profile_is_recorded(
        self, real_async_db_session: AsyncSession
    ):
        from app.cli.commands_demo import DEMO_PROFILE_ID, apply_demo_onboarding

        db = real_async_db_session
        org, user = await _an_organization(db, modules=['core'])
        await db.commit()

        await apply_demo_onboarding(db, user.email)

        refreshed = (
            await db.execute(
                select(
                    Organization.onboarding_completed,
                    Organization.active_profile_id,
                    Organization.enabled_modules,
                ).where(Organization.id == org.id)
            )
        ).one()
        completed, profile, enabled = refreshed

        assert completed, (
            'onboarding was not marked complete, so the instance opens on the '
            'setup wizard and the first visitor answers it for everyone'
        )
        assert profile == DEMO_PROFILE_ID
        missing = set(DEMO_EXTRA_MODULES) - set(enabled or [])
        assert not missing, (
            f'{sorted(missing)} stayed off after onboarding — their screens '
            f'would say "Module Not Enabled" over rows the seeder writes'
        )

    async def test_a_second_run_is_a_no_op(self, real_async_db_session: AsyncSession):
        """The reset is safe to run on an instance it already built.

        ``apply_onboarding_profile_async`` refuses an organization that has
        already onboarded, so without the early return the second nightly
        rebuild would fail on an instance that is otherwise fine.
        """
        from app.cli.commands_demo import apply_demo_onboarding

        db = real_async_db_session
        _org, user = await _an_organization(db, modules=['core'])
        await db.commit()

        await apply_demo_onboarding(db, user.email)
        await apply_demo_onboarding(db, user.email)  # must not raise

    async def test_an_unknown_admin_is_left_alone(
        self, real_async_db_session: AsyncSession
    ):
        """No user, nothing to onboard — and nothing to blow up on either."""
        from app.cli.commands_demo import apply_demo_onboarding

        await apply_demo_onboarding(real_async_db_session, 'nobody-at-all@example.com')


class TestTheRebuildRunsItsStepsInOrder:
    """``_seed_everything`` is orchestration, and the order is the content.

    Every pair here is a failure somebody meets: an admin created before the
    migrations has no table to land in, an onboarding run before the admin
    exists finds no organization to onboard, and demo rows written before
    onboarding land in modules the instance has switched off — which is the
    defect that shipped "Module Not Enabled" over seeded production runs.
    """

    def test_the_steps_run_migrations_then_admin_then_onboarding_then_rows(
        self, monkeypatch
    ):
        order: list[str] = []

        import alembic.command as alembic_command

        import app.cli.commands_db as commands_db
        import app.cli.commands_user as commands_user
        import app.seed_data as seed_data
        import seed_demo_data
        import seed_demo_showcase

        monkeypatch.setattr(commands_demo, 'bootstrap_db', lambda: order.append('boot'))
        monkeypatch.setattr(
            alembic_command, 'upgrade', lambda *a, **k: order.append('migrate')
        )
        monkeypatch.setattr(
            commands_db, '_upgrade_all_modules', lambda: order.append('migrate:modules')
        )
        monkeypatch.setattr(
            seed_data, 'seed_all', lambda **k: order.append('seed:system')
        )
        monkeypatch.setattr(
            commands_user, 'create_admin', lambda **k: order.append('admin')
        )

        async def _onboard(_email: str) -> None:
            order.append('onboarding')

        monkeypatch.setattr(commands_demo, '_complete_onboarding', _onboard)
        monkeypatch.setattr(
            seed_demo_data,
            'seed_from_cli',
            lambda **k: (order.append('seed:rows'), {'items_total': 7})[1],
        )
        monkeypatch.setattr(
            seed_demo_showcase,
            'dress_from_cli',
            lambda **k: (order.append('showcase'), {'labels': 12})[1],
        )

        report = commands_demo._seed_everything(
            items=7, admin_email='a@example.com', admin_password='x'
        )

        assert report == {'items_total': 7, 'labels': 12}
        assert order.index('migrate') < order.index('admin'), (
            'the admin account was created before the migrations that make its table'
        )
        assert order.index('admin') < order.index('onboarding'), (
            'onboarding ran before the account whose organization it onboards'
        )
        assert order.index('onboarding') < order.index('seed:rows'), (
            'demo rows were written before onboarding enabled the modules they '
            'belong to — that is how "Module Not Enabled" ends up over seeded data'
        )
        assert order.index('seed:rows') < order.index('showcase'), (
            'the demo was dressed before the rows it takes the seed marker off'
        )

    def test_seeding_targets_the_administrator_the_operator_chose(self, monkeypatch):
        """The demo chooses its own administrator now; the seed must aim at
        that account, not at the address this script was written around.

        Found on the review smoke of the credential change: with any email
        other than ``admin@example.com`` the reset created the admin and
        then died seeding rows — the demo came up with no data.
        """
        received: dict[str, object] = {}
        dressed: dict[str, object] = {}

        import alembic.command as alembic_command

        import app.cli.commands_db as commands_db
        import app.cli.commands_user as commands_user
        import app.seed_data as seed_data
        import seed_demo_data
        import seed_demo_showcase

        monkeypatch.setattr(commands_demo, 'bootstrap_db', lambda: None)
        monkeypatch.setattr(alembic_command, 'upgrade', lambda *a, **k: None)
        monkeypatch.setattr(commands_db, '_upgrade_all_modules', lambda: None)
        monkeypatch.setattr(seed_data, 'seed_all', lambda **k: None)
        created: dict = {}
        monkeypatch.setattr(
            commands_user, 'create_admin', lambda **k: created.update(k)
        )

        async def _onboard(_email: str) -> None:
            return None

        monkeypatch.setattr(commands_demo, '_complete_onboarding', _onboard)
        monkeypatch.setattr(
            seed_demo_data,
            'seed_from_cli',
            lambda **k: received.update(k) or {'items_total': 0},
        )
        monkeypatch.setattr(
            seed_demo_showcase,
            'dress_from_cli',
            lambda **k: dressed.update(k) or {},
        )

        commands_demo._seed_everything(
            items=3, admin_email='ops@demo.test', admin_password='chosen'
        )

        assert created.get('instance_superuser') is False, (
            'the shared demo account must not be the instance superuser'
        )
        assert received.get('admin_email') == 'ops@demo.test', (
            'seed_from_cli was not told which account was created'
        )
        assert dressed.get('admin_email') == 'ops@demo.test', (
            'the showcase step was not told which account was created'
        )

    def test_seed_from_cli_looks_up_the_account_it_was_given(self, monkeypatch):
        """The DB lookup inside seed_from_cli follows the same parameter."""
        captured: list[object] = []

        import seed_demo_data

        class _EmailColumn:
            def __eq__(self, other: object) -> tuple[str, object]:
                captured.append(other)
                return ('email_is', other)

        class _FakeUser:
            email = _EmailColumn()

        class _Query:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                class _User:
                    id = 'u1'
                    organization_id = 'org1'

                return _User()

        class _Session:
            def query(self, model):
                return _Query()

            def commit(self):
                pass

            def close(self):
                pass

        monkeypatch.setattr(seed_demo_data, 'User', _FakeUser)
        monkeypatch.setattr(seed_demo_data, 'SessionLocal', lambda: _Session())
        monkeypatch.setattr(
            seed_demo_data,
            'seed_organization',
            lambda *a, **k: {'items_total': 0},
        )

        seed_demo_data.seed_from_cli(items=1, admin_email='ops@demo.test')

        assert captured == ['ops@demo.test'], (
            'the lookup still targets a hardcoded address'
        )


class TestTheDropRefusesWithoutADatabase:
    def test_a_missing_database_url_is_a_named_refusal(self, monkeypatch):
        """Not an AttributeError three frames down inside SQLAlchemy."""
        monkeypatch.delenv('DATABASE_URL', raising=False)
        with pytest.raises(DemoGuardError) as excinfo:
            commands_demo._drop_schema()
        assert 'DATABASE_URL' in str(excinfo.value)
