"""Scheduled stock reconciliation — drift measured on a cycle, not on demand.

``GET /stats/reconciliation`` answers only when somebody asks, and nobody
asks until a report has been wrong for a month. This job runs the same
two-pair comparison on a schedule, leaves the numbers in the log (the
metric), warns the organization's admins when a drift appears or changes,
reminds them once a week while it stands unchanged, and stores what it
measured, so the screen can put a row beside its predecessor instead of
asking the reader to watch a number they see once. A clean pass is stored
and warns nobody.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.contracts import PreviousMeasurementDTO
from app.core.logging import get_logger
from app.i18n.service import SUPPORTED_LANGUAGES, get_error_message

logger = get_logger(__name__)

_ZERO = Decimal('0')

#: The settings key the previous pass is stored under. The drift warning's
#: ``changed?`` question and the reconciliation screen's ``what did it look
#: like last time`` read the same record — one write, two readers, so the
#: number the screen calls "previous" is exactly the one that decided the
#: last warning.
_SIGNATURE_KEY = 'reconciliation_drift_signature'

#: The warning's copy, one entry per language, read from the core catalogue —
#: the same place every other translated message lives, so the sentence names
#: the tabs exactly as the interface does in each language and cannot drift
#: away from it. A recipient reads the entry their ``preferred_language``
#: picks; an unknown language falls back to English inside the notification
#: service.
_DRIFT_TITLE: dict[str, str] = {
    str(lang): get_error_message('reconciliation_drift_title', lang)
    for lang in SUPPORTED_LANGUAGES
}
_DRIFT_CONTENT: dict[str, str] = {
    str(lang): get_error_message('reconciliation_drift_content', lang)
    for lang in SUPPORTED_LANGUAGES
}
_STANDING_TITLE: dict[str, str] = {
    str(lang): get_error_message('reconciliation_drift_standing_title', lang)
    for lang in SUPPORTED_LANGUAGES
}
_STANDING_CONTENT: dict[str, str] = {
    str(lang): get_error_message('reconciliation_drift_standing_content', lang)
    for lang in SUPPORTED_LANGUAGES
}

#: Each pair named the way the reconciliation screen names it — "the shelf vs
#: the movement ledger", not "quant/ledger" — keyed by the figure that counts
#: it. The warning lists only the pairs that disagree: the one that agrees is
#: not news, and the model's own names for its layers read as noise to a
#: household that never meets them.
_PAIR_PHRASES: dict[str, dict[str, str]] = {
    figure: {
        str(lang): get_error_message(message_key, lang) for lang in SUPPORTED_LANGUAGES
    }
    for figure, message_key in (
        ('quant_move_drift_count', 'reconciliation_pair_quant_ledger'),
        ('layer_quant_drift_count', 'reconciliation_pair_layer_quant'),
    )
}

#: The figures a pass measures — what it stores, and what its signature is
#: made of.
_FIGURES = frozenset(
    {
        'quant_move_drift_count',
        'quant_move_drift_total',
        'layer_quant_drift_count',
        'layer_quant_drift_total',
    }
)

#: How long a drift may stand unchanged before the admins hear of it again.
#: A change is news the pass it happens; a drift nobody acts on used to go
#: quiet for good after its first warning — "a fact of the hydration design"
#: — and a fact nobody is told about again is one nobody looks at.
_STANDING_REMINDER = timedelta(days=7)

#: How often the pass runs, and so how old a stored pass may be before an
#: organization is measured again. The scheduler ticks at this interval and
#: also once on every start of a backend process; without the age check each
#: restart, and each of the web workers starting side by side, measured every
#: organization again beside the users it was serving.
RECONCILIATION_INTERVAL = timedelta(hours=6)

#: A pass is due a little before the interval is out: a tick lands a few
#: seconds either side of the previous one, and a pass measured 5 h 59 min 58 s
#: ago must not make the next tick wait another six hours.
_DUE_SLACK = timedelta(minutes=5)


def _signature_of(figures: dict[str, Any]) -> str:
    return '|'.join(str(figures[key]) for key in sorted(figures) if key in _FIGURES)


def _encode_measurement(
    measured_at: datetime, figures: dict[str, Any], alerted_at: datetime
) -> str:
    """The record both readers consume: this pass's figures, and when.

    Quantities travel as their exact string — the report's totals are
    ``numeric`` values, and a float would make the stored record unable to
    say whether its number was measured or rounded. ``alerted_at`` is when
    the admins last heard about these figures, which is what the weekly
    reminder of a standing drift counts from.
    """
    return json.dumps(
        {
            'measured_at': measured_at.isoformat(),
            'alerted_at': alerted_at.isoformat(),
            'figures': {key: str(value) for key, value in figures.items()},
        }
    )


def _decode_measurement(raw: object) -> tuple[str, str | None, str | None]:
    """The stored record as ``(signature, measured_at, alerted_at)``.

    Records written before the pass carried its timestamp stored the bare
    signature string; it compares the way it always did and the next pass
    rewrites it in the structured shape. ``None`` reads as "never measured",
    and a record from before the reminder has no ``alerted_at``. A figure
    the job no longer measures — the two pairs that ended with the quant
    table — is left out of the signature, so a drift standing on the pairs
    that remain does not read as new the first pass after they went.
    Anything but a string under the key — only a hand-made write puts one
    there — reads as never measured too, and the pass overwrites it.
    """
    if not raw or not isinstance(raw, str):
        return '', None, None
    if raw.startswith('{'):
        payload = json.loads(raw)
        stored: dict[str, str] = payload.get('figures', {})
        return (
            '|'.join(stored[key] for key in sorted(stored) if key in _FIGURES),
            payload.get('measured_at'),
            payload.get('alerted_at'),
        )
    return raw, None, None


def _has_drift(figures: dict[str, Any]) -> bool:
    return any(v for k, v in figures.items() if k.endswith('_count'))


def _drift_content(figures: dict[str, Any], *, standing: bool) -> dict[str, str]:
    """The warning's sentence in every language, naming the pairs that disagree."""
    table = _STANDING_CONTENT if standing else _DRIFT_CONTENT
    return {
        lang: text.format(
            pairs='; '.join(
                phrases[lang].format(count=figures[figure])
                for figure, phrases in _PAIR_PHRASES.items()
                if figures[figure]
            )
        )
        for lang, text in table.items()
    }


def decode_previous_measurement(raw: object) -> PreviousMeasurementDTO | None:
    """The stored pass as the DTO the public API hands to the screen.

    A record from before the structured shape, or the absence of one, has
    no timestamp to show — ``None`` is the honest answer, and the screen
    says the previous measurement has not been taken yet. So has a value
    of another shape under the key: it used to fail the whole screen.
    """
    if not isinstance(raw, str) or not raw.startswith('{'):
        return None
    payload = json.loads(raw)
    figures: dict[str, str] = payload.get('figures', {})
    measured_at = payload.get('measured_at')
    if not measured_at:
        return None
    return PreviousMeasurementDTO(
        measured_at=datetime.fromisoformat(measured_at),
        quant_move_drift_count=int(figures['quant_move_drift_count']),
        quant_move_drift_total=Decimal(figures['quant_move_drift_total']),
        layer_quant_drift_count=int(figures['layer_quant_drift_count']),
        layer_quant_drift_total=Decimal(figures['layer_quant_drift_total']),
    )


async def read_previous_measurement_async(
    db, organization_id: UUID
) -> PreviousMeasurementDTO | None:
    """What the previous scheduled pass measured, for the screen to show."""
    from app.core.public_api import core_api

    stored = await core_api.settings.get_async(
        db, organization_id, 'core', _SIGNATURE_KEY
    )
    return decode_previous_measurement(stored)


async def reconcile_organization_async(db, organization_id: UUID) -> dict:
    """Run both pair comparisons for one organization.

    Returns the reconciliation DTO's figures as a plain dict. Alerting,
    storing and logging live here rather than in the read-model, so the
    endpoint stays a pure read.
    """
    from app.services.analytics.reconciliation import get_reconciliation_async

    result = await get_reconciliation_async(db, organization_id)
    figures = {
        'quant_move_drift_count': result.quant_move_drift_count or 0,
        'quant_move_drift_total': result.quant_move_drift_total or _ZERO,
        'layer_quant_drift_count': result.layer_quant_drift_count or 0,
        'layer_quant_drift_total': result.layer_quant_drift_total or _ZERO,
    }
    if _has_drift(figures):
        logger.warning(
            '[reconciliation] stock drift measured',
            extra={'organization_id': str(organization_id), **figures},
        )
    else:
        logger.info(
            '[reconciliation] stock reconciled clean',
            extra={'organization_id': str(organization_id), **figures},
        )
    return figures


async def _record_pass_and_alert_admins_async(
    db, organization_id: UUID, figures: dict, measured_at: datetime
) -> None:
    """Store this pass; warn the admins when a drift appears, changes or stands.

    The write happens every pass: a record that only moved when the figures
    did would leave the screen's "previous" naming a measurement taken the
    day the drift last changed, not the one taken before this one — and the
    reader comparing today's number against it could not tell a standing
    figure from a stale one. The warning compares figures, never the
    timestamp, so a standing drift does not warn again pass after pass. It
    does come back once :data:`_STANDING_REMINDER` has passed since the admins
    last heard of it, with its own sentence — "still standing", not "found" —
    and a record from before the reminder starts that clock on this pass
    rather than firing at once.

    Every admin is warned in the language they read. The row is text and
    keeps the language it was written in, so the copy is a table keyed by
    language — taken from the core catalogue, so it cannot drift from the
    rest of the application — and the recipient's ``preferred_language``
    picks the entry. It used to be one English literal for every admin at
    once: a Polish administrator read it beside notifications that were
    already translated. The sentence also names the two tabs the way the
    interface names them (Statistics → Reconciliation, Statystyki →
    Uzgodnienie); "Stats → Reconciliation" pointed at labels no screen
    carries.

    Only a drift is news. The warning used to fire on any change of the
    figures, so the first pass of every organization — nothing stored to
    compare with — told a new organization "Stock drift detected" in its
    first minute while the screen it linked to said "In agreement", and a
    drift that disappeared was announced as if it had just been found. A
    clean pass is still stored, so a drift that comes back later is a change
    again and warns.
    """
    from app.core.public_api import core_api

    signature = _signature_of(figures)
    previous_signature, _, previous_alert = _decode_measurement(
        await core_api.settings.get_async(db, organization_id, 'core', _SIGNATURE_KEY)
    )
    alerted_at = (
        datetime.fromisoformat(previous_alert) if previous_alert else measured_at
    )
    if _has_drift(figures):
        if previous_signature != signature:
            await _warn_admins_async(db, organization_id, figures, standing=False)
            alerted_at = measured_at
        elif measured_at - alerted_at >= _STANDING_REMINDER:
            await _warn_admins_async(db, organization_id, figures, standing=True)
            alerted_at = measured_at
    await core_api.settings.set_bulk_async(
        db,
        organization_id,
        'core',
        {_SIGNATURE_KEY: _encode_measurement(measured_at, figures, alerted_at)},
    )


async def _warn_admins_async(
    db, organization_id: UUID, figures: dict, *, standing: bool
) -> None:
    """One warning to every admin, in their language: found, or still there."""
    from app.core.public_api import core_api

    await core_api.notifications.notify_org_admins_async(
        db,
        organization_id,
        title=_STANDING_TITLE if standing else _DRIFT_TITLE,
        content=_drift_content(figures, standing=standing),
        notification_type='warning',
        # The address the reader actually lands on. This said '/stats',
        # which is not a route in this application: the warning about
        # drift ended on Page Not Found.
        link='/inventory/stats/reconciliation',
    )


async def _is_due_async(db, organization_id: UUID, now: datetime) -> bool:
    """Whether the organization's last stored pass is old enough to repeat.

    No stored pass, or one from before the record carried its timestamp, is
    due: nothing says it was measured.
    """
    previous = await read_previous_measurement_async(db, organization_id)
    if previous is None:
        return True
    return now - previous.measured_at >= RECONCILIATION_INTERVAL - _DUE_SLACK


async def run_reconciliation_once() -> None:
    """One pass over every organization: measure, log, store, alert on change.

    An organization measured within the last interval is left alone, so a
    backend that restarts, or starts several workers at once, does not run
    the comparison again for every organization on every start.
    """
    from app.core import db_facade
    from app.models.organization import Organization

    if db_facade.AsyncSessionLocal is None:
        logger.warning('[reconciliation] session factory unavailable; skipped')
        return

    async with db_facade.AsyncSessionLocal() as db:
        org_ids = (
            await db.scalars(select(Organization.id).order_by(Organization.id))
        ).all()
        now = datetime.now(UTC)
        for organization_id in org_ids:
            try:
                if not await _is_due_async(db, organization_id, now):
                    continue
                figures = await reconcile_organization_async(db, organization_id)
                await _record_pass_and_alert_admins_async(
                    db, organization_id, figures, datetime.now(UTC)
                )
                await db.commit()
            except Exception:  # one broken org must not stop the others
                logger.exception(
                    '[reconciliation] failed for organization %s', organization_id
                )
                await db.rollback()
