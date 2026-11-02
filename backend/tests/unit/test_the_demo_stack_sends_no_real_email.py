"""The demo stack must not be able to mail the outside world.

A public demo publishes its administrator login, so whatever the instance can
send, a visitor can send: a purchase order to an address they type, an
invitation whose text carries the organization name they chose. On a real
relay that puts the sending domain on blocklists within days — so the demo
profile aims the *system* SMTP settings at a Mailpit container beside it, and
overwrites whatever ``.env`` says rather than defaulting it. The values are
literals in ``docker-compose.demo.yml`` for exactly that reason: with a
``${SMTP_HOST:-...}`` fallback an operator's real relay would win on the
deployments where the variable is set, which is all of the real ones.

None of this starts Docker. The files are parsed as text, because the failure
worth catching is a later edit quietly dropping one of these keys — the demo
then inherits the operator's relay and nothing on screen changes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

#: Both containers run the application and both could send mail; neither may
#: reach anything but Mailpit.
_MAIL_SENDING_SERVICES = ('backend', 'demo-reset')


def _demo_compose() -> dict[str, Any]:
    text = (_REPO_ROOT / 'docker-compose.demo.yml').read_text(encoding='utf-8')
    return yaml.safe_load(text)['services']


class TestTheSystemSmtpPointsInside:
    def test_every_mail_sending_process_aims_at_mailpit(self) -> None:
        services = _demo_compose()

        for name in _MAIL_SENDING_SERVICES:
            environment = services[name]['environment']
            assert environment['SMTP_HOST'] == 'mailpit', (
                f'{name} would inherit the SMTP host from .env'
            )
            assert str(environment['SMTP_PORT']) == '1025'
            assert environment['SMTP_ENCRYPTION'] == 'none'

    def test_the_values_are_literals_not_fallbacks_to_dot_env(self) -> None:
        """A ``${SMTP_HOST:-...}`` default is the hole this test exists for.

        The demo file is layered last, so a literal wins over the base file —
        but a fallback expression would resolve from ``.env``, which is where
        the operator's real relay lives.
        """
        services = _demo_compose()

        for name in _MAIL_SENDING_SERVICES:
            environment = services[name]['environment']
            for key in (
                'SMTP_HOST',
                'SMTP_PORT',
                'SMTP_USER',
                'SMTP_PASSWORD',
                'SMTP_ENCRYPTION',
            ):
                assert '${' not in str(environment[key]), (
                    f'{name}.{key} resolves from .env instead of being pinned '
                    f'to the demo inbox'
                )


class TestTheDemoDeclaresItself:
    def test_every_mail_sending_process_knows_it_serves_a_demo(self) -> None:
        """The marker is what stops the organization SMTP settings from being
        saved or used: without it the backend sees an ordinary installation
        whose visitors are its administrators. The reset service already
        carried the marker for its own guard; the application needs it too.
        """
        services = _demo_compose()

        for name in _MAIL_SENDING_SERVICES:
            assert services[name]['environment']['INVENTARI_DEMO'] == 'true', (
                f'{name} would not know it serves a demo'
            )


class TestTheCatcher:
    def test_mailpit_rides_in_the_demo_profile_with_auth_for_plaintext(
        self,
    ) -> None:
        """The application logs in unconditionally, so Mailpit must accept it.

        Without these two flags Mailpit advertises no AUTH mechanism over
        plaintext and every send fails — the demo would silently mail nothing,
        which is worse than mailing Mailpit.
        """
        mailpit = _demo_compose()['mailpit']

        assert mailpit['profiles'] == ['demo']
        assert '--smtp-auth-accept-any' in mailpit['command']
        assert '--smtp-auth-allow-insecure' in mailpit['command']

    def test_the_ui_is_served_under_the_prefix_the_visitor_opens(self) -> None:
        command = _demo_compose()['mailpit']['command']
        webroot = command[command.index('--webroot') + 1]

        assert webroot == '/mailpit'


class TestTheResetEmptiesIt:
    def test_the_reset_is_told_where_the_inbox_api_is(self) -> None:
        environment = _demo_compose()['demo-reset']['environment']

        assert environment['DEMO_INBOX_API_URL'].startswith('http://mailpit:')


class TestTheSeedingProcessSeesTheServersModel:
    """The rebuild enables image recognition where the server's model serves it.

    That decision reads ``LLM_*`` in the process that seeds — ``demo-reset``,
    which has no ``env_file:``. A test that patches the deciding function
    cannot see that the container never receives its input.
    """

    #: Provider, endpoint and key travel together: the application refuses to
    #: start on a key whose provider has no endpoint of its own.
    _MODEL = (
        'LLM_API_KEY',
        'OPENROUTER_API_KEY',
        'LLM_PROVIDER',
        'LLM_API_BASE_URL',
        'LLM_CAPABILITIES',
    )

    def test_the_reset_service_receives_the_model_the_backend_gets(self) -> None:
        services = _demo_compose()
        prod = yaml.safe_load(
            (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')
        )['services']['backend']['environment']

        reset = services['demo-reset']['environment']
        for key in self._MODEL:
            assert key in reset, f'demo-reset would see no {key}'
            assert reset[key] == prod[key], (
                f'demo-reset.{key} differs from the backend ({reset[key]!r} vs '
                f'{prod[key]!r}): the two would disagree on the model'
            )


class TestTheVisitorCanReachIt:
    def test_the_demo_caddyfile_imports_the_production_one(self) -> None:
        """A copy would drift; an import cannot."""
        text = (_REPO_ROOT / 'Caddyfile.demo').read_text(encoding='utf-8')

        assert 'import /etc/caddy/Caddyfile' in text
        assert 'reverse_proxy mailpit:8025' in text

    def test_caddy_is_pointed_at_the_demo_configuration(self) -> None:
        command = _demo_compose()['caddy']['command']

        assert '/etc/caddy/Caddyfile.demo' in command

    def test_the_sign_in_screen_is_given_the_public_inbox_url(self) -> None:
        environment = _demo_compose()['backend']['environment']

        assert '${DOMAIN' in environment['DEMO_INBOX_URL']
        assert environment['DEMO_INBOX_URL'].endswith('/mailpit/')
