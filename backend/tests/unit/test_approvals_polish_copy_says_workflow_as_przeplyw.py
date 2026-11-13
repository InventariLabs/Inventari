"""The approvals module calls a workflow "przepływ" in Polish, never "ścieżka"."""

from pathlib import Path

from app.modules.approvals import _services_notify

_MODULE = Path(_services_notify.__file__).parent
_FORBIDDEN = ('ścieżk', 'Ścieżk')


def test_closure_notifications_use_przeplyw() -> None:
    for texts in _services_notify._CLOSURE_CONTENT.values():
        assert not any(word in texts['pl'] for word in _FORBIDDEN)
        assert 'Przepływ akceptacji' in texts['pl']


def test_no_polish_approvals_notification_says_sciezka() -> None:
    source = (_MODULE / '_services_notify.py').read_text(encoding='utf-8')
    assert not any(word in source for word in _FORBIDDEN)
