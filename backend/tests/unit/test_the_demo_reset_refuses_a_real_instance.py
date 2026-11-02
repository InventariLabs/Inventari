"""``demo reset`` drops the schema, so the question is where it agrees to run.

Every other destructive command in this CLI is protected by a person: ``db
reset`` asks the operator to type the database name. This one is meant to be
called by a timer at three in the morning, and a timer cannot be asked
anything — so the protection has to be a property of the instance rather than
an answer from whoever is watching.

Two conditions, and the second is the one that matters: the instance must not
be production, *and* it must have declared itself a demo. The first is the
same check the rest of the CLI makes. The second exists because the first is
not enough — a staging copy of a customer's database is not production and has
nothing to do with a demo, and inferring "this looks like a demo" from a
database name is how a reset finds the wrong machine.
"""

from __future__ import annotations

import pytest

from app.cli.commands_demo import (
    DEMO_ENVIRONMENT,
    DEMO_MARKER_ENV,
    DemoGuardError,
    guard_demo_instance,
)
from app.config import settings


class TestTheGuardRefuses:
    def test_an_instance_that_has_not_declared_itself_is_refused(self, monkeypatch):
        monkeypatch.delenv(DEMO_MARKER_ENV, raising=False)
        with pytest.raises(DemoGuardError) as excinfo:
            guard_demo_instance()
        # The message has to name the variable, because the person reading it
        # is being told to go and set something.
        assert DEMO_MARKER_ENV in str(excinfo.value)

    @pytest.mark.parametrize('value', ['', ' ', 'false', 'no', '0', 'maybe'])
    def test_a_marker_that_does_not_say_yes_is_not_a_yes(self, monkeypatch, value):
        monkeypatch.setenv(DEMO_MARKER_ENV, value)
        with pytest.raises(DemoGuardError):
            guard_demo_instance()

    def test_production_is_refused_even_when_the_marker_says_demo(self, monkeypatch):
        """The marker is permission to wipe a demo, not permission to wipe.

        Both conditions are required, and this is the one that would hurt: an
        instance carrying a stale INVENTARI_DEMO from a copied env file while
        serving real users.
        """
        monkeypatch.setenv(DEMO_MARKER_ENV, 'true')
        monkeypatch.setenv('INVENTARI_ENV', 'production')
        with pytest.raises(DemoGuardError) as excinfo:
            guard_demo_instance()
        assert 'production' in str(excinfo.value).lower()


class TestTheGuardAllows:
    @pytest.mark.parametrize('value', ['true', 'TRUE', 'True', 'yes', '1'])
    def test_a_declared_demo_outside_production_may_run(self, monkeypatch, value):
        """A guard that refuses everything is not a guard, it is an outage.

        Without this case the tests above would pass on a guard hard-coded to
        raise, and nobody would find out until the demo went a month stale.
        """
        monkeypatch.setenv(DEMO_MARKER_ENV, value)
        monkeypatch.setattr(settings, 'DEBUG', False)
        monkeypatch.setattr(settings, 'TESTING', False)
        monkeypatch.setenv('INVENTARI_ENV', DEMO_ENVIRONMENT)
        guard_demo_instance()
