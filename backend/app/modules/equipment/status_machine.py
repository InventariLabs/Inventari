"""
Equipment status state machine.

Defines allowed transitions between equipment statuses.
Status is stored in meta_data['equipment']['equipment_status'].
"""

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    'AVAILABLE': {'DEPLOYED', 'MAINTENANCE', 'RETIRED'},
    'DEPLOYED': {'AVAILABLE', 'MAINTENANCE', 'RETIRED'},
    'MAINTENANCE': {'AVAILABLE', 'DEPLOYED', 'RETIRED'},
    'RETIRED': {'AVAILABLE'},
}

VALID_STATUSES = set(_ALLOWED_TRANSITIONS.keys())

#: What the metadata reader writes where an asset has no status yet. It is
#: an absence, not a state: it is not in ``VALID_STATUSES``, every read of
#: a previous status walks past it, and it must never reach a screen as if
#: it were a name.
UNKNOWN_STATUS = 'UNKNOWN'


def resolve_previous_status(value: str | None) -> str | None:
    """A previous status as the interface may show it.

    ``UNKNOWN`` and empty both mean "there was no status" and read as
    ``None`` — the caller renders its own nothing — while a real state
    passes through untouched.
    """
    if not value or value == UNKNOWN_STATUS:
        return None
    return value


_TRANSITION_ERROR_KEYS: dict[str, dict[str, str]] = {
    'en': {
        'invalid_status': 'Invalid status: {status}',
        'transition_denied': 'Cannot change status from {old} to {new}',
        'from_retired_hint': ' Retired assets must be explicitly unretired first.',
    },
    'pl': {
        'invalid_status': 'Nieprawidłowy status: {status}',
        'transition_denied': 'Nie można zmienić status z {old} na {new}',
        'from_retired_hint': ' Wycofane zasoby muszą być najpierw jawnie przywrócone.',
    },
    'de': {
        'invalid_status': 'Ungültiger Status: {status}',
        'transition_denied': 'Status kann nicht von {old} nach {new} geändert werden',
        'from_retired_hint': ' Ausgemusterte Geräte müssen zuerst explizit reaktiviert werden.',
    },
    'fr': {
        'invalid_status': 'Statut invalide : {status}',
        'transition_denied': 'Impossible de changer le statut de {old} à {new}',
        'from_retired_hint': " Les équipements retirés doivent d'abord être explicitement réactivés.",
    },
    'es': {
        'invalid_status': 'Estado no válido: {status}',
        'transition_denied': 'No se puede cambiar el estado de {old} a {new}',
        'from_retired_hint': ' Los equipos retirados deben ser reactivados explícitamente primero.',
    },
}


def validate_transition(
    old_status: str | None, new_status: str, lang: str = 'en'
) -> None:
    """Validate that a status transition is allowed.

    Raises ValueError with a translated message if the transition is not allowed.
    """
    labels = _TRANSITION_ERROR_KEYS.get(lang, _TRANSITION_ERROR_KEYS['en'])

    if new_status not in VALID_STATUSES:
        raise ValueError(labels['invalid_status'].format(status=new_status))

    previous = resolve_previous_status(old_status)
    if previous is None:
        return

    allowed = _ALLOWED_TRANSITIONS.get(previous, VALID_STATUSES)
    if new_status not in allowed:
        msg = labels['transition_denied'].format(old=previous, new=new_status)
        if previous == 'RETIRED':
            msg += labels['from_retired_hint']
        raise ValueError(msg)
