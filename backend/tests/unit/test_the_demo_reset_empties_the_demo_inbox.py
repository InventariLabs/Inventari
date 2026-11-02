"""The demo sends no real email, so the inbox is the only copy — and it expires.

Every message a visitor triggers on the demo lands in the Mailpit inbox that
sits beside it, addresses typed in by strangers included. The nightly rebuild
is what bounds that: the inbox is emptied with the rest of the instance, so an
address typed yesterday is not still on display today.

Two properties, tested apart because they fail apart:

* the reset asks Mailpit to delete every message, and
* a Mailpit that is slow, down or refusing does not take the database rebuild
  with it — the rebuild is the part the demo cannot run without.

Nothing here reaches the network or the database: both are monkeypatched, so
the tests pin the decision rather than the environment.
"""

from __future__ import annotations

import httpx
import pytest

from app.cli import commands_demo


class _FakeResponse:
    def __init__(self) -> None:
        self.raised = False

    def raise_for_status(self) -> None:
        self.raised = True


def _arrange_reset(monkeypatch, order: list[str] | None = None) -> list[str]:
    """Replace every step but the one under test with a note in ``order``."""
    order = order if order is not None else []

    monkeypatch.setattr(commands_demo, 'guard_demo_instance', lambda: None)
    monkeypatch.setattr(commands_demo, '_drop_schema', lambda: order.append('drop'))
    monkeypatch.setattr(commands_demo, '_clear_the_uploads', lambda: None)
    monkeypatch.setattr(
        commands_demo,
        '_seed_everything',
        lambda *a, **k: (order.append('seed'), {'items_total': 3})[1],
    )
    monkeypatch.setattr(
        commands_demo, '_record_reset_time', lambda: order.append('record')
    )
    return order


class TestTheInboxIsEmptied:
    def test_the_reset_asks_mailpit_to_delete_every_message(self, monkeypatch):
        monkeypatch.setenv(
            commands_demo.DEMO_INBOX_API_URL_ENV, 'http://mailpit:8025/mailpit'
        )
        calls: list[tuple[str, str]] = []

        def _delete(url: str, **kwargs) -> _FakeResponse:
            calls.append((url, kwargs.get('timeout')))
            response = _FakeResponse()
            response.raise_for_status()
            return response

        monkeypatch.setattr(httpx, 'delete', _delete)
        order = _arrange_reset(monkeypatch)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert calls == [
            (
                'http://mailpit:8025/mailpit/api/v1/messages',
                commands_demo.DEMO_INBOX_TIMEOUT_SECONDS,
            )
        ]
        assert order == ['drop', 'seed', 'record']

    def test_the_inbox_is_emptied_before_the_database_is_dropped(self, monkeypatch):
        """An address must not survive a rebuild that then fails halfway.

        Clearing first means the one thing the reset cannot rebuild — a
        stranger's address in a public inbox — is gone even when the rest of
        the run collapses.
        """
        monkeypatch.setenv(
            commands_demo.DEMO_INBOX_API_URL_ENV, 'http://mailpit:8025/mailpit'
        )
        order = _arrange_reset(monkeypatch)

        def _delete(url: str, **kwargs) -> _FakeResponse:
            order.append('inbox')
            response = _FakeResponse()
            response.raise_for_status()
            return response

        monkeypatch.setattr(httpx, 'delete', _delete)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert order == ['inbox', 'drop', 'seed', 'record']

    def test_a_trailing_slash_on_the_url_is_not_doubled(self, monkeypatch):
        monkeypatch.setenv(
            commands_demo.DEMO_INBOX_API_URL_ENV, 'http://mailpit:8025/mailpit/'
        )
        urls: list[str] = []

        def _delete(url: str, **kwargs) -> _FakeResponse:
            urls.append(url)
            response = _FakeResponse()
            response.raise_for_status()
            return response

        monkeypatch.setattr(httpx, 'delete', _delete)
        _arrange_reset(monkeypatch)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert urls == ['http://mailpit:8025/mailpit/api/v1/messages']

    def test_an_unset_inbox_only_means_there_is_nothing_to_empty(self, monkeypatch):
        """``make demo-reset`` on a developer's machine has no Mailpit beside it."""
        monkeypatch.delenv(commands_demo.DEMO_INBOX_API_URL_ENV, raising=False)

        def _delete(url: str, **kwargs) -> _FakeResponse:
            pytest.fail('a reset with no inbox configured called Mailpit')

        monkeypatch.setattr(httpx, 'delete', _delete)
        order = _arrange_reset(monkeypatch)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert order == ['drop', 'seed', 'record']


class TestAMailpitThatRefusesDoesNotStopTheRebuild:
    """The rebuild is the part the demo cannot run without; the inbox is not.

    Mailpit is one small container on the same host, and it can be restarting,
    renamed or simply not there. A reset that aborts before the drop because
    the inbox refused leaves the instance with yesterday's data — the failure
    is now the visitor's, which is the worse trade.
    """

    @pytest.mark.parametrize(
        'failure',
        [
            httpx.ConnectError('connection refused'),
            httpx.ReadTimeout('too slow'),
            httpx.HTTPStatusError(
                'mailpit said no',
                request=httpx.Request(
                    'DELETE', 'http://mailpit:8025/mailpit/api/v1/messages'
                ),
                response=httpx.Response(500),
            ),
        ],
    )
    def test_the_other_steps_still_run(self, monkeypatch, failure):
        monkeypatch.setenv(
            commands_demo.DEMO_INBOX_API_URL_ENV, 'http://mailpit:8025/mailpit'
        )

        def _delete(url: str, **kwargs):
            raise failure

        monkeypatch.setattr(httpx, 'delete', _delete)
        order = _arrange_reset(monkeypatch)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert order == ['drop', 'seed', 'record'], (
            f'{type(failure).__name__} from Mailpit stopped the database rebuild'
        )

    def test_a_mailpit_that_answers_an_error_is_treated_like_one_that_hung(
        self, monkeypatch
    ):
        monkeypatch.setenv(
            commands_demo.DEMO_INBOX_API_URL_ENV, 'http://mailpit:8025/mailpit'
        )

        class _Broken(_FakeResponse):
            def raise_for_status(self) -> None:
                raise httpx.HTTPStatusError(
                    '500',
                    request=httpx.Request('DELETE', 'http://x/api/v1/messages'),
                    response=httpx.Response(500),
                )

        monkeypatch.setattr(httpx, 'delete', lambda url, **kwargs: _Broken())
        order = _arrange_reset(monkeypatch)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert order == ['drop', 'seed', 'record']
