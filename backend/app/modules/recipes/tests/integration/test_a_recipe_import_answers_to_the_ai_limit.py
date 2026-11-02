"""Importing a recipe spends the organization's AI budget, so the budget gates it.

The URL import pipeline books every provider call against the same monthly
ceiling as vision and the connection test, but until now nothing asked that
ceiling first — and the one check that existed was doubly wrong: it counted a
single action bucket against a hardcoded ``50``, and its "safe" wrapper caught
the very refusal it raised (an ``HTTPException`` is an ``Exception``), so an
overage was logged as "non-blocking" and the import continued.

These tests pin both halves of the gate on both import doors: over the limit
the scraping stage is never reached and the refusal carries the counter's
numbers and period, under it the import still runs, and an outage of the
counter itself refuses nothing.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from httpx import Response
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.public_api import core_api
from app.models.ai_usage_log import AIUsageLog
from app.models.organization import Organization
from app.modules.recipes.ingredient_parser_basic import ParsedIngredient
from app.modules.recipes.ingredient_parser_llm import IngredientParseOutcome
from app.modules.recipes.scrapers.base import ScrapedRecipe

_IMPORT_DOORS = (
    '/api/v1/recipes/import/preview',
    '/api/v1/recipes/import',
)

# A public IP literal on purpose: the URL guard passes it without a DNS
# lookup, so the only network this test could ever reach is the mocked one.
_URL = 'http://93.184.216.34/recipe'


def _cap_requests(db: Session, org: Organization, monthly_requests: int) -> None:
    org.settings = {'limits': {'ai_requests_monthly': monthly_requests}}
    db.commit()


def _spend(db: Session, org: Organization, calls: int) -> None:
    """Book *calls* billable AI rows for the org, as the ledger would."""
    for _ in range(calls):
        db.add(
            AIUsageLog(
                organization_id=org.id,
                model_name='some/model',
                provider='openrouter',
                action_type='recipe_import',
            )
        )
    db.commit()


def _this_month() -> tuple[str, str]:
    """The period the counter counts over, in the shape the refusal reports it."""
    now = datetime.now(UTC)
    _, last_day = monthrange(now.year, now.month)
    return (
        f'{now.year:04d}-{now.month:02d}-01',
        f'{now.year:04d}-{now.month:02d}-{last_day:02d}',
    )


def _scraped() -> ScrapedRecipe:
    return ScrapedRecipe(
        title='Imported Recipe',
        ingredients=['500 g flour'],
        instructions='Mix.',
        servings=2,
        image_url=None,
        prep_time_minutes=15,
        translated=True,
        source_language=None,
    )


def _parsed() -> ParsedIngredient:
    return ParsedIngredient(
        name='flour',
        group_name='flour',
        quantity=Decimal('500'),
        unit_symbol='g',
        original_text='500 g flour',
        original_quantity=None,
        original_unit_text=None,
        unit_display=None,
    )


@contextmanager
def _pipeline_stages() -> Iterator[AsyncMock]:
    """Scraping and parsing replaced so a test can watch what the gate let through.

    The parser patch covers both doors: ``parse_ingredients_llm_async`` (the
    persist path) delegates to ``parse_ingredients_llm_with_status_async``
    (the preview path) through the module global resolved at call time.
    """
    with (
        patch(
            'app.modules.recipes._import_url_pipeline._scrape_recipe',
            new=AsyncMock(return_value=_scraped()),
        ) as scraper,
        patch(
            'app.modules.recipes.ingredient_parser_llm.'
            'parse_ingredients_llm_with_status_async',
            new=AsyncMock(return_value=IngredientParseOutcome(items=[_parsed()])),
        ),
    ):
        yield scraper


def _import(door: str, client: TestClient, auth_headers: dict[str, str]) -> Response:
    response: Response = client.post(
        door,
        json={'format': 'url', 'url': _URL},
        headers=auth_headers,
    )
    return response


@pytest.mark.integration
class TestOverTheLimit:
    """The one import that must not happen: the one there is no budget for."""

    @pytest.mark.parametrize('door', _IMPORT_DOORS)
    def test_the_refusal_carries_the_numbers_and_the_scraper_is_never_reached(
        self,
        door: str,
        db_session: Session,
        test_household: Organization,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        _cap_requests(db_session, test_household, 2)
        _spend(db_session, test_household, 3)

        with _pipeline_stages() as scraper:
            response = _import(door, client, auth_headers)

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'AI_USAGE_LIMIT_EXCEEDED'
        assert detail['limit_key'] == 'ai_requests_monthly'
        assert detail['used'] == 3
        assert detail['limit'] == 2

        period_start, period_end = _this_month()
        assert detail['period_start'] == period_start
        assert detail['period_end'] == period_end

        # The sentence a toast shows is the catalogue's, and the numbers are in
        # it too — a reader who never opens a network tab learns which budget
        # ran out, how much of it, and for which period.
        assert '3' in detail['message']
        assert '2' in detail['message']
        assert period_start in detail['message']

        # The refusal arrives before the external fetch, so a refused import
        # does not burn a Jina request on the way to the answer.
        scraper.assert_not_awaited()


@pytest.mark.integration
class TestUnderTheLimit:
    @pytest.mark.parametrize(
        ('door', 'expected'),
        [
            ('/api/v1/recipes/import/preview', status.HTTP_200_OK),
            ('/api/v1/recipes/import', status.HTTP_201_CREATED),
        ],
    )
    def test_the_import_still_runs(
        self,
        door: str,
        expected: int,
        db_session: Session,
        test_household: Organization,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        _cap_requests(db_session, test_household, 5)
        _spend(db_session, test_household, 4)

        with _pipeline_stages() as scraper:
            response = _import(door, client, auth_headers)

        assert response.status_code == expected, response.text
        scraper.assert_awaited_once()


@pytest.mark.integration
class TestACounterOutageIsNotAnAnswer:
    """A counter that cannot be read refuses nothing.

    The gate is best-effort by design: an organization whose usage counter is
    down must still be able to import a recipe, or a bookkeeping outage
    becomes a feature nobody can use.
    """

    @pytest.mark.parametrize(
        ('door', 'expected'),
        [
            ('/api/v1/recipes/import/preview', status.HTTP_200_OK),
            ('/api/v1/recipes/import', status.HTTP_201_CREATED),
        ],
    )
    def test_the_import_runs_when_the_counter_is_down(
        self,
        door: str,
        expected: int,
        db_session: Session,
        test_household: Organization,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        with (
            patch.object(
                core_api.ai_usage,
                'check_limit_async',
                new=AsyncMock(side_effect=RuntimeError('counter is down')),
            ),
            _pipeline_stages() as scraper,
        ):
            response = _import(door, client, auth_headers)

        assert response.status_code == expected, response.text
        scraper.assert_awaited_once()
