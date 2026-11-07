from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

import markupsafe

from app.core.public_api import core_api

_EMAIL_LABELS: dict[str, dict[str, str]] = {
    'en': {
        'heading': 'Asset Attestation — Action Required',
        'greeting': 'Hello',
        'default_body': (
            'Please confirm that you still have <b>{item}</b> in your possession. '
            'This confirmation is required by <b>{deadline}</b>.'
        ),
        'multiple_items_body': (
            'Please confirm that you still have the following items in your possession:'
        ),
        'button': 'Confirm / Report Issue',
        'fallback': "If the button doesn't work, copy and paste this link:",
        'footer': 'This is an automated message from Inventari.',
        'subject': 'Asset attestation required',
        'reminder_prefix': '[Reminder] ',
    },
    'pl': {
        'heading': 'Atestacja sprzętu — wymagane działanie',
        'greeting': 'Witaj',
        'default_body': (
            'Prosimy o potwierdzenie, że <b>{item}</b> nadal znajduje się w Twoim posiadaniu. '
            'Potwierdzenie jest wymagane do <b>{deadline}</b>.'
        ),
        'multiple_items_body': (
            'Prosimy o potwierdzenie, że nadal posiadasz następujące zasoby:'
        ),
        'button': 'Potwierdź / Zgłoś problem',
        'fallback': 'Jeśli przycisk nie działa, skopiuj i wklej ten link:',
        'footer': 'To jest automatyczna wiadomość z systemu Inventari.',
        'subject': 'Atestacja sprzętu — wymagane działanie',
        'reminder_prefix': '[Przypomnienie] ',
    },
    'de': {
        'heading': 'Attestierung — Handlung erforderlich',
        'greeting': 'Hallo',
        'default_body': (
            'Bitte bestätigen Sie, dass sich <b>{item}</b> noch in Ihrem Besitz befindet. '
            'Diese Bestätigung ist bis zum <b>{deadline}</b> erforderlich.'
        ),
        'multiple_items_body': (
            'Bitte bestätigen Sie, dass sich die folgenden Geräte noch in '
            'Ihrem Besitz befinden:'
        ),
        'button': 'Bestätigen / Problem melden',
        'fallback': 'Wenn der Button nicht funktioniert, kopieren Sie diesen Link:',
        'footer': 'Dies ist eine automatische Nachricht von Inventari.',
        'subject': 'Attestierung erforderlich',
        'reminder_prefix': '[Erinnerung] ',
    },
    'fr': {
        'heading': "Attestation d'équipement — Action requise",
        'greeting': 'Bonjour',
        'default_body': (
            'Veuillez confirmer que <b>{item}</b> est toujours en votre possession. '
            'Cette confirmation est requise avant le <b>{deadline}</b>.'
        ),
        'multiple_items_body': (
            'Veuillez confirmer que vous êtes toujours en possession des '
            'équipements suivants :'
        ),
        'button': 'Confirmer / Signaler un problème',
        'fallback': 'Si le bouton ne fonctionne pas, copiez ce lien :',
        'footer': "Ceci est un message automatique d'Inventari.",
        'subject': "Attestation d'équipement requise",
        'reminder_prefix': '[Rappel] ',
    },
    'es': {
        'heading': 'Atestación de equipo — Acción requerida',
        'greeting': 'Hola',
        'default_body': (
            'Por favor confirme que aún tiene <b>{item}</b> en su posesión. '
            'Esta confirmación es requerida antes del <b>{deadline}</b>.'
        ),
        'multiple_items_body': (
            'Por favor confirme que aún tiene los siguientes activos en su posesión:'
        ),
        'button': 'Confirmar / Reportar problema',
        'fallback': 'Si el botón no funciona, copie este enlace:',
        'footer': 'Este es un mensaje automático de Inventari.',
        'subject': 'Atestación de equipo requerida',
        'reminder_prefix': '[Recordatorio] ',
    },
}

_DEFAULT_LANG = 'en'


def _get_email_label(lang: str, key: str) -> str:
    return _EMAIL_LABELS.get(lang, _EMAIL_LABELS[_DEFAULT_LANG]).get(
        key, _EMAIL_LABELS[_DEFAULT_LANG][key]
    )


def _build_email_html(
    assignee_name: str,
    item_name: str,
    attestation_url: str,
    deadline: datetime | str,
    custom_body: str | None,
    lang: str = _DEFAULT_LANG,
    item_names: list[str] | None = None,
    deadline_tz: tzinfo | None = None,
) -> str:
    from datetime import datetime

    # A deadline is a day on the organization's calendar (create_campaign
    # pins the end of that day in the org's zone before storing). The stored
    # value is a UTC instant, so printing it bare answers with UTC's date —
    # the next day for an organization west of Greenwich, which is how the
    # invitation mail said "26" while the screen said "25". astimezone reads
    # the instant through the organization's clock first; the date printed is
    # then the day the org picked.
    if isinstance(deadline, datetime) and deadline_tz is not None:
        deadline = deadline.astimezone(deadline_tz)
    deadline_str = (
        deadline.strftime('%Y-%m-%d')
        if isinstance(deadline, datetime)
        else str(deadline)
    )
    safe_name = markupsafe.escape(assignee_name)
    safe_item = markupsafe.escape(item_name)
    if custom_body is not None:
        # Admin-provided body — escape so any HTML they paste is rendered
        # as inert text rather than live markup in the recipient's inbox.
        body_paragraph: Any = markupsafe.escape(custom_body)
    elif item_names and len(item_names) > 1:
        # one email per person lists every asset in one place.
        items_html = ''.join(
            f'<li>{markupsafe.escape(name)}</li>' for name in item_names
        )
        body_paragraph = (
            f'{_get_email_label(lang, "multiple_items_body")}'
            f'<ul style="margin: 8px 0; padding-left: 20px;">{items_html}</ul>'
        )
    else:
        body_paragraph = _get_email_label(lang, 'default_body').format(
            item=safe_item, deadline=deadline_str
        )
    return core_api.email.render_shell(
        _get_email_label(lang, 'heading'),
        f'            <p>{_get_email_label(lang, "greeting")} <b>{safe_name}</b>,</p>\n'
        f'            <p>{body_paragraph}</p>\n'
        + core_api.email.render_button(
            attestation_url, _get_email_label(lang, 'button')
        )
        + '\n'
        + core_api.email.render_fallback_link(
            _get_email_label(lang, 'fallback'), attestation_url
        ),
        _get_email_label(lang, 'footer'),
    )
