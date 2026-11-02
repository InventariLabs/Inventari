"""The QA fixture makes administrators with a password printed in this repository.

So the question is where it agrees to run, and the answer has to fail closed.
It used to refuse only when ``INVENTARI_ENV`` said production — a variable the
production compose never sets, so a real install read as ``development`` and
the command ran. The settings that production does set are the ones to ask:
``DEBUG`` is off there, and so is ``TESTING``.

Three answers are tested apart because each is a different mistake:

* an install with ``DEBUG`` and ``TESTING`` both off, and no environment name,
  is refused — and the refusal names what it read,
* a development or test install, or one that says it is staging, still runs, and
* an install that says it is production is refused whatever else is on.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from app.cli import commands_qa
from app.config import settings

runner = CliRunner()


@pytest.fixture
def provisioned(monkeypatch) -> list[str]:
    """Names of the steps past the guard that ran; a refusal leaves it empty.

    The runner swallows exceptions into the exit code, so a step that raised
    would look like a refusal — recording the call is what tells them apart.
    """
    reached: list[str] = []

    def _step(name: str):
        def _record(*_args, **_kwargs):
            reached.append(name)

        return _record

    monkeypatch.setattr(commands_qa, '_provision_variants', _step('provision'))
    monkeypatch.setattr(commands_qa, '_reset', _step('reset'))
    return reached


def _install(monkeypatch, *, debug: bool, testing: bool, env: str | None) -> None:
    monkeypatch.setattr(settings, 'DEBUG', debug)
    monkeypatch.setattr(settings, 'TESTING', testing)
    if env is None:
        monkeypatch.delenv('INVENTARI_ENV', raising=False)
    else:
        monkeypatch.setenv('INVENTARI_ENV', env)


class TestAnInstallThatIsNotForDevelopmentIsRefused:
    @pytest.mark.parametrize('command', [['fixture'], ['reset', 'one', '--yes']])
    def test_debug_and_testing_off_with_no_environment_name(
        self, monkeypatch, provisioned, command
    ):
        """What the production compose looks like: DEBUG false, no INVENTARI_ENV."""
        _install(monkeypatch, debug=False, testing=False, env=None)

        result = runner.invoke(commands_qa.qa_app, command)

        assert result.exit_code == 1
        assert provisioned == []

    def test_the_refusal_says_what_it_read(self, monkeypatch, provisioned):
        _install(monkeypatch, debug=False, testing=False, env=None)

        result = runner.invoke(commands_qa.qa_app, ['fixture'])

        assert 'DEBUG' in result.output
        assert 'TESTING' in result.output
        assert 'INVENTARI_ENV' in result.output
        assert provisioned == []

    def test_an_environment_name_that_is_not_listed_does_not_open_it(
        self, monkeypatch, provisioned
    ):
        _install(monkeypatch, debug=False, testing=False, env='qa-lab')

        result = runner.invoke(commands_qa.qa_app, ['fixture'])

        assert result.exit_code == 1
        assert provisioned == []

    def test_production_is_refused_even_with_debug_on(self, monkeypatch, provisioned):
        _install(monkeypatch, debug=True, testing=False, env='production')

        result = runner.invoke(commands_qa.qa_app, ['fixture'])

        assert result.exit_code == 1
        assert provisioned == []


class TestADevelopmentInstallStillRuns:
    @pytest.mark.parametrize(
        ('debug', 'testing', 'env'),
        [
            (True, False, None),
            (False, True, None),
            (False, False, 'staging'),
            (False, False, 'development'),
        ],
    )
    def test_the_guard_lets_it_through(self, monkeypatch, debug, testing, env):
        _install(monkeypatch, debug=debug, testing=testing, env=env)

        commands_qa._guard_environment()
