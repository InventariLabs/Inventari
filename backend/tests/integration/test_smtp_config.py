"""Validation of SmtpConfig used by /api/organizations/my/test-email."""

import pytest
from pydantic import ValidationError

from app.api.organizations import SmtpConfig


@pytest.mark.unit
@pytest.mark.integration
class TestSmtpConfig:
    def test_accepts_minimal_valid_config(self) -> None:
        cfg = SmtpConfig(host='smtp.gmail.com', port=587)
        assert cfg.host == 'smtp.gmail.com'
        assert cfg.port == 587
        assert cfg.from_name == 'Inventari'

    def test_rejects_empty_host(self) -> None:
        with pytest.raises(ValidationError):
            SmtpConfig(host='', port=587)

    def test_rejects_port_below_1(self) -> None:
        with pytest.raises(ValidationError):
            SmtpConfig(host='smtp.gmail.com', port=0)

    def test_rejects_port_above_65535(self) -> None:
        with pytest.raises(ValidationError):
            SmtpConfig(host='smtp.gmail.com', port=70000)

    def test_rejects_malformed_from_email(self) -> None:
        with pytest.raises(ValidationError):
            SmtpConfig(host='smtp.gmail.com', port=587, from_email='not-an-email')
