"""``manage.py db seed`` resolves the organization a profile is applied to.

Without ``--org`` the command seeded units of measure and said nothing else —
which made the Makefile's "storage types, categories" description a promise it
did not keep. It now reads the organizations that exist: exactly one is used,
none is reported as such, several are refused and listed.
"""

import importlib
from unittest.mock import MagicMock, patch
from uuid import uuid4

from typer.testing import CliRunner

from manage import app

runner = CliRunner()


def _seed(*args, organizations=()):
    """Invoke ``db seed`` with the organization lookup and the seeder patched.

    Both are imported inside the command, so patching the module attributes
    reaches the call the command actually makes.
    """
    with (
        patch('app.cli.commands_db.bootstrap_db'),
        patch('app.database.SessionLocal', return_value=MagicMock()),
        patch(
            'app.seed_data.list_seedable_organizations',
            return_value=list(organizations),
        ),
        patch('app.seed_data.seed_all') as seed_all,
    ):
        result = runner.invoke(app, ['db', 'seed', *args])
    return result, seed_all


class TestOneOrganization:
    """A single tenant is what a self-hosted install has; it needs no switch."""

    def test_the_only_organization_is_used_without_a_switch(self):
        org_id = uuid4()

        result, seed_all = _seed(organizations=[(org_id, 'My Organization')])

        assert result.exit_code == 0
        assert seed_all.call_args.kwargs['organization_id'] == org_id
        assert 'My Organization' in result.output

    def test_the_seeded_rows_are_named_in_the_output(self):
        org_id = uuid4()

        result, _ = _seed(organizations=[(org_id, 'My Organization')])

        assert str(org_id) in result.output

    def test_the_default_mode_leaves_existing_rows_alone(self):
        result, seed_all = _seed(organizations=[(uuid4(), 'Solo')])

        assert result.exit_code == 0
        assert seed_all.call_args.kwargs['insert_only'] is True


class TestNoOrganization:
    """A database nobody has claimed can only take the ownerless data."""

    def test_only_the_ownerless_data_is_seeded(self):
        result, seed_all = _seed(organizations=[])

        assert result.exit_code == 0
        assert seed_all.call_args.kwargs['organization_id'] is None
        assert 'units of measure' in result.output.lower()

    def test_it_names_the_step_that_creates_one(self):
        result, _ = _seed(organizations=[])

        assert 'create-admin' in result.output


class TestSeveralOrganizations:
    """Guessing a tenant would seed the wrong books; the operator chooses."""

    def test_the_run_refuses_instead_of_picking_one(self):
        result, seed_all = _seed(organizations=[(uuid4(), 'Alpha'), (uuid4(), 'Beta')])

        assert result.exit_code == 1
        seed_all.assert_not_called()
        assert 'Alpha' in result.output
        assert 'Beta' in result.output

    def test_the_refusal_names_the_way_out(self):
        result, _ = _seed(organizations=[(uuid4(), 'Alpha'), (uuid4(), 'Beta')])

        assert '--org' in result.output


class TestExplicitOrganization:
    """``--org`` keeps working and stops accepting an id that names nothing."""

    def test_the_named_organization_is_used(self):
        target = uuid4()

        result, seed_all = _seed(
            '--org',
            str(target),
            organizations=[(target, 'Chosen'), (uuid4(), 'Other')],
        )

        assert result.exit_code == 0
        assert seed_all.call_args.kwargs['organization_id'] == target

    def test_an_id_that_names_nothing_is_refused(self):
        result, seed_all = _seed(
            '--org', str(uuid4()), organizations=[(uuid4(), 'Only One')]
        )

        assert result.exit_code == 1
        seed_all.assert_not_called()
        assert 'Only One' in result.output

    def test_a_malformed_id_is_refused_rather_than_raised(self):
        result, seed_all = _seed(
            '--org', 'not-a-uuid', organizations=[(uuid4(), 'Only One')]
        )

        assert result.exit_code == 1
        seed_all.assert_not_called()
        assert 'not-a-uuid' in result.output


class TestModes:
    def test_overwrite_asks_the_seeder_to_refresh_existing_rows(self):
        result, seed_all = _seed('--overwrite', organizations=[(uuid4(), 'Solo')])

        assert result.exit_code == 0
        assert seed_all.call_args.kwargs['insert_only'] is False

    def test_the_profile_reaches_the_seeder(self):
        result, seed_all = _seed(
            '--profile', 'food_home', organizations=[(uuid4(), 'Solo')]
        )

        assert result.exit_code == 0
        assert seed_all.call_args.kwargs['profile'] == 'food_home'


class TestTheOwnerlessPath:
    """What a mocked seeder cannot see: the call the run actually makes.

    The unit seeder has its own entry point, and a mode the command accepts
    but that entry point does not take is a ``TypeError`` in production with
    every test above still green.
    """

    def test_the_default_mode_reaches_the_unit_seeder(self):
        with (
            patch('app.database.SessionLocal', return_value=MagicMock()),
            patch('app._seed_uom._seed_uom_base') as base_seed,
        ):
            from app.seed_data import seed_all

            seed_all()

        assert base_seed.call_args.kwargs['insert_only'] is True

    def test_overwrite_reaches_the_unit_seeder(self):
        with (
            patch('app.database.SessionLocal', return_value=MagicMock()),
            patch('app._seed_uom._seed_uom_base') as base_seed,
        ):
            from app.seed_data import seed_all

            seed_all(insert_only=False)

        assert base_seed.call_args.kwargs['insert_only'] is False


class TestTheProfileFallback:
    """The profile ``seed_all`` picks for an organization when none is named.

    Every command above hands one over, so the fallback is the line none of
    them reaches. ``SEED_PROFILE`` used to be read here — and the shipped
    example file offered it to operators as the way to choose — while the read
    happened once at import, where anything setting the variable later had no
    say. The module is therefore reloaded with the variable set, which is the
    one arrangement in which the old read would have had an answer; the seeder
    must still be handed the default profile, which is what lets the example
    drop the variable with a test behind it.
    """

    def test_an_organizational_seed_without_a_profile_takes_the_default(
        self, monkeypatch
    ):
        monkeypatch.setenv('SEED_PROFILE', 'food_home')
        import app.seed_data as seed_data

        seeded: dict[str, str] = {}

        def _record_the_profile(profile: str):
            seeded['profile'] = profile
            return lambda *args, **kwargs: None

        importlib.reload(seed_data)
        try:
            with (
                patch('app.database.SessionLocal', return_value=MagicMock()),
                patch.object(seed_data, '_get_seeder', _record_the_profile),
            ):
                seed_data.seed_all(organization_id=uuid4())
        finally:
            monkeypatch.delenv('SEED_PROFILE', raising=False)
            importlib.reload(seed_data)

        assert seeded['profile'] == 'clean_core'
