"""
Integration tests for EmailService.

Tests cover:
- Sending basic HTML emails
- Custom SMTP configuration
- Missing SMTP settings handling
- SMTP connection errors
- Registration link emails in multiple languages
"""

import smtplib
from unittest.mock import MagicMock

import pytest

from app.services.email_service import SMTP_TIMEOUT_SECONDS, EmailService


@pytest.fixture(autouse=True)
def no_stored_encryption(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing is stored, so the port decides — which is what is under test.

    Every test here states its own host, port and credentials but inherited
    this one field. On an installation that stores a transport choice the
    port stops voting, and the cases below would assert against a decision
    they never made.
    """
    monkeypatch.setattr('app.services.email_service.settings.SMTP_ENCRYPTION', None)


@pytest.mark.integration
class TestEmailService:
    """EmailService integration tests."""

    def test_send_email_basic_no_config(self, monkeypatch):
        """Test sending email using system SMTP settings."""
        # Mock smtplib.SMTP
        mock_smtp = MagicMock()
        mock_smtp_class = MagicMock(return_value=mock_smtp)
        monkeypatch.setattr('smtplib.SMTP', mock_smtp_class)

        # Mock settings
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_HOST', 'smtp.gmail.com'
        )
        monkeypatch.setattr('app.services.email_service.settings.SMTP_PORT', 587)
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_USER', 'user@gmail.com'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_PASSWORD', 'password'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.EMAILS_FROM_EMAIL', 'sender@gmail.com'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.EMAILS_FROM_NAME', 'Inventari'
        )

        result = EmailService.send_email(
            to_email='recipient@test.com',
            subject='Test Subject',
            html_content='<p>Test content</p>',
        )

        assert result is True
        # Verify SMTP.SMTP was called with correct host and port
        mock_smtp_class.assert_called_once_with(
            'smtp.gmail.com', 587, timeout=SMTP_TIMEOUT_SECONDS
        )
        # Verify starttls was called (port 587)
        mock_smtp.__enter__.return_value.starttls.assert_called_once()

    def test_send_email_with_custom_smtp_config(self, monkeypatch):
        """Test sending email with custom SMTP configuration."""
        mock_smtp = MagicMock()
        mock_smtp_class = MagicMock(return_value=mock_smtp)
        monkeypatch.setattr('smtplib.SMTP_SSL', mock_smtp_class)

        custom_config = {
            'host': 'smtp.custom.com',
            'port': 465,
            'user': 'custom_user',
            'password': 'custom_pass',
            'from_email': 'custom@custom.com',
            'from_name': 'Custom',
        }

        result = EmailService.send_email(
            to_email='recipient@test.com',
            subject='Custom Test',
            html_content='<p>Custom content</p>',
            smtp_config=custom_config,
        )

        assert result is True
        # Verify custom config was used
        mock_smtp_class.assert_called_once_with(
            'smtp.custom.com', 465, timeout=SMTP_TIMEOUT_SECONDS
        )
        mock_smtp.__enter__.return_value.login.assert_called_once_with(
            'custom_user', 'custom_pass'
        )

    def test_send_email_port_465_uses_implicit_tls(self, monkeypatch):
        """Port 465 is implicit TLS: no STARTTLS, because the socket is already
        encrypted. It used to mean plain SMTP with no STARTTLS either — login
        and message in the clear."""
        mock_smtp = MagicMock()
        mock_smtp_class = MagicMock(return_value=mock_smtp)
        monkeypatch.setattr('smtplib.SMTP_SSL', mock_smtp_class)
        monkeypatch.setattr(
            'smtplib.SMTP', MagicMock(side_effect=AssertionError('sent in the clear'))
        )

        config = {
            'host': 'smtp.example.com',
            'port': 465,
            'user': 'user',
            'password': 'pass',
            'from_email': 'from@example.com',
            'from_name': 'Example',
        }

        result = EmailService.send_email(
            to_email='recipient@test.com',
            subject='Test',
            html_content='<p>Test</p>',
            smtp_config=config,
        )

        assert result is True
        # starttls should NOT be called for port 465
        mock_smtp.__enter__.return_value.starttls.assert_not_called()

    def test_send_email_missing_smtp_settings(self, monkeypatch):
        """Test handling when SMTP settings are not configured."""
        # Mock settings with None/empty values
        monkeypatch.setattr('app.services.email_service.settings.SMTP_HOST', None)
        monkeypatch.setattr('app.services.email_service.settings.SMTP_PORT', 587)
        monkeypatch.setattr('app.services.email_service.settings.SMTP_USER', None)
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_PASSWORD', 'password'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.EMAILS_FROM_EMAIL', 'from@test.com'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.EMAILS_FROM_NAME', 'Test'
        )

        result = EmailService.send_email(
            to_email='recipient@test.com',
            subject='Test',
            html_content='<p>Test</p>',
        )

        assert result is False

    def test_a_relay_without_a_login_sends_without_logging_in(self, monkeypatch):
        """Username and password both empty is a valid, unauthenticated relay."""
        mock_smtp = MagicMock()
        monkeypatch.setattr('smtplib.SMTP', MagicMock(return_value=mock_smtp))
        monkeypatch.setattr('app.services.email_service.settings.SMTP_HOST', None)
        # The installation's own credentials must not follow the typed host.
        monkeypatch.setattr('app.services.email_service.settings.SMTP_USER', 'sys')
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_PASSWORD', 'system-secret'
        )

        config = {'host': 'relay.internal', 'port': 25, 'encryption': 'none'}
        assert EmailService.is_configured(config) is True
        assert (
            EmailService.send_email(
                'recipient@test.com', 'Test', '<p>Test</p>', smtp_config=config
            )
            is True
        )
        mock_smtp.__enter__.return_value.login.assert_not_called()
        mock_smtp.__enter__.return_value.send_message.assert_called_once()

    def test_half_a_login_is_refused_with_the_reason(self, monkeypatch):
        """A username without a password names what is missing."""
        monkeypatch.setattr('app.services.email_service.settings.SMTP_HOST', None)
        config = {'host': 'relay.internal', 'port': 25, 'user': 'someone'}

        result = EmailService.deliver(
            'recipient@test.com', 'Test', '<p>Test</p>', smtp_config=config
        )

        assert EmailService.is_configured(config) is False
        assert result.ok is False
        assert 'username and password' in (result.error or '')

    def test_send_email_smtp_connection_error(self, monkeypatch):
        """Test handling of SMTP connection errors."""
        # Mock SMTP to raise exception
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_HOST', 'smtp.test.com'
        )
        monkeypatch.setattr('app.services.email_service.settings.SMTP_PORT', 587)
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_USER', 'user@test.com'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_PASSWORD', 'password'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.EMAILS_FROM_EMAIL', 'from@test.com'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.EMAILS_FROM_NAME', 'Test'
        )

        def mock_smtp_error(*args, **kwargs):
            raise ConnectionError('SMTP connection failed')

        monkeypatch.setattr('smtplib.SMTP', mock_smtp_error)

        result = EmailService.send_email(
            to_email='recipient@test.com',
            subject='Test',
            html_content='<p>Test</p>',
        )

        assert result is False

    def test_send_email_auth_error(self, monkeypatch):
        """Test handling of SMTP authentication errors."""
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value.login.side_effect = (
            smtplib.SMTPAuthenticationError(535, b'Authentication failed')
        )
        monkeypatch.setattr('smtplib.SMTP', MagicMock(return_value=mock_smtp))

        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_HOST', 'smtp.test.com'
        )
        monkeypatch.setattr('app.services.email_service.settings.SMTP_PORT', 587)
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_USER', 'user@test.com'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.SMTP_PASSWORD', 'password'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.EMAILS_FROM_EMAIL', 'from@test.com'
        )
        monkeypatch.setattr(
            'app.services.email_service.settings.EMAILS_FROM_NAME', 'Test'
        )

        result = EmailService.send_email(
            to_email='recipient@test.com',
            subject='Test',
            html_content='<p>Test</p>',
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_registration_link_english(self, monkeypatch):
        """Test sending registration link email in English."""
        # Mock send_email method
        call_args = {}

        async def mock_send_email(
            to_email,
            subject,
            html_content,
            smtp_config=None,
            organization_id=None,
            failure_notice=None,
        ):
            call_args['to_email'] = to_email
            call_args['subject'] = subject
            call_args['html_content'] = html_content
            call_args['smtp_config'] = smtp_config
            return True

        monkeypatch.setattr(EmailService, 'send_email_async', mock_send_email)
        monkeypatch.setattr(
            'app.services.email_service.settings.FRONTEND_URL',
            'https://inventory.example.com',
        )

        en_registration_link = '/register?token=abc123'
        result = await EmailService.send_registration_link_async(
            to_email='user@test.com',
            registration_link=en_registration_link,
            lang='en',
        )

        assert result is True
        assert call_args['to_email'] == 'user@test.com'
        assert 'Your access to Inventari has been approved!' in call_args['subject']
        assert 'Complete Registration' in call_args['html_content']
        assert (
            'https://inventory.example.com/register?token=abc123'
            in call_args['html_content']
        )

    @pytest.mark.asyncio
    async def test_send_registration_link_polish(self, monkeypatch):
        """Test sending registration link email in Polish."""
        call_args = {}

        async def mock_send_email(
            to_email,
            subject,
            html_content,
            smtp_config=None,
            organization_id=None,
            failure_notice=None,
        ):
            call_args['to_email'] = to_email
            call_args['subject'] = subject
            call_args['html_content'] = html_content
            return True

        monkeypatch.setattr(EmailService, 'send_email_async', mock_send_email)
        monkeypatch.setattr(
            'app.services.email_service.settings.FRONTEND_URL',
            'https://inventory.example.com',
        )

        registration_link = '/register?token=xyz789'
        result = await EmailService.send_registration_link_async(
            to_email='user@example.org',
            registration_link=registration_link,
            lang='pl',
        )

        assert result is True
        assert call_args['to_email'] == 'user@example.org'
        assert 'Twój dostęp do Inventari został zatwierdzony!' in call_args['subject']
        assert 'Dokończ rejestrację' in call_args['html_content']
        assert 'Witaj!' in call_args['html_content']

    @pytest.mark.asyncio
    async def test_send_registration_link_german(self, monkeypatch):
        """Test sending registration link email in German."""
        call_args = {}

        async def mock_send_email(
            to_email,
            subject,
            html_content,
            smtp_config=None,
            organization_id=None,
            failure_notice=None,
        ):
            call_args['subject'] = subject
            call_args['html_content'] = html_content
            return True

        monkeypatch.setattr(EmailService, 'send_email_async', mock_send_email)
        monkeypatch.setattr(
            'app.services.email_service.settings.FRONTEND_URL',
            'https://inventory.example.com',
        )

        await EmailService.send_registration_link_async(
            to_email='user@test.de',
            registration_link='/register?token=de1',
            lang='de',
        )

        assert 'Ihr Zugang zu Inventari wurde genehmigt!' in call_args['subject']
        assert 'Registrierung abschließen' in call_args['html_content']
        assert 'Hallo!' in call_args['html_content']

    @pytest.mark.asyncio
    async def test_send_registration_link_french(self, monkeypatch):
        """Test sending registration link email in French."""
        call_args = {}

        async def mock_send_email(
            to_email,
            subject,
            html_content,
            smtp_config=None,
            organization_id=None,
            failure_notice=None,
        ):
            call_args['subject'] = subject
            call_args['html_content'] = html_content
            return True

        monkeypatch.setattr(EmailService, 'send_email_async', mock_send_email)
        monkeypatch.setattr(
            'app.services.email_service.settings.FRONTEND_URL',
            'https://inventory.example.com',
        )

        await EmailService.send_registration_link_async(
            to_email='user@test.fr',
            registration_link='/register?token=fr1',
            lang='fr',
        )

        assert 'Votre accès à Inventari a été approuvé !' in call_args['subject']
        assert "Finaliser l'inscription" in call_args['html_content']
        assert 'Bonjour !' in call_args['html_content']

    @pytest.mark.asyncio
    async def test_send_registration_link_spanish(self, monkeypatch):
        """Test sending registration link email in Spanish."""
        call_args = {}

        async def mock_send_email(
            to_email,
            subject,
            html_content,
            smtp_config=None,
            organization_id=None,
            failure_notice=None,
        ):
            call_args['subject'] = subject
            call_args['html_content'] = html_content
            return True

        monkeypatch.setattr(EmailService, 'send_email_async', mock_send_email)
        monkeypatch.setattr(
            'app.services.email_service.settings.FRONTEND_URL',
            'https://inventory.example.com',
        )

        await EmailService.send_registration_link_async(
            to_email='user@test.es',
            registration_link='/register?token=es1',
            lang='es',
        )

        assert '¡Tu acceso a Inventari ha sido aprobado!' in call_args['subject']
        assert 'Completar registro' in call_args['html_content']
        assert '¡Hola!' in call_args['html_content']

    @pytest.mark.asyncio
    async def test_send_registration_link_invalid_language_defaults_to_english(
        self, monkeypatch
    ):
        """Test that invalid language defaults to English."""
        call_args = {}

        async def mock_send_email(
            to_email,
            subject,
            html_content,
            smtp_config=None,
            organization_id=None,
            failure_notice=None,
        ):
            call_args['subject'] = subject
            call_args['html_content'] = html_content
            return True

        monkeypatch.setattr(EmailService, 'send_email_async', mock_send_email)
        monkeypatch.setattr(
            'app.services.email_service.settings.FRONTEND_URL',
            'https://inventory.example.com',
        )

        result = await EmailService.send_registration_link_async(
            to_email='user@test.com',
            registration_link='/register?token=invalid',
            lang='invalid_lang',
        )

        assert result is True
        # Should fallback to English
        assert 'Your access to Inventari' in call_args['subject']

    @pytest.mark.asyncio
    async def test_send_registration_link_with_custom_smtp(self, monkeypatch):
        """Test sending registration link with custom SMTP config."""
        call_args = {}

        async def mock_send_email(
            to_email,
            subject,
            html_content,
            smtp_config=None,
            organization_id=None,
            failure_notice=None,
        ):
            call_args['smtp_config'] = smtp_config
            return True

        monkeypatch.setattr(EmailService, 'send_email_async', mock_send_email)
        monkeypatch.setattr(
            'app.services.email_service.settings.FRONTEND_URL',
            'https://inventory.example.com',
        )

        custom_config = {
            'host': 'smtp.custom.com',
            'port': 465,
            'user': 'custom',
            'password': 'pass',
        }

        result = await EmailService.send_registration_link_async(
            to_email='user@test.com',
            registration_link='/register?token=test',
            smtp_config=custom_config,
        )

        assert result is True
        assert call_args['smtp_config'] == custom_config

    @pytest.mark.asyncio
    async def test_send_registration_link_frontend_url_trailing_slash_handling(
        self, monkeypatch
    ):
        """Test that frontend URL trailing slash is handled correctly."""
        call_args = {}

        async def mock_send_email(
            to_email,
            subject,
            html_content,
            smtp_config=None,
            organization_id=None,
            failure_notice=None,
        ):
            call_args['html_content'] = html_content
            return True

        monkeypatch.setattr(EmailService, 'send_email_async', mock_send_email)

        # Test with trailing slash
        monkeypatch.setattr(
            'app.services.email_service.settings.FRONTEND_URL',
            'https://inventory.example.com/',
        )

        result = await EmailService.send_registration_link_async(
            to_email='user@test.com',
            registration_link='/register?token=test',
        )

        assert result is True
        # Verify URL is correctly formed (no double slash)
        assert (
            'https://inventory.example.com/register?token=test'
            in call_args['html_content']
        )
        assert (
            'https://inventory.example.com//register' not in call_args['html_content']
        )

    def test_email_service_singleton(self):
        """Test that email_service is properly initialized."""
        from app.services.email_service import email_service

        assert email_service is not None
        assert isinstance(email_service, EmailService)


@pytest.mark.integration
class TestSmtpTransport:
    """Which transport a configuration gets, and how long it may hang.

    The port used to decide encryption on its own: ``starttls()`` was called
    when the port was exactly 587 and never otherwise, so a configuration on
    465 — the standard TLS port an administrator types by reflex — logged in
    and sent the message in the clear. And no call carried a ``timeout``, so
    an unreachable host held the request for the system TCP limit: 134 seconds
    measured in the walkthrough, ending in a 502.
    """

    @staticmethod
    def _smtp_config(**overrides) -> dict:
        cfg = {
            'host': 'smtp.example.com',
            'port': 587,
            'user': 'user@example.com',
            'password': 'secret',
            'from_email': 'sender@example.com',
            'from_name': 'Inventari',
        }
        cfg.update(overrides)
        return cfg

    def _send(self, monkeypatch, **overrides):
        plain = MagicMock(return_value=MagicMock())
        ssl = MagicMock(return_value=MagicMock())
        monkeypatch.setattr('smtplib.SMTP', plain)
        monkeypatch.setattr('smtplib.SMTP_SSL', ssl)

        result = EmailService.send_email(
            to_email='recipient@test.com',
            subject='Test',
            html_content='<p>Test</p>',
            smtp_config=self._smtp_config(**overrides),
        )
        assert result is True
        return plain, ssl

    def test_port_465_connects_over_ssl(self, monkeypatch):
        """A stored configuration from before the field existed still gets the
        transport its port implies — and 465 means SSL, not plaintext."""
        plain, ssl = self._send(monkeypatch, port=465)

        plain.assert_not_called()
        ssl.assert_called_once()
        assert ssl.call_args.kwargs['timeout'] > 0

    def test_port_587_starts_tls(self, monkeypatch):
        plain, ssl = self._send(monkeypatch, port=587)

        ssl.assert_not_called()
        plain.assert_called_once()
        plain.return_value.__enter__.return_value.starttls.assert_called_once()

    def test_port_25_stays_plain(self, monkeypatch):
        plain, ssl = self._send(monkeypatch, port=25)

        ssl.assert_not_called()
        plain.assert_called_once()
        plain.return_value.__enter__.return_value.starttls.assert_not_called()

    def test_explicit_encryption_wins_over_the_port(self, monkeypatch):
        """Once the choice is stored, the port number stops voting."""
        plain, ssl = self._send(monkeypatch, port=2525, encryption='ssl')

        plain.assert_not_called()
        ssl.assert_called_once()

        plain, ssl = self._send(monkeypatch, port=587, encryption='none')

        ssl.assert_not_called()
        plain.return_value.__enter__.return_value.starttls.assert_not_called()

    def test_every_transport_carries_a_timeout(self, monkeypatch):
        for port in (25, 465, 587):
            plain, ssl = self._send(monkeypatch, port=port)
            called = ssl if port == 465 else plain
            assert called.call_args.kwargs['timeout'] > 0, (
                f'port {port} connects without a timeout'
            )

    def _send_with_attachment(self, monkeypatch, **overrides):
        plain = MagicMock(return_value=MagicMock())
        ssl = MagicMock(return_value=MagicMock())
        monkeypatch.setattr('smtplib.SMTP', plain)
        monkeypatch.setattr('smtplib.SMTP_SSL', ssl)

        result = EmailService._send_email_with_attachment(
            to_email='recipient@test.com',
            subject='Test',
            html_content='<p>Test</p>',
            attachment_bytes=b'%PDF-1.4 protocol',
            attachment_filename='protocol.pdf',
            smtp_config=self._smtp_config(**overrides),
        )
        assert result.ok is True
        return plain, ssl

    def test_attachment_path_honours_ssl(self, monkeypatch):
        """An attached protocol travels the transport the settings chose.

        It used to open a plain connection of its own, so an organization on
        SSL/465 received the notification and never the file — the two
        halves of the same feature disagreeing about the same setting.
        """
        plain, ssl = self._send_with_attachment(monkeypatch, port=465)

        plain.assert_not_called()
        ssl.assert_called_once()
        assert ssl.call_args.kwargs['timeout'] > 0

    def test_attachment_path_starts_tls_when_asked(self, monkeypatch):
        """STARTTLS follows the stored choice, not the port number.

        Port 2525 with ``starttls`` stored used to send the login in the
        clear, because only 587 counted.
        """
        plain, ssl = self._send_with_attachment(
            monkeypatch, port=2525, encryption='starttls'
        )

        ssl.assert_not_called()
        plain.return_value.__enter__.return_value.starttls.assert_called_once()

    def test_failure_reports_why(self, monkeypatch):
        """The test-email endpoint has something to say beyond "it failed"."""
        monkeypatch.setattr(
            'smtplib.SMTP',
            MagicMock(side_effect=OSError('[Errno 110] Connection timed out')),
        )

        result = EmailService.deliver(
            to_email='recipient@test.com',
            subject='Test',
            html_content='<p>Test</p>',
            smtp_config=self._smtp_config(),
        )

        assert result.ok is False
        assert 'Connection timed out' in (result.error or '')
