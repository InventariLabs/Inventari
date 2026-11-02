"""
Unit tests for ContributionRegistry.

Tests cover:
- Registering to known points stores contributions
- get() returns correct list per point
- Registering to unknown point emits a warning log
- check_quota() returns True when no providers registered
- check_quota() returns False when any provider denies
- Multiple registrations to same point accumulate correctly
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.contributions import ContributionRegistry, QuotaProvider

# ---------------------------------------------------------------------------
# Known-point registration
# ---------------------------------------------------------------------------


def test_register_to_known_point():
    registry = ContributionRegistry()
    contribution = MagicMock()

    registry.register('scan_providers', contribution)

    assert contribution in registry.get('scan_providers')


def test_register_multiple_to_same_point():
    registry = ContributionRegistry()
    c1, c2 = MagicMock(), MagicMock()

    registry.register('quota_providers', c1)
    registry.register('quota_providers', c2)

    result = registry.get('quota_providers')
    assert c1 in result
    assert c2 in result
    assert len(result) == 2


def test_get_returns_empty_for_unregistered_point():
    registry = ContributionRegistry()
    # Known point but nothing registered
    assert registry.get('item_interceptors') == []


def test_get_returns_empty_for_completely_unknown_point():
    registry = ContributionRegistry()
    assert registry.get('nonexistent_point') == []


# ---------------------------------------------------------------------------
# Warning for unknown points
# ---------------------------------------------------------------------------


def test_warning_logged_for_unknown_point(caplog):
    registry = ContributionRegistry()
    contribution = MagicMock()

    with caplog.at_level(logging.WARNING, logger='app.core.contributions'):
        registry.register('totally_unknown_point', contribution)

    assert any('totally_unknown_point' in record.message for record in caplog.records)
    assert any(
        'unknown contribution point' in record.message.lower()
        for record in caplog.records
    )


def test_warning_not_logged_for_known_point(caplog):
    registry = ContributionRegistry()
    contribution = MagicMock()

    with caplog.at_level(logging.WARNING, logger='app.core.contributions'):
        registry.register('scan_providers', contribution)

    assert not any('unknown' in record.message.lower() for record in caplog.records)


def test_info_logged_for_experimental_point(caplog):
    registry = ContributionRegistry()
    contribution = MagicMock()

    with caplog.at_level(logging.INFO, logger='app.core.contributions'):
        registry.register('enrichment_providers', contribution)

    assert any('experimental' in record.message.lower() for record in caplog.records)
    assert any('no consumer yet' in record.message.lower() for record in caplog.records)
    # And the contribution IS still stored
    assert contribution in registry.get('enrichment_providers')


def test_unknown_point_contribution_still_stored():
    """Even for unknown points, contribution should be accessible via get()."""
    registry = ContributionRegistry()
    c = MagicMock()

    registry.register('mystery_point', c)

    assert c in registry.get('mystery_point')


def test_warning_mentions_known_points(caplog):
    registry = ContributionRegistry()

    with caplog.at_level(logging.WARNING, logger='app.core.contributions'):
        registry.register('bad_point', MagicMock())

    warning_messages = ' '.join(r.message for r in caplog.records)
    # At least some known points should be mentioned in the warning
    assert 'scan_providers' in warning_messages or 'quota_providers' in warning_messages


# ---------------------------------------------------------------------------
# check_quota()
# ---------------------------------------------------------------------------


def test_check_quota_no_providers_returns_true():
    registry = ContributionRegistry()
    result = asyncio.run(registry.check_quota('org_id', 'items', db=MagicMock()))
    assert result is True


@pytest.mark.asyncio
async def test_check_quota_all_allow_returns_true():
    registry = ContributionRegistry()
    provider = MagicMock(spec=QuotaProvider)
    provider.check_organization_limit = AsyncMock(return_value=True)
    registry.register('quota_providers', provider)

    result = await registry.check_quota('org_id', 'items', db=MagicMock())
    assert result is True


@pytest.mark.asyncio
async def test_check_quota_one_deny_returns_false():
    registry = ContributionRegistry()

    allow_provider = MagicMock(spec=QuotaProvider)
    allow_provider.check_organization_limit = AsyncMock(return_value=True)

    deny_provider = MagicMock(spec=QuotaProvider)
    deny_provider.check_organization_limit = AsyncMock(return_value=False)

    registry.register('quota_providers', allow_provider)
    registry.register('quota_providers', deny_provider)

    result = await registry.check_quota('org_id', 'items', db=MagicMock())
    assert result is False


@pytest.mark.asyncio
async def test_check_quota_passes_correct_arguments():
    registry = ContributionRegistry()
    provider = MagicMock(spec=QuotaProvider)
    provider.check_organization_limit = AsyncMock(return_value=True)
    registry.register('quota_providers', provider)

    mock_db = MagicMock()
    await registry.check_quota('my_org', 'storage_locations', db=mock_db)

    provider.check_organization_limit.assert_called_once_with(
        'my_org', 'storage_locations', mock_db
    )


# ---------------------------------------------------------------------------
# KNOWN_POINTS coverage
# ---------------------------------------------------------------------------


def test_all_known_points_are_accessible():
    registry = ContributionRegistry()
    for point in ContributionRegistry.KNOWN_POINTS:
        # Each known point should return an empty list (not raise)
        result = registry.get(point)
        assert isinstance(result, list)
