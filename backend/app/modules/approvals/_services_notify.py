"""Best-effort approver notifications for approval requests.

Creating an approval request notifies the approvers of the pending stage:
an in-app notification (persisted via ``core_api.notifications`` and pushed
through Redis to the WebSocket hub) plus a transactional email (global SMTP,
localized per recipient). Both channels are best-effort: a notification
failure must never fail or roll back the approval request itself.

The helper is invoked from ``request_approval`` AFTER the request
transaction commits. The notification Core API raw-awaits ``db.flush()``,
which requires an AsyncSession — all approvals callers are async now.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from html import escape
from typing import TYPE_CHECKING, Any
from uuid import UUID

from babel.numbers import format_currency, format_decimal
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserDTO
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.public_api.users import UserProfileDTO

from ._audit import people_names_async
from ._services_solvability import (
    APPROVE_GRANT,
    NAMED_APPROVERS_CANNOT_DECIDE,
    cannot_be_decided_reason,
    deciders_async,
    named_approvers,
    stage_label,
)
from .models import OPEN_STATUSES
from .target_scopes import describe_scope_async
from .target_summaries import get_target_summary_provider
from .target_types import REQUESTING_TARGET_TYPES

if TYPE_CHECKING:
    from .models import ApprovalRequest

logger = get_logger(__name__)

# The queue opens on everything still awaiting a decision. Linking to
# ``pending`` alone hid every request already part-way through a multi-stage
# workflow — precisely the ones this notification is about.
QUEUE_LINK = '/approvals?status=PENDING,IN_PROGRESS'

_NOTIFY_TITLE: dict[str, str] = {
    'en': 'New approval request',
    'pl': 'Nowy wniosek o akceptację',
    'de': 'Neue Genehmigungsanfrage',
    'fr': "Nouvelle demande d'approbation",
    'es': 'Nueva solicitud de aprobación',
}
_NOTIFY_CONTENT: dict[str, str] = {
    'en': 'An approval request is waiting for your decision.',
    'pl': 'Wniosek o akceptację czeka na Twoją decyzję.',
    'de': 'Eine Genehmigungsanfrage wartet auf Ihre Entscheidung.',
    'fr': "Une demande d'approbation attend votre décision.",
    'es': 'Una solicitud de aprobación espera su decisión.',
}
# Who asks and about what. Two requests from one person read alike without it,
# and the recipient had to open the queue to tell them apart.
_NOTIFY_TITLE_NAMED: dict[str, str] = {
    'en': 'New approval request: {number}',
    'pl': 'Nowy wniosek o akceptację: {number}',
    'de': 'Neue Genehmigungsanfrage: {number}',
    'fr': "Nouvelle demande d'approbation : {number}",
    'es': 'Nueva solicitud de aprobación: {number}',
}
_NOTIFY_CONTENT_NAMED: dict[str, str] = {
    'en': 'Request from {requester}: {target}. It is waiting for your decision.',
    'pl': 'Wniosek od {requester}: {target}. Czeka na Twoją decyzję.',
    'de': 'Anfrage von {requester}: {target}. Sie wartet auf Ihre Entscheidung.',
    'fr': 'Demande de {requester} : {target}. Elle attend votre décision.',
    'es': 'Solicitud de {requester}: {target}. Espera su decisión.',
}
# The amount a summary reports is net, the side the approval threshold is on.
_NET_AMOUNT: dict[str, str] = {
    'en': '{amount} net',
    'pl': '{amount} netto',
    'de': '{amount} netto',
    'fr': '{amount} HT',
    'es': '{amount} neto',
}
_OPEN_QUEUE: dict[str, str] = {
    'en': 'Open the approval queue',
    'pl': 'Otwórz kolejkę akceptacji',
    'de': 'Genehmigungswarteschlange öffnen',
    'fr': 'Ouvrir la file approbation',
    'es': 'Abrir la cola de aprobaciones',
}


def _loc(table: dict[str, str], lang: str) -> str:
    return table.get(lang, table['en'])


def _money(value: Decimal, currency: str | None, lang: str) -> str:
    """The amount as the queue card writes it, in the recipient's language."""
    locale = lang.replace('-', '_')
    if currency:
        return format_currency(value, currency, locale=locale)
    return format_decimal(value, format='#,##0.00', locale=locale)


@dataclass(frozen=True)
class _RequestFacts:
    """What the notice names: who asked, and what the request stands before."""

    requester: str | None
    number: str | None
    amount: Decimal | None
    currency: str | None

    def title(self, lang: str) -> str:
        if not self.number:
            return _loc(_NOTIFY_TITLE, lang)
        return _loc(_NOTIFY_TITLE_NAMED, lang).format(number=self.number)

    def content(self, lang: str) -> str:
        if not self.requester or not self.number:
            return _loc(_NOTIFY_CONTENT, lang)
        target = self.number
        if self.amount is not None:
            amount = _money(self.amount, self.currency, lang)
            target += f', {_loc(_NET_AMOUNT, lang).format(amount=amount)}'
        return _loc(_NOTIFY_CONTENT_NAMED, lang).format(
            requester=self.requester, target=target
        )


async def _request_facts_async(
    db: AsyncSession, request: ApprovalRequest, org_id: UUID
) -> _RequestFacts:
    """Read them from whoever describes the target; missing facts are left out."""
    names = await people_names_async(db, org_id, [request.created_by])
    provider = get_target_summary_provider(request.target_type)
    summaries = (
        await provider(db, org_id, [request.target_id]) if provider is not None else {}
    )
    summary = summaries.get(request.target_id)
    return _RequestFacts(
        requester=names.get(str(request.created_by)),
        number=getattr(summary, 'number', None),
        amount=getattr(summary, 'total_value', None),
        currency=getattr(summary, 'currency', None),
    )


_DEAD_END_TITLE: dict[str, str] = {
    'en': 'Approval request stuck',
    'pl': 'Wniosek o akceptację utknął',
    'de': 'Genehmigungsanfrage hängt fest',
    'fr': "Demande d'approbation bloquée",
    'es': 'Solicitud de aprobación bloqueada',
}
# The way out, in words the recipient can act on: the stage that holds the
# request and the two moves that end the wait — give the person who should
# decide the access, or withdraw the request. Sent to the people who can take
# either, never to an approver the door would refuse. Two shapes because the
# way out differs: a stage that names the wrong person is fixed by granting
# that person, an open stage by granting anybody.
_DEAD_END_NAMED_CONTENT: dict[str, str] = {
    'en': (
        'The request is waiting at stage \u201c{stage}\u201d, but the person it '
        'names cannot decide it. To unblock it, give that person access to '
        'approvals, or withdraw the request.'
    ),
    'pl': (
        'Wniosek czeka na etapie \u201e{stage}\u201d, ale wskazana osoba nie może '
        'go zatwierdzić. Aby go odblokować, przyznaj jej dostęp do akceptacji '
        'albo wycofaj wniosek.'
    ),
    'de': (
        'Die Anfrage wartet auf der Stufe \u201e{stage}\u201c, aber die genannte '
        'Person kann sie nicht entscheiden. Um sie freizugeben, geben Sie dieser '
        'Person Zugriff auf Genehmigungen, oder ziehen Sie die Anfrage zurück.'
    ),
    'fr': (
        "La demande attend à l'étape \u00ab\u00a0{stage}\u00a0\u00bb, mais la "
        'personne nommée ne peut pas y décider. Pour la débloquer, accordez-lui '
        "l'accès aux approbations, ou retirez la demande."
    ),
    'es': (
        'La solicitud espera en la etapa \u00ab{stage}\u00bb, pero la persona '
        'indicada no puede decidirla. Para desbloquearla, concédele acceso a '
        'aprobaciones, o retira la solicitud.'
    ),
}
_DEAD_END_OPEN_CONTENT: dict[str, str] = {
    'en': (
        'The request is waiting at stage \u201c{stage}\u201d, but nobody can '
        'decide it. To unblock it, give someone access to approvals, or '
        'withdraw the request.'
    ),
    'pl': (
        'Wniosek czeka na etapie \u201e{stage}\u201d, ale nikt nie może go '
        'zatwierdzić. Aby go odblokować, przyznaj komuś dostęp do akceptacji '
        'albo wycofaj wniosek.'
    ),
    'de': (
        'Die Anfrage wartet auf der Stufe \u201e{stage}\u201c, aber niemand kann '
        'sie entscheiden. Um sie freizugeben, geben Sie jemandem Zugriff auf '
        'Genehmigungen, oder ziehen Sie die Anfrage zurück.'
    ),
    'fr': (
        "La demande attend à l'étape \u00ab\u00a0{stage}\u00a0\u00bb, mais "
        "personne ne peut y décider. Pour la débloquer, accordez à quelqu'un "
        "l'accès aux approbations, ou retirez la demande."
    ),
    'es': (
        'La solicitud espera en la etapa \u00ab{stage}\u00bb, pero nadie puede '
        'decidirla. Para desbloquearla, concede a alguien acceso a '
        'aprobaciones, o retira la solicitud.'
    ),
}


async def clear_settled_notices(
    db: AsyncSession, org_id: UUID, request_id: UUID
) -> None:
    """Mark a settled request's unread notices read.

    A request that was decided, withdrawn or released no longer waits for
    anybody, and the bell must stop counting a decision nobody can take. Call
    it before the outcome notices are written: they report the end of the
    request and stay unread.
    """
    await core_api.notifications.mark_read_by_meta_async(
        db, org_id, 'approval_request_id', str(request_id)
    )


async def _stage_verdict_async(
    db: AsyncSession,
    org_id: UUID,
    request: ApprovalRequest,
    stage_def: dict[str, Any],
) -> tuple[str | None, set[UUID]]:
    """(why nobody could decide this stage, or ``None``, and who can).

    The same rule the queue reports under and the save refuses under
    (``_services_solvability``), asked here so a notice cannot promise a
    decision the door refuses. ``deciders`` is who the door lets through: on
    a stage that names people, those of them holding a grant that reaches it;
    on an open stage, every holder of the approve grant except the requester,
    unless the organization lets them decide their own request.
    """
    named = named_approvers(stage_def)
    deciders = await deciders_async(db, org_id, named)

    approver_holders: set[UUID] | None = None
    if not named:
        approver_holders = await core_api.roles.holders_of_permission_async(
            db, organization_id=org_id, permission=APPROVE_GRANT
        )

    requester_may_decide_own = False
    if request.created_by in named or (
        approver_holders is not None and request.created_by in approver_holders
    ):
        from ._services_decisions import _may_decide_on_own_request

        requester_may_decide_own = await _may_decide_on_own_request(
            db, org_id, request.created_by
        )

    reason = cannot_be_decided_reason(
        stage_def,
        org_has_approver=bool(approver_holders)
        if approver_holders is not None
        else True,
        deciders=deciders,
        requester_id=request.created_by,
        approver_holders=approver_holders,
        requester_may_decide_own=requester_may_decide_own,
    )
    if approver_holders is not None:
        deciders = set(approver_holders)
    if not requester_may_decide_own:
        deciders.discard(request.created_by)
    return reason, deciders


async def _notify_stage_dead_end_async(
    db: AsyncSession,
    request: ApprovalRequest,
    stage_name: str,
    reason: str,
    org_id: UUID,
) -> None:
    """Tell the requester and the admins that the pending stage is a dead end.

    The stage cannot be decided, so the one notification that would have been
    useful — "it is your turn" — is replaced by the truth and the way out. The
    requester withdraws, an administrator grants the access; exactly one
    notification reaches each, and nobody is told a decision they cannot take.
    """
    title = _DEAD_END_TITLE
    copy = (
        _DEAD_END_NAMED_CONTENT
        if reason == NAMED_APPROVERS_CANNOT_DECIDE
        else _DEAD_END_OPEN_CONTENT
    )
    content = core_api.notifications.localize(copy, stage=stage_name)
    meta_data = {
        'approval_request_id': str(request.id),
        'target_type': request.target_type,
        'kind': 'approval_dead_end',
        'reason': reason,
    }

    # Both channels are best-effort, and the caller already guards them: the
    # two callers of ``_notify_pending_stage_approvers_async`` catch and log
    # whatever this raises, so a notice that fails never fails the request it
    # was about. Catching again here would only hide the failure from that one
    # guard without changing what the reader sees.
    # The administrators by authority, not by the role's name: a custom role
    # that may grant the access is as much a way out as the built-in level.
    administrators = await core_api.roles.administrators_async(
        db, organization_id=org_id
    )
    recipients: list[UUID] = [request.created_by, *administrators]

    dtos = []
    for user_id in dict.fromkeys(recipients):
        dto = await core_api.notifications.create_async(
            db,
            user_id=user_id,
            title=title,
            content=content,
            notification_type='warning',
            link=QUEUE_LINK,
            meta_data=meta_data,
        )
        if dto is not None:
            dtos.append(dto)

    await core_api.notifications.publish_async(db, dtos)


async def _notify_pending_stage_approvers_async(
    db: AsyncSession,
    request: ApprovalRequest,
    stages: list[dict[str, Any]],
    org_id: UUID,
) -> None:
    """Notify the approvers of the request's current pending stage.

    No-op when the request is already terminal (e.g. every stage was
    auto-skipped to APPROVED). When the current stage names nobody, they are
    the active holders of the approve grant.
    """
    if request.status not in OPEN_STATUSES:
        return

    stage_def = next(
        (s for s in stages if s.get('order') == request.current_stage), None
    )
    if stage_def is None:
        return

    reason, deciders = await _stage_verdict_async(db, org_id, request, stage_def)
    if reason is not None:
        # Nobody could decide this stage, so nobody is told it is their turn.
        # The people who can end the wait hear instead what it would take.
        await _notify_stage_dead_end_async(
            db, request, stage_label(stage_def), reason, org_id
        )
        return

    # Never promise a decision the door refuses: whoever is told it is their
    # turn is somebody the door lets through. On an open stage that is a
    # holder of the approve grant, whatever their role is called.
    users: Sequence[UserProfileDTO | UserDTO]
    try:
        users = await core_api.users.get_by_ids_async(db, org_id, list(deciders))
    except Exception as exc:  # noqa: BLE001 — resolution is best-effort
        logger.warning('[Approvals] notify: failed to resolve approvers: %s', exc)
        return

    if not users:
        return

    facts = await _request_facts_async(db, request, org_id)

    notification_dtos = []
    for user in users:
        lang = user.preferred_language or 'en'
        title = facts.title(lang)
        content = facts.content(lang)
        try:
            dto = await core_api.notifications.create_async(
                db,
                user_id=user.id,
                title=title,
                content=content,
                notification_type='info',
                link=QUEUE_LINK,
                meta_data={
                    'approval_request_id': str(request.id),
                    'target_type': request.target_type,
                },
            )
            if dto is not None:
                notification_dtos.append(dto)
        except Exception as exc:  # noqa: BLE001 — one recipient's failure must not stop the rest
            logger.warning(
                '[Approvals] notify: failed to notify user %s: %s', user.id, exc
            )

    # Real-time fan-out is best-effort (publish_async never raises; it logs).
    await core_api.notifications.publish_async(db, notification_dtos)

    # Email is secondary; global SMTP configured via env. Never blocks.
    for user in users:
        if not user.email:
            continue
        try:
            lang = user.preferred_language or 'en'
            subject = facts.title(lang)
            # A person's name and a document number are somebody's typing, and
            # this is the channel that renders them as markup.
            body = escape(facts.content(lang))
            html = (
                '<html><body style="font-family:sans-serif;line-height:1.6;'
                'color:#333;"><p>'
                f'{body}</p><p><a href="{QUEUE_LINK}">'
                f'{_loc(_OPEN_QUEUE, lang)}</a></p></body></html>'
            )
            await core_api.email.send_async(
                user.email, subject, html, organization_id=org_id
            )
        except Exception as exc:  # noqa: BLE001 — email is best-effort
            logger.warning(
                '[Approvals] notify: email to %s failed: %s', user.email, exc
            )


# Requester notification on reject.
DOC_OPEN_LINK = '/warehouse/documents/{doc_id}'

_REJECT_TITLE: dict[str, str] = {
    'en': 'Your approval request was rejected',
    'pl': 'Twój wniosek o akceptację został odrzucony',
    'de': 'Ihre Genehmigungsanfrage wurde abgelehnt',
    'fr': "Votre demande d'approbation a été rejetée",
    'es': 'Su solicitud de aprobación fue rechazada',
}
_REJECT_CONTENT: dict[str, str] = {
    'en': 'Reason: {reason}. Open the document to fix and re-submit.',
    'pl': 'Powód: {reason}. Otwórz dokument, aby poprawić i wysłać ponownie.',
    'de': 'Grund: {reason}. Öffnen Sie das Dokument, um es zu korrigieren und erneut einzureichen.',
    'fr': 'Motif : {reason}. Ouvrez le document pour le corriger et le renvoyer.',
    'es': 'Motivo: {reason}. Abra el documento para corregirlo y reenviarlo.',
}
_REJECT_NO_REASON: dict[str, str] = {
    'en': 'No reason provided. Open the document to fix and re-submit.',
    'pl': 'Brak powodu. Otwórz dokument, aby poprawić i wysłać ponownie.',
    'de': 'Kein Grund angegeben. Öffnen Sie das Dokument, um es zu korrigieren und erneut einzureichen.',
    'fr': 'Aucun motif fourni. Ouvrez le document pour le corriger et le renvoyer.',
    'es': 'No se proporcionó motivo. Abra el documento para corregirlo y reenviarlo.',
}
_REJECT_OPEN_DOC: dict[str, str] = {
    'en': 'Open document',
    'pl': 'Otwórz dokument',
    'de': 'Dokument öffnen',
    'fr': 'Ouvrir le document',
    'es': 'Abrir documento',
}


async def notify_rejection_async(
    db: AsyncSession,
    *,
    org_id: UUID,
    doc_id: UUID,
    request_id: UUID,
    requester_id: UUID,
    reason: str | None,
) -> None:
    """Notify the requester that their approval request was rejected.

    Best-effort: any failure is logged but never raised. The caller must
    not roll back the request state on notification failure — same
    contract as ``_notify_pending_stage_approvers_async``.
    """
    try:
        requester = await core_api.users.get_full_async(db, org_id, requester_id)
    except Exception as exc:  # noqa: BLE001 — the notice is best-effort
        logger.warning(
            '[Approvals] notify_rejection: failed to load requester %s: %s',
            requester_id,
            exc,
        )
        return

    if requester is None:
        return

    lang = requester.preferred_language or 'en'
    title = _loc(_REJECT_TITLE, lang)
    if reason:
        body = _loc(_REJECT_CONTENT, lang).format(reason=reason)
    else:
        body = _loc(_REJECT_NO_REASON, lang)
    link = DOC_OPEN_LINK.format(doc_id=doc_id)

    try:
        dto = await core_api.notifications.create_async(
            db,
            user_id=requester_id,
            title=title,
            content=body,
            notification_type='warning',
            link=link,
            meta_data={
                'approval_request_id': str(request_id),
                'document_id': str(doc_id),
                'kind': 'approval_rejected',
            },
        )
    except Exception as exc:  # noqa: BLE001 — the notice is best-effort
        logger.warning(
            '[Approvals] notify_rejection: create_async failed for %s: %s',
            requester_id,
            exc,
        )
        return

    if dto is not None:
        try:
            await core_api.notifications.publish_async(db, [dto])
        except Exception as exc:  # noqa: BLE001 — the notice is best-effort
            logger.warning(
                '[Approvals] notify_rejection: publish_async failed: %s', exc
            )

    if requester.email:
        try:
            open_label = _loc(_REJECT_OPEN_DOC, lang)
            # `body` carries the approver's free-text reason; escaped here
            # because this is the one channel that renders it as markup.
            html = (
                '<html><body style="font-family:sans-serif;line-height:1.6;'
                'color:#333;"><p>'
                f'{escape(body)}</p><p><a href="{link}">{open_label}</a></p>'
                '</body></html>'
            )
            await core_api.email.send_async(
                requester.email, title, html, organization_id=org_id
            )
        except Exception as exc:  # noqa: BLE001 — email is best-effort
            logger.warning(
                '[Approvals] notify_rejection: email to %s failed: %s',
                requester.email,
                exc,
            )


# Requester notification when the workflow was switched off under a waiting
# request. Two halves, because they answer two different questions: the
# closure says why the request ended, the consequence says whether the item
# may now be carried out — which is not the same answer.
_CLOSED_TITLE: dict[str, str] = {
    'en': 'Your approval request was closed',
    'pl': 'Twój wniosek o akceptację został zamknięty',
    'de': 'Ihre Genehmigungsanfrage wurde geschlossen',
    'fr': "Votre demande d'approbation a été clôturée",
    'es': 'Su solicitud de aprobación fue cerrada',
}
_CLOSURE_CONTENT: dict[str, dict[str, str]] = {
    'workflow deactivated': {
        'en': 'The approval workflow was deactivated, so nothing is waiting for a decision any more.',
        'pl': 'Przepływ akceptacji został wyłączony, więc nic już nie czeka na decyzję.',
        'de': 'Der Genehmigungsablauf wurde deaktiviert, es wartet nichts mehr auf eine Entscheidung.',
        'fr': "Le circuit d'approbation a été désactivé : plus rien n'attend de décision.",
        'es': 'El flujo de aprobación se desactivó, así que nada espera una decisión.',
    },
    'workflow deleted': {
        'en': 'The approval workflow was deleted, so nothing is waiting for a decision any more.',
        'pl': 'Przepływ akceptacji został usunięty, więc nic już nie czeka na decyzję.',
        'de': 'Der Genehmigungsablauf wurde gelöscht, es wartet nichts mehr auf eine Entscheidung.',
        'fr': "Le circuit d'approbation a été supprimé : plus rien n'attend de décision.",
        'es': 'El flujo de aprobación se eliminó, así que nada espera una decisión.',
    },
}

# The consequence, when nothing stands in the item's way any more — a
# released order, or a document no setting holds back any more.
_GOES_ON_CONTENT: dict[str, str] = {
    'en': 'The item goes on without approval.',
    'pl': 'Pozycja przechodzi dalej bez akceptacji.',
    'de': 'Der Vorgang geht ohne Genehmigung weiter.',
    'fr': "L'élément poursuit sans approbation.",
    'es': 'El elemento sigue sin aprobación.',
}

# The consequence when the target's own module still demands an approval of
# it: the request is closed, and that is not permission to execute. Worded
# after the administrator's switch-off dialog, which names the same settings
# from the same scope — the requester is warned with what the admin was.
_STILL_REQUIRED_CONTENT: dict[str, str] = {
    'en': (
        'Your request is closed, but that is not an approval. Still requiring '
        'approval: {settings}. The item stops at completion until that setting '
        'is cleared or a workflow is active again.'
    ),
    'pl': (
        'Twój wniosek został zamknięty, ale to nie jest akceptacja. '
        'Akceptacji nadal wymaga: {settings}. Pozycja zatrzyma się przy '
        'zakończeniu, dopóki ustawienie nie zostanie wyczyszczone lub nie '
        'będzie znów aktywnego przepływu.'
    ),
    'de': (
        'Ihr Antrag wurde geschlossen, aber das ist keine Genehmigung. '
        'Weiterhin genehmigungspflichtig laut: {settings}. Der Vorgang bleibt '
        'beim Abschluss stehen, bis diese Einstellung gelöscht ist oder wieder '
        'ein Ablauf aktiv ist.'
    ),
    'fr': (
        "Votre demande a été clôturée, mais ce n'est pas une approbation. "
        "Une approbation reste exigée par : {settings}. L'élément s'arrête à "
        "la clôture tant que ce réglage n'est pas vidé ou qu'un circuit n'est "
        'pas de nouveau actif.'
    ),
    'es': (
        'Su solicitud fue cerrada, pero eso no es una aprobación. Siguen '
        'exigiendo aprobación: {settings}. El elemento se detiene al '
        'completarse hasta que se borre ese ajuste o vuelva a haber un flujo '
        'activo.'
    ),
}

# The setting names the scope gives, in the recipient's language — the same
# names the switch-off dialog shows the administrator. A setting nobody has
# named here reaches the reader as the key the scope answered with, the way
# the dialog falls back too.
_SETTING_NAMES: dict[str, dict[str, str]] = {
    'en': {
        'approval_threshold': 'the approval threshold',
        'approval_required_for_types': 'the document types that need approval',
    },
    'pl': {
        'approval_threshold': 'próg akceptacji',
        'approval_required_for_types': 'lista typów dokumentów wymagających akceptacji',
    },
    'de': {
        'approval_threshold': 'der Genehmigungsschwellenwert',
        'approval_required_for_types': 'die genehmigungspflichtigen Dokumenttypen',
    },
    'fr': {
        'approval_threshold': "le seuil d'approbation",
        'approval_required_for_types': 'la liste des types de documents soumis à approbation',
    },
    'es': {
        'approval_threshold': 'el umbral de aprobación',
        'approval_required_for_types': 'la lista de tipos de documento que requieren aprobación',
    },
}


async def _still_required_by_settings(
    db: AsyncSession, org_id: UUID, target: tuple[str, UUID] | None
) -> list[str]:
    """The settings that still demand an approval of this released target.

    Empty when the released item may go on. A requesting target type (see
    ``target_types.REQUESTING_TARGET_TYPES``) is finished with its request:
    releasing it confirms the target and nothing of its own guards it
    afterwards, so its settings concern orders that have not been raised yet,
    not the one that was just released. A gated target goes back under its
    own module's gate, and which settings still demand an approval there is
    the asking module's answer — through the scope provider it registered,
    the same answer the switch-off dialog shows the administrator.

    It is the setting's answer for this kind of target, not a verdict on one
    item: whether a particular document is over its threshold is the module's
    rule to apply at completion, where the refusal speaks for itself.
    """
    if target is None:
        return []
    target_type = target[0]
    if target_type in REQUESTING_TARGET_TYPES:
        return []
    scope = await describe_scope_async(db, org_id, target_type)
    return list(scope.required_by_settings) if scope is not None else []


def _named_settings(settings: Sequence[str], lang: str) -> str:
    names = _SETTING_NAMES.get(lang, _SETTING_NAMES['en'])
    return ', '.join(names.get(name, name) for name in settings)


async def _target_number(
    db: AsyncSession, org_id: UUID, target: tuple[str, UUID] | None
) -> str | None:
    """The human number of a request's target, or ``None`` when nobody can say."""
    if target is None:
        return None
    from .target_summaries import get_target_summary_provider

    provider = get_target_summary_provider(target[0])
    if provider is None:
        return None
    summary = (await provider(db, org_id, [target[1]])).get(target[1])
    return getattr(summary, 'number', None)


async def notify_request_closed(
    db: AsyncSession,
    org_id: UUID,
    request_id: UUID,
    requester_id: UUID,
    *,
    reason: str,
    target: tuple[str, UUID] | None = None,
) -> None:
    """Tell the requester their request was closed because its workflow went off.

    ``target`` (type, id) lets the notice name the item by its number, through
    the target-summary provider its module registered; without a provider the
    notice stays unnamed. It also decides the second half of the notice: the
    closure ends the request, and whether the item may now be carried out is
    a separate answer (see ``_still_required_by_settings``).

    Best-effort, in-app only: a notice that cannot be stored is logged and
    never fails the switch-off, which is the admin's act.
    """
    try:
        requester = await core_api.users.get_full_async(db, org_id, requester_id)
        if requester is None:
            return
        lang = requester.preferred_language or 'en'
        texts = _CLOSURE_CONTENT.get(reason, _CLOSURE_CONTENT['workflow deactivated'])
        still_required = await _still_required_by_settings(db, org_id, target)
        if still_required:
            consequence = _loc(_STILL_REQUIRED_CONTENT, lang).format(
                settings=_named_settings(still_required, lang)
            )
        else:
            consequence = _loc(_GOES_ON_CONTENT, lang)
        content = f'{_loc(texts, lang)} {consequence}'
        number = await _target_number(db, org_id, target)
        if number:
            content = f'{number}: {content}'
        dto = await core_api.notifications.create_async(
            db,
            user_id=requester_id,
            title=_loc(_CLOSED_TITLE, lang),
            content=content,
            notification_type='info',
            link='/approvals',
            meta_data={
                'approval_request_id': str(request_id),
                'kind': 'approval_closed',
                'reason': reason,
            },
        )
        if dto is not None:
            await core_api.notifications.publish_async(db, [dto])
    except Exception as exc:  # noqa: BLE001 — the notice is best-effort
        logger.warning(
            '[Approvals] notify_request_closed failed for %s: %s', requester_id, exc
        )
