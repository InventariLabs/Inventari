"""The names the screens give the stored statuses, for sentences the backend writes.

A refusal that interpolates ``MAINTENANCE`` or ``COMPLETED`` shows the reader
the stored enum, while every screen says "Maintenance" and "Closed". These
tables carry the screens' own words (the frontend catalogues' ``status`` and
``attestation.status`` blocks), one entry per language, so a sentence names a
state the way the page next to it does.
"""

from __future__ import annotations

from app.i18n.service import get_current_lang

EQUIPMENT_STATUS_LABELS: dict[str, dict[str, str]] = {
    'en': {
        'AVAILABLE': 'Available',
        'DEPLOYED': 'Checked Out',
        'MAINTENANCE': 'Maintenance',
        'RETIRED': 'Retired',
    },
    'pl': {
        'AVAILABLE': 'Dostępny',
        'DEPLOYED': 'Wydany',
        'MAINTENANCE': 'W serwisie',
        'RETIRED': 'Wycofany',
    },
    'de': {
        'AVAILABLE': 'Verfügbar',
        'DEPLOYED': 'Ausgeliehen',
        'MAINTENANCE': 'Wartung',
        'RETIRED': 'Ausgemustert',
    },
    'fr': {
        'AVAILABLE': 'Disponible',
        'DEPLOYED': 'Emprunté',
        'MAINTENANCE': 'Maintenance',
        'RETIRED': 'Retiré',
    },
    'es': {
        'AVAILABLE': 'Disponible',
        'DEPLOYED': 'Prestado',
        'MAINTENANCE': 'Mantenimiento',
        'RETIRED': 'Retirado',
    },
    'pt': {
        'AVAILABLE': 'Disponível',
        'DEPLOYED': 'Entregue',
        'MAINTENANCE': 'Manutenção',
        'RETIRED': 'Baixado',
    },
}

CAMPAIGN_STATUS_LABELS: dict[str, dict[str, str]] = {
    'en': {
        'DRAFT': 'Draft',
        'ACTIVE': 'Active',
        'COMPLETED': 'Closed',
        'CANCELLED': 'Cancelled',
    },
    'pl': {
        'DRAFT': 'Szkic',
        'ACTIVE': 'Aktywna',
        'COMPLETED': 'Zamknięta',
        'CANCELLED': 'Anulowana',
    },
    'de': {
        'DRAFT': 'Entwurf',
        'ACTIVE': 'Aktiv',
        'COMPLETED': 'Abgeschlossen',
        'CANCELLED': 'Abgebrochen',
    },
    'fr': {
        'DRAFT': 'Brouillon',
        'ACTIVE': 'Active',
        'COMPLETED': 'Clôturée',
        'CANCELLED': 'Annulée',
    },
    'es': {
        'DRAFT': 'Borrador',
        'ACTIVE': 'Activa',
        'COMPLETED': 'Cerrada',
        'CANCELLED': 'Cancelada',
    },
    'pt': {
        'DRAFT': 'Rascunho',
        'ACTIVE': 'Ativa',
        'COMPLETED': 'Encerrada',
        'CANCELLED': 'Cancelada',
    },
}


def _label(table: dict[str, dict[str, str]], status: str) -> str:
    """The screens' name for *status* in the current language, or *status* itself."""
    return table.get(get_current_lang(), table['en']).get(status, status)


def equipment_status_label(status: str) -> str:
    return _label(EQUIPMENT_STATUS_LABELS, status)


def campaign_status_label(status: str) -> str:
    return _label(CAMPAIGN_STATUS_LABELS, status)
