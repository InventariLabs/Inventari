"""Prefix validation for LabelPoolCreate."""

import pytest
from pydantic import ValidationError

from app.schemas.label_pool import LabelPoolCreate


@pytest.mark.unit
@pytest.mark.integration
class TestLabelPoolCreatePrefix:
    def test_default_prefix_is_alphanumeric(self) -> None:
        cfg = LabelPoolCreate(count=10)
        assert cfg.prefix == 'STM'

    def test_accepts_alphanumeric_prefix(self) -> None:
        cfg = LabelPoolCreate(count=10, prefix='A12')
        assert cfg.prefix == 'A12'

    def test_rejects_prefix_with_hyphen(self) -> None:
        with pytest.raises(ValidationError):
            LabelPoolCreate(count=10, prefix='STM-')

    def test_rejects_prefix_with_space(self) -> None:
        with pytest.raises(ValidationError):
            LabelPoolCreate(count=10, prefix='S M')

    def test_rejects_prefix_longer_than_5(self) -> None:
        with pytest.raises(ValidationError):
            LabelPoolCreate(count=10, prefix='TOOLONG')

    def test_rejects_empty_prefix(self) -> None:
        with pytest.raises(ValidationError):
            LabelPoolCreate(count=10, prefix='')
