"""The QA fixture's refusals and the helpers it provisions through.

The heavy and the destructive pieces are faked, so what this file holds is the
refusals (unknown variants, a password below the policy) and that the fixture
provisions through the shared helper, seeding volume only where asked.
"""

from __future__ import annotations

import pytest
import typer

from app.cli import commands_qa

pytestmark = pytest.mark.integration


class TestTheSharedHelpers:
    def test_all_names_the_three_variants(self):
        assert commands_qa._wanted_variants('all') == ['empty', 'one', 'many']

    def test_an_unknown_variant_stops_the_command(self):
        with pytest.raises(typer.Exit):
            commands_qa._wanted_variants('nope')

    def test_a_password_below_the_policy_stops_the_command(self):
        with pytest.raises(typer.Exit):
            commands_qa._validate_password('short')

    def test_provision_variants_seeds_volume_only_for_many(self, monkeypatch):
        calls: list[tuple[str, object]] = []

        async def fake_provision(name, password, profile):
            calls.append(('provision', name))
            return {
                'organization': f'QA {name.title()}',
                'organization_id': f'org-{name}',
                'admin': f'qa-{name}@example.com',
                'admin_id': f'admin-{name}',
                'seeded': {},
            }

        monkeypatch.setattr(commands_qa, '_provision', fake_provision)
        monkeypatch.setattr(
            commands_qa,
            '_seed_many',
            lambda org, admin, items: calls.append(('seed_many', items)) or {'item': 1},
        )

        commands_qa._provision_variants(
            ['one', 'many'], 'QaFixture123', 'equipment_wms', 7
        )

        assert calls == [
            ('provision', 'one'),
            ('provision', 'many'),
            ('seed_many', 7),
        ]

    def test_a_failing_provision_stops_the_command(self, monkeypatch):
        async def explode(name, password, profile):
            raise RuntimeError('boom')

        monkeypatch.setattr(commands_qa, '_provision', explode)

        with pytest.raises(SystemExit):
            commands_qa._provision_variants(['one'], 'QaFixture123', 'equipment_wms', 0)

    def test_the_fixture_provisions_through_the_shared_helper(self, monkeypatch):
        calls: list[list[str]] = []
        monkeypatch.setattr(
            commands_qa,
            '_provision_variants',
            lambda wanted, password, profile, items: calls.append(wanted),
        )

        commands_qa.fixture(
            variant='one',
            profile='equipment_wms',
            items=0,
            password='QaFixture123',
            reset=False,
            yes=True,
        )

        assert calls == [['one']]
