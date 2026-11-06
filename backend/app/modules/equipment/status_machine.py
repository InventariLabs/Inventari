"""
Equipment status state machine.

Defines allowed transitions between equipment statuses.
Status is stored in meta_data['equipment']['equipment_status'].
"""

from app.core.exceptions import ServiceRejectionError

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


def validate_transition(old_status: str | None, new_status: str) -> None:
    """Validate that a status transition is allowed.

    Raises a keyed ``ServiceRejectionError``: the sentence is the catalogue's
    in the language of the request (or of the bulk row's caller), and the
    refusal carries its machine code.
    """
    if new_status not in VALID_STATUSES:
        raise ServiceRejectionError('equipment_status_invalid', status=new_status)

    previous = resolve_previous_status(old_status)
    if previous is None:
        return

    allowed = _ALLOWED_TRANSITIONS.get(previous, VALID_STATUSES)
    if new_status not in allowed:
        key = (
            'equipment_status_transition_from_retired'
            if previous == 'RETIRED'
            else 'equipment_status_transition_denied'
        )
        raise ServiceRejectionError(key, old=previous, new=new_status)
