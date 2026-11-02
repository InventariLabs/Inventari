"""Notification copy for this module, one entry per supported language.

A notification row is stored as text and read months later, so the language it
is written in is the language it keeps. Writing English into a table that also
holds Polish is how the tray ended up mixing the two: the recipient's
``preferred_language`` picks the entry at the moment the row is created — see
``core_api.notifications.localize``.
"""

from __future__ import annotations

RECEIPT_CREATED_TITLE: dict[str, str] = {
    'en': 'Receipt {receipt} created',
    'pl': 'Utworzono przyjęcie {receipt}',
    'de': 'Wareneingang {receipt} erstellt',
    'fr': 'Réception {receipt} créée',
    'es': 'Recepción {receipt} creada',
}
RECEIPT_CREATED_CONTENT: dict[str, str] = {
    'en': 'Receipt {receipt} has been created from purchase order {po}.',
    'pl': 'Przyjęcie {receipt} zostało utworzone z zamówienia {po}.',
    'de': 'Wareneingang {receipt} wurde aus Bestellung {po} erstellt.',
    'fr': 'La réception {receipt} a été créée à partir de la commande {po}.',
    'es': 'La recepción {receipt} se ha creado a partir del pedido {po}.',
}

PO_REJECTED_TITLE: dict[str, str] = {
    'en': 'Purchase order {po} rejected',
    'pl': 'Zamówienie {po} odrzucone',
    'de': 'Bestellung {po} abgelehnt',
    'fr': 'Commande {po} refusée',
    'es': 'Pedido {po} rechazado',
}
PO_REJECTED_CONTENT: dict[str, str] = {
    'en': 'Purchase order {po} was rejected.{reason}',
    'pl': 'Zamówienie {po} zostało odrzucone.{reason}',
    'de': 'Bestellung {po} wurde abgelehnt.{reason}',
    'fr': 'La commande {po} a été refusée.{reason}',
    'es': 'El pedido {po} ha sido rechazado.{reason}',
}
PO_REJECTED_REASON: dict[str, str] = {
    'en': ' Reason: {notes}',
    'pl': ' Powód: {notes}',
    'de': ' Grund: {notes}',
    'fr': ' Motif : {notes}',
    'es': ' Motivo: {notes}',
}

PO_COMPLETED_TITLE: dict[str, str] = {
    'en': 'Purchase order {po} completed',
    'pl': 'Zamówienie {po} zrealizowane',
    'de': 'Bestellung {po} abgeschlossen',
    'fr': 'Commande {po} terminée',
    'es': 'Pedido {po} completado',
}
PO_COMPLETED_CONTENT: dict[str, str] = {
    'en': 'Purchase order {po} has been fully received.',
    'pl': 'Zamówienie {po} zostało w całości przyjęte.',
    'de': 'Bestellung {po} wurde vollständig vereinnahmt.',
    'fr': 'La commande {po} a été entièrement réceptionnée.',
    'es': 'El pedido {po} se ha recibido por completo.',
}
PO_COMPLETED_OWN_TITLE: dict[str, str] = {
    'en': 'Your purchase order {po} is complete',
    'pl': 'Twoje zamówienie {po} jest zrealizowane',
    'de': 'Ihre Bestellung {po} ist abgeschlossen',
    'fr': 'Votre commande {po} est terminée',
    'es': 'Tu pedido {po} está completo',
}
PO_COMPLETED_OWN_CONTENT: dict[str, str] = {
    'en': 'All items for purchase order {po} have been received.',
    'pl': 'Wszystkie pozycje zamówienia {po} zostały przyjęte.',
    'de': 'Alle Positionen der Bestellung {po} wurden vereinnahmt.',
    'fr': 'Tous les articles de la commande {po} ont été réceptionnés.',
    'es': 'Se han recibido todos los artículos del pedido {po}.',
}

RECALC_FAILED_TITLE: dict[str, str] = {
    'en': 'Purchase order quantity recalculation failed',
    'pl': 'Nie udało się przeliczyć ilości w zamówieniu',
    'de': 'Neuberechnung der Bestellmengen fehlgeschlagen',
    'fr': 'Échec du recalcul des quantités de la commande',
    'es': 'Error al recalcular las cantidades del pedido',
}
RECALC_FAILED_CONTENT: dict[str, str] = {
    'en': (
        'Purchase order quantities could not be recalculated after a receipt '
        'was cancelled ({lines} line(s) affected). The received quantity may '
        'be out of date — please check it.'
    ),
    'pl': (
        'Nie udało się przeliczyć ilości w zamówieniu po anulowaniu przyjęcia '
        '(dotyczy {lines} pozycji). Przyjęta ilość może być nieaktualna — '
        'sprawdź ją.'
    ),
    'de': (
        'Die Bestellmengen konnten nach dem Stornieren eines Wareneingangs '
        'nicht neu berechnet werden ({lines} Position(en) betroffen). Die '
        'vereinnahmte Menge ist möglicherweise veraltet — bitte prüfen.'
    ),
    'fr': (
        "Les quantités de la commande n'ont pas pu être recalculées après "
        "l'annulation d'une réception ({lines} ligne(s) concernée(s)). La "
        'quantité reçue peut être obsolète — veuillez la vérifier.'
    ),
    'es': (
        'No se pudieron recalcular las cantidades del pedido tras anular una '
        'recepción ({lines} línea(s) afectada(s)). La cantidad recibida puede '
        'estar desactualizada: compruébela.'
    ),
}
