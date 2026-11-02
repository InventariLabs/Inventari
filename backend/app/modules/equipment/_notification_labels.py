"""Notification copy for this module, one entry per supported language.

A notification row is stored as text and read months later, so the language it
is written in is the language it keeps — the recipient's ``preferred_language``
picks the entry at the moment the row is created.
"""

from __future__ import annotations

WARRANTY_TITLE: dict[str, str] = {
    'en': 'Warranty expiring: {item}',
    'pl': 'Kończy się gwarancja: {item}',
    'de': 'Garantie läuft ab: {item}',
    'fr': 'Garantie bientôt expirée : {item}',
    'es': 'La garantía caduca: {item}',
}
WARRANTY_CONTENT: dict[str, str] = {
    'en': (
        'The warranty on {item} (serial number {serial}) expires in {days} '
        'day(s), on {date}.'
    ),
    'pl': (
        'Gwarancja na {item} (numer seryjny {serial}) kończy się za {days} dni, {date}.'
    ),
    'de': (
        'Die Garantie für {item} (Seriennummer {serial}) läuft in {days} '
        'Tag(en) ab, am {date}.'
    ),
    'fr': (
        'La garantie de {item} (numéro de série {serial}) expire dans {days} '
        'jour(s), le {date}.'
    ),
    'es': (
        'La garantía de {item} (número de serie {serial}) caduca en {days} '
        'día(s), el {date}.'
    ),
}

OVERDUE_TITLE: dict[str, str] = {
    'en': 'Overdue return: {item}',
    'pl': 'Zaległy zwrot: {item}',
    'de': 'Überfällige Rückgabe: {item}',
    'fr': 'Retour en retard : {item}',
    'es': 'Devolución vencida: {item}',
}
OVERDUE_CONTENT: dict[str, str] = {
    'en': '{item}, assigned to {holder}, was due back {days} day(s) ago.',
    'pl': '{item}, przypisany do {holder}, miał wrócić {days} dni temu.',
    'de': '{item}, zugewiesen an {holder}, war vor {days} Tag(en) fällig.',
    'fr': '{item}, attribué à {holder}, devait revenir il y a {days} jour(s).',
    'es': '{item}, asignado a {holder}, debía volver hace {days} día(s).',
}
#: A deployment's overdue sentence: the holder is a place, and "assigned to"
#: would claim a person the record does not have.
OVERDUE_CONTENT_LOCATION: dict[str, str] = {
    'en': '{item}, standing in {holder}, was due back {days} day(s) ago.',
    'pl': '{item}, stojący w {holder}, miał wrócić {days} dni temu.',
    'de': '{item}, stehend in {holder}, war vor {days} Tag(en) fällig.',
    'fr': '{item}, se trouvant dans {holder}, devait revenir il y a {days} jour(s).',
    'es': '{item}, situado en {holder}, debía volver hace {days} día(s).',
}

MAINTENANCE_TITLE: dict[str, str] = {
    'en': 'Maintenance due: {item}',
    'pl': 'Zbliża się przegląd: {item}',
    'de': 'Wartung fällig: {item}',
    'fr': 'Maintenance à prévoir : {item}',
    'es': 'Mantenimiento pendiente: {item}',
}
MAINTENANCE_CONTENT: dict[str, str] = {
    'en': '{item} has {kind} scheduled in {days} day(s), on {date}.',
    'pl': '{item} ma zaplanowane: {kind} za {days} dni, {date}.',
    'de': 'Für {item} ist {kind} in {days} Tag(en) geplant, am {date}.',
    'fr': 'Pour {item}, {kind} est prévu dans {days} jour(s), le {date}.',
    'es': 'Para {item} hay {kind} programado en {days} día(s), el {date}.',
}

#: When the asset carries no serial number.
NO_SERIAL: dict[str, str] = {
    'en': 'none',
    'pl': 'brak',
    'de': 'keine',
    'fr': 'aucun',
    'es': 'ninguno',
}

#: When the assignment or the log points at an item that is no longer there.
UNKNOWN_ITEM: dict[str, str] = {
    'en': 'Unknown item',
    'pl': 'Nieznany sprzęt',
    'de': 'Unbekanntes Gerät',
    'fr': 'Équipement inconnu',
    'es': 'Equipo desconocido',
}

#: When a legacy row names neither a person nor a place. Current paths
#: cannot write one, but a notification must never format an empty holder
#: into the sentence.
UNKNOWN_HOLDER: dict[str, str] = {
    'en': 'an unnamed holder',
    'pl': 'nieznany posiadacz',
    'de': 'ein unbenannter Halter',
    'fr': 'un détenteur inconnu',
    'es': 'un poseedor desconocido',
}

#: An attestation answered with a problem. It used to be stored on the
#: response and nowhere else: nobody was told, and the asset said nothing.
DISPUTE_TITLE: dict[str, str] = {
    'en': 'Problem reported: {item}',
    'pl': 'Zgłoszono problem: {item}',
    'de': 'Problem gemeldet: {item}',
    'fr': 'Problème signalé : {item}',
    'es': 'Problema notificado: {item}',
}
DISPUTE_CONTENT: dict[str, str] = {
    'en': '{holder} answered the attestation “{campaign}” about {item}: {reason}',
    'pl': '{holder} odpowiedział(a) w atestacji „{campaign}” w sprawie {item}: {reason}',
    'de': '{holder} hat in der Attestierung „{campaign}“ zu {item} geantwortet: {reason}',
    'fr': '{holder} a répondu à l’attestation « {campaign} » au sujet de {item} : {reason}',
    'es': '{holder} respondió a la atestación «{campaign}» sobre {item}: {reason}',
}
