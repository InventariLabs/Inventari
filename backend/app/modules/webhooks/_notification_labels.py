"""Notification copy for this module, one entry per supported language.

A notification row is stored as text and read months later, so the language it
is written in is the language it keeps — the recipient's ``preferred_language``
picks the entry at the moment the row is created.
"""

from __future__ import annotations

AUTO_DISABLED_TITLE: dict[str, str] = {
    'en': 'Webhook "{name}" switched off',
    'pl': 'Webhook „{name}” wyłączony',
    'de': 'Webhook „{name}“ abgeschaltet',
    'fr': 'Webhook « {name} » désactivé',
    'es': 'Webhook «{name}» desactivado',
}
AUTO_DISABLED_CONTENT: dict[str, str] = {
    # The diagnosis names where the cause lives, with the card's own words —
    # the last attempt can have died of something no address edit can reach
    # (an unreadable signing secret among them), so the notice an
    # administrator reads before the card must not guess either.
    'en': (
        'After {failures} deliveries in a row failed, the webhook "{name}" was '
        'switched off. The cause of the last attempt is named in the delivery '
        'log.'
    ),
    'pl': (
        'Po {failures} nieudanych dostarczeniach z rzędu webhook „{name}” '
        'został wyłączony. Przyczyna ostatniej próby jest zapisana w logach '
        'dostarczeń.'
    ),
    'de': (
        'Nach {failures} fehlgeschlagenen Zustellungen in Folge wurde der '
        'Webhook „{name}“ abgeschaltet. Die Ursache des letzten Versuchs '
        'steht im Zustellprotokoll.'
    ),
    'fr': (
        'Après {failures} livraisons échouées consécutives, le webhook '
        '« {name} » a été désactivé. La cause de la dernière tentative '
        'figure dans les journaux de livraison.'
    ),
    'es': (
        'Tras {failures} entregas fallidas seguidas, el webhook «{name}» se ha '
        'desactivado. La causa del último intento consta en los registros de '
        'entrega.'
    ),
}
