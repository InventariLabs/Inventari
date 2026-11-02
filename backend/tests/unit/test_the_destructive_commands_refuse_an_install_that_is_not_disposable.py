"""``db reset``, ``db downgrade`` and ``demo reset`` destroy data, so they ask first.

They used to refuse only when ``INVENTARI_ENV`` said production — a variable the
production compose never sets, so a real install read as ``development`` and
``db reset --yes-i-am-sure`` dropped its schema. They now ask the question the
``qa`` commands ask: is ``DEBUG`` or ``TESTING`` on, or does ``INVENTARI_ENV``
name an install that exists to be thrown away?

Each command runs through its Typer app, as an operator would call it, and the
first step past the guard is replaced by a note: the runner swallows exceptions
into the exit code, so only the note tells a refusal from a step that failed.
"""

from __future__ import annotations

import contextlib

import pytest
from typer.testing import CliRunner

from app.cli import commands_db, commands_demo
from app.config import settings

runner = CliRunner()


@pytest.fixture
def reached(monkeypatch) -> list[str]:
    """The database steps the commands got to; a refusal leaves it empty."""
    notes: list[str] = []

    class _Engine:
        def connect(self):
            notes.append('db reset')
            raise RuntimeError('stop after the first database step')

    monkeypatch.setenv('DATABASE_URL', 'postgresql://nobody@nowhere/nothing')
    monkeypatch.setattr('sqlalchemy.create_engine', lambda *_a, **_k: _Engine())
    # These tests are about the guard and the first database step; the
    # migration lock is a real connection and is asserted elsewhere.
    monkeypatch.setattr(commands_demo, 'hold_migration_lock', contextlib.nullcontext)
    monkeypatch.setattr(
        'alembic.command.downgrade', lambda *_a, **_k: notes.append('db downgrade')
    )
    monkeypatch.setattr(
        commands_demo, '_clear_the_demo_inbox', lambda: notes.append('demo reset')
    )
    monkeypatch.setattr(commands_demo, '_drop_schema', lambda: notes.append('drop'))
    monkeypatch.setattr(commands_demo, '_clear_the_uploads', lambda: None)
    monkeypatch.setattr(commands_demo, '_seed_everything', lambda *_a, **_k: {})
    monkeypatch.setattr(commands_demo, '_cap_the_ai_requests', lambda: 20)
    monkeypatch.setattr(commands_demo, '_record_reset_time', lambda: None)
    # The demo's own declaration, so the only question left is the one under test.
    monkeypatch.setenv(commands_demo.DEMO_MARKER_ENV, 'true')
    return notes


def _install(monkeypatch, *, debug: bool, testing: bool, env: str | None) -> None:
    monkeypatch.setattr(settings, 'DEBUG', debug)
    monkeypatch.setattr(settings, 'TESTING', testing)
    monkeypatch.delenv('ENVIRONMENT', raising=False)
    if env is None:
        monkeypatch.delenv('INVENTARI_ENV', raising=False)
    else:
        monkeypatch.setenv('INVENTARI_ENV', env)


COMMANDS = {
    'db reset': (commands_db.db_app, ['reset', '--yes-i-am-sure']),
    'db downgrade': (commands_db.db_app, ['downgrade', 'abc123']),
    'demo reset': (
        commands_demo.demo_app,
        ['reset', '--email', 'a@example.com', '--password', 'Passw0rd!'],
    ),
}


def _run(name: str):
    app, args = COMMANDS[name]
    return runner.invoke(app, args)


@pytest.mark.parametrize('name', list(COMMANDS))
class TestAnInstallThatSaysNothingIsRefused:
    def test_debug_and_testing_off_with_no_environment_name(
        self, monkeypatch, reached, name
    ):
        """What the production compose looks like: DEBUG false, no INVENTARI_ENV."""
        _install(monkeypatch, debug=False, testing=False, env=None)

        result = _run(name)

        assert result.exit_code == 1
        assert reached == []
        # The person reading it is told what to change, so it names all three.
        output = ' '.join(result.output.split())
        assert 'DEBUG is False' in output
        assert 'TESTING is False' in output
        assert 'INVENTARI_ENV is not set' in output

    def test_production_is_refused_even_with_debug_on(self, monkeypatch, reached, name):
        _install(monkeypatch, debug=True, testing=False, env='production')

        result = _run(name)

        assert result.exit_code == 1
        assert reached == []

    def test_an_environment_name_that_is_not_listed_does_not_open_it(
        self, monkeypatch, reached, name
    ):
        _install(monkeypatch, debug=False, testing=False, env='qa-lab')

        result = _run(name)

        assert result.exit_code == 1
        assert reached == []


@pytest.mark.parametrize('name', list(COMMANDS))
@pytest.mark.parametrize(
    ('debug', 'testing', 'env'),
    [
        (True, False, None),
        (False, True, None),
        (False, False, 'development'),
        (False, False, 'staging'),
    ],
)
def test_a_disposable_install_still_runs(
    monkeypatch, reached, name, debug, testing, env
):
    """A guard that refuses everything is an outage, not a safeguard."""
    _install(monkeypatch, debug=debug, testing=testing, env=env)

    _run(name)

    assert reached[:1] == [name]


@pytest.mark.parametrize('name', list(COMMANDS))
@pytest.mark.parametrize('alias', ['development', 'staging'])
def test_the_alias_alone_opens_a_disposable_install(monkeypatch, reached, name, alias):
    """``.env.example`` calls ``ENVIRONMENT`` the same switch, so it answers too.

    Only one of the two names is allowed to decide — the refusal below reads
    the resolved value, and so must the way out.
    """
    _install(monkeypatch, debug=False, testing=False, env=None)
    monkeypatch.setenv('ENVIRONMENT', alias)

    _run(name)

    assert reached[:1] == [name]


@pytest.mark.parametrize('name', list(COMMANDS))
def test_the_alias_alone_still_says_no_to_production(monkeypatch, reached, name):
    _install(monkeypatch, debug=False, testing=False, env=None)
    monkeypatch.setenv('ENVIRONMENT', 'production')

    result = _run(name)

    assert result.exit_code == 1
    assert reached == []


def test_a_refusal_reports_the_alias_when_the_alias_is_what_was_read(
    monkeypatch, reached
):
    """Naming only INVENTARI_ENV would hide what the guard actually read."""
    _install(monkeypatch, debug=False, testing=False, env=None)
    monkeypatch.setenv('ENVIRONMENT', 'qa-lab')

    result = _run('db reset')

    assert result.exit_code == 1
    output = ' '.join(result.output.split())
    assert 'INVENTARI_ENV is not set' in output
    assert "the ENVIRONMENT alias is 'qa-lab'" in output


@pytest.mark.parametrize('name', list(COMMANDS))
def test_the_documented_name_wins_when_both_are_set(monkeypatch, reached, name):
    """Set both and INVENTARI_ENV answers — the alias never overrides it."""
    _install(monkeypatch, debug=False, testing=False, env='production')
    monkeypatch.setenv('ENVIRONMENT', 'development')

    result = _run(name)

    assert result.exit_code == 1
    assert reached == []


@pytest.mark.parametrize('name', list(COMMANDS))
def test_the_documented_name_wins_over_a_production_alias(monkeypatch, reached, name):
    _install(monkeypatch, debug=False, testing=False, env='development')
    monkeypatch.setenv('ENVIRONMENT', 'production')

    _run(name)

    assert reached[:1] == [name]


def test_the_demo_reset_service_is_allowed_by_its_own_name(monkeypatch, reached):
    """docker-compose.demo.yml runs the reset with DEBUG off and INVENTARI_ENV=demo."""
    _install(monkeypatch, debug=False, testing=False, env='demo')

    result = _run('demo reset')

    assert result.exit_code == 0, result.output
    assert reached == ['demo reset', 'drop']


@pytest.mark.parametrize('name', ['db reset', 'db downgrade'])
def test_the_demo_name_does_not_open_the_other_commands(monkeypatch, reached, name):
    """``demo`` is permission to rebuild a demo, which is the demo reset's job."""
    _install(monkeypatch, debug=False, testing=False, env='demo')

    result = _run(name)

    assert result.exit_code == 1
    assert reached == []
