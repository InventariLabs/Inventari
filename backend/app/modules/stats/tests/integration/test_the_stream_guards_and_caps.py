"""The overview stream refuses cleanly, caps its clients and logs an outage once."""

import logging
import uuid

import pytest
from starlette.testclient import TestClient

import app.database
from app.core.contracts import UserContextDTO
from app.core.exceptions import AppException
from app.modules.stats import router as stats_router
from app.modules.stats.router import stream_overview

pytestmark = pytest.mark.unit


def _context() -> UserContextDTO:
    return UserContextDTO(id=uuid.uuid4(), organization_id=uuid.uuid4(), role='admin')


@pytest.mark.integration
def test_stream_limit_refusal_speaks_polish(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        stats_router,
        '_open_overview_streams',
        stats_router.MAX_CONCURRENT_OVERVIEW_STREAMS,
    )
    response = client.get(
        '/api/v1/stats/overview/stream',
        headers={**auth_headers, 'Accept-Language': 'pl'},
    )
    assert response.status_code == 429
    assert response.json()['detail']['message'] == (
        'Zbyt wiele otwartych strumieni statystyk. Spróbuj ponownie za 10 sekund.'
    )


async def test_missing_session_factory_is_refused_with_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.database, 'AsyncSessionLocal', None)
    with pytest.raises(AppException) as refused:
        await stream_overview(current_user=_context())
    assert refused.value.status_code == 503


async def test_streams_beyond_the_cap_get_429_and_a_closed_one_frees_a_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.database, 'AsyncSessionLocal', lambda: None)
    monkeypatch.setattr(stats_router, 'MAX_CONCURRENT_OVERVIEW_STREAMS', 2)
    monkeypatch.setattr(stats_router, '_open_overview_streams', 0)

    first = await stream_overview(current_user=_context())
    await stream_overview(current_user=_context())
    with pytest.raises(AppException) as refused:
        await stream_overview(current_user=_context())
    assert refused.value.status_code == 429

    assert first.background is not None
    await first.background()
    await stream_overview(current_user=_context())


def test_an_outage_logs_one_traceback_whatever_the_clients_and_ticks(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(stats_router, '_tick_outage_suppressed', {})
    caplog.set_level(logging.INFO)
    org = uuid.uuid4()
    for _ in range(50 * 6):  # 50 clients, one minute of ticks
        try:
            raise RuntimeError('db down')
        except RuntimeError:
            stats_router._record_tick_failure(org)
    failures = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(failures) == 1

    stats_router._record_tick_success(org)
    assert 'recovered; 299 failures suppressed' in caplog.text
    stats_router._record_tick_success(org)
    assert caplog.text.count('recovered') == 1


def test_another_orgs_success_does_not_rearm_a_failing_orgs_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(stats_router, '_tick_outage_suppressed', {})
    caplog.set_level(logging.INFO)
    failing, cached = uuid.uuid4(), uuid.uuid4()
    for _ in range(6):  # the cached org succeeds between every failure
        try:
            raise RuntimeError('db down')
        except RuntimeError:
            stats_router._record_tick_failure(failing)
        stats_router._record_tick_success(cached)
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1
