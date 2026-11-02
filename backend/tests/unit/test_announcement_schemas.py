from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.announcement import AnnouncementType
from app.schemas.announcement import AnnouncementCreate


def test_announcement_create_valid():
    """Test valid announcement creation schema."""
    data = {'title': 'Test Title', 'content': 'Test Content', 'type': 'warning'}
    ann = AnnouncementCreate(**data)
    assert ann.title == 'Test Title'
    assert ann.type == AnnouncementType.WARNING
    assert ann.active_until is None


def test_announcement_create_with_date():
    """Test announcement with active_until date."""
    future_date = datetime.now(UTC) + timedelta(days=5)
    data = {
        'title': 'Timed Ann',
        'content': 'Content',
        'type': 'critical',
        'active_until': future_date,
    }
    ann = AnnouncementCreate(**data)
    assert ann.active_until == future_date


def test_announcement_create_invalid_type():
    """Test schema validation fails for invalid type."""
    data = {'title': 'Title', 'content': 'Content', 'type': 'invalid_type'}
    with pytest.raises(ValidationError):
        AnnouncementCreate(**data)


def test_announcement_create_missing_required():
    """Test schema validation fails for missing required fields."""
    with pytest.raises(ValidationError):
        AnnouncementCreate(title='Only Title')
