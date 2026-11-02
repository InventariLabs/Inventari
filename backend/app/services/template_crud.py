"""Shared CRUD service for DocumentTemplate model."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import NotFoundException, catalogue_refusal
from app.core.logging import get_logger
from app.core.template_models import DocumentTemplate
from app.i18n.service import get_current_lang
from app.services.audit_service import log_action_async
from app.services.template_engine import TemplateEngine

logger = get_logger(__name__)


def _template_snapshot(tpl: DocumentTemplate) -> dict[str, object]:
    """A template as the organization log names it.

    Not the body: a printed protocol is pages of HTML, and a snapshot that
    large buries every other entry on the screen. What a reader needs is
    which template, whose, and whether it is the one that prints by default.
    """
    return {
        'name': tpl.name,
        'module': tpl.module,
        'document_type': tpl.document_type,
        'is_default': tpl.is_default,
    }


async def _log_template_async(
    db: AsyncSession,
    tpl: DocumentTemplate,
    *,
    user_id: uuid.UUID | None,
    action: AuditAction,
    snapshot: dict[str, object] | None = None,
) -> None:
    """Record a template write for whichever module made it.

    Here rather than in the modules: equipment, documents and purchase
    orders all write the same table through the same functions, and a
    journal kept per module would say a handover protocol was edited when
    equipment did it and nothing when documents did — the log depending on
    which screen was open, which is the thing it must never do.
    """
    await log_action_async(
        db,
        organization_id=tpl.organization_id,
        user_id=user_id,
        action=action,
        target_type=AuditTargetType.DOCUMENT_TEMPLATE,
        target_id=tpl.id,
        snapshot=snapshot if snapshot is not None else _template_snapshot(tpl),
    )


async def get_default_template_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    module: str,
    document_type: str,
) -> DocumentTemplate | None:
    result = await db.scalar(
        select(DocumentTemplate).where(
            DocumentTemplate.organization_id == org_id,
            DocumentTemplate.module == module,
            DocumentTemplate.document_type == document_type,
            DocumentTemplate.is_default.is_(True),
        )
    )
    return result


async def list_templates_async(
    db: AsyncSession, org_id: uuid.UUID, module: str
) -> list[DocumentTemplate]:
    result = await db.scalars(
        select(DocumentTemplate)
        .where(
            DocumentTemplate.organization_id == org_id,
            DocumentTemplate.module == module,
        )
        .order_by(DocumentTemplate.created_at.desc())
    )
    return list(result.all())


async def get_template_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    module: str,
) -> DocumentTemplate | None:
    return await db.scalar(
        select(DocumentTemplate).where(
            DocumentTemplate.id == template_id,
            DocumentTemplate.organization_id == org_id,
            DocumentTemplate.module == module,
        )
    )


async def create_template_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    module: str,
    user_id: uuid.UUID,
    name: str,
    body_html: str,
    document_type: str = 'DEFAULT',
    is_default: bool = False,
    partials: dict[str, str] | None = None,
) -> DocumentTemplate:
    # Stored verbatim: the template is code, not data, and a
    # source-level sanitizer pass would reorder the HTML around Jinja spans
    # (html5lib foster-parenting). Sanitization happens on the rendered
    # output (TemplateEngine.render), where it cannot mangle the template.
    if partials:
        engine = TemplateEngine()
        body_html = engine.inline_includes(body_html, partials)

    if is_default:
        await db.execute(
            update(DocumentTemplate)
            .where(
                DocumentTemplate.organization_id == org_id,
                DocumentTemplate.module == module,
                DocumentTemplate.document_type == document_type,
                DocumentTemplate.is_default.is_(True),
            )
            .values(is_default=False)
        )

    tpl = DocumentTemplate(
        organization_id=org_id,
        module=module,
        name=name,
        document_type=document_type,
        body_html=body_html,
        is_default=is_default,
        created_by=user_id,
    )
    db.add(tpl)
    await db.flush()
    await _log_template_async(db, tpl, user_id=user_id, action=AuditAction.CREATE)
    await db.flush()
    await db.refresh(tpl)
    return tpl


async def update_template_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    module: str,
    name: str | None = None,
    body_html: str | None = None,
    document_type: str | None = None,
    is_default: bool | None = None,
    partials: dict[str, str] | None = None,
    user_id: uuid.UUID | None = None,
) -> DocumentTemplate:
    tpl = await get_template_async(db, org_id, template_id, module)
    if not tpl:
        raise NotFoundException('template', get_current_lang())
    before = _template_snapshot(tpl)
    body_before = tpl.body_html

    if is_default:
        await db.execute(
            update(DocumentTemplate)
            .where(
                DocumentTemplate.organization_id == org_id,
                DocumentTemplate.module == module,
                DocumentTemplate.document_type == tpl.document_type,
                DocumentTemplate.is_default.is_(True),
                DocumentTemplate.id != template_id,
            )
            .values(is_default=False)
        )

    if body_html is not None:
        # Stored verbatim; sanitized at render time (see create_template_async).
        if partials:
            engine = TemplateEngine()
            body_html = engine.inline_includes(body_html, partials)
        tpl.body_html = body_html

    if name is not None:
        tpl.name = name
    if document_type is not None:
        tpl.document_type = document_type
    if is_default is not None:
        tpl.is_default = is_default

    await db.flush()
    after = _template_snapshot(tpl)
    moved: dict[str, object] = {
        key: value for key, value in after.items() if before[key] != value
    }
    # The body is the point of a template and it does not belong in the
    # snapshot, so the entry says it changed rather than showing it.
    if tpl.body_html != body_before:
        moved['body_html'] = 'changed'
    if moved:
        await _log_template_async(
            db,
            tpl,
            user_id=user_id,
            action=AuditAction.UPDATE,
            snapshot={
                'name': tpl.name,
                'module': tpl.module,
                'before': {key: before[key] for key in moved if key in before},
                'after': moved,
            },
        )
    await db.flush()
    await db.refresh(tpl)
    return tpl


async def delete_template_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    module: str,
    user_id: uuid.UUID | None = None,
) -> None:
    tpl = await get_template_async(db, org_id, template_id, module)
    if not tpl:
        raise NotFoundException('template', get_current_lang())
    await _log_template_async(db, tpl, user_id=user_id, action=AuditAction.HARD_DELETE)
    await db.delete(tpl)
    await db.flush()


async def seed_default_templates_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    module: str,
    user_id: uuid.UUID,
    built_ins: list[tuple[str, str, str]],
    partials: dict[str, str] | None = None,
) -> list[DocumentTemplate]:
    engine = TemplateEngine() if partials else None
    existing = await list_templates_async(db, org_id, module)
    existing_names = {t.name for t in existing}
    # A copied built-in is only rendered when it is the default for its
    # document type (PdfServiceBase.try_db_template loads the default only).
    # Make the first seeded template of each type default when the org has
    # none yet, so "Load built-in templates" produces a usable document.
    existing_default_types = {t.document_type for t in existing if t.is_default}
    created_default_types: set[str] = set()

    created: list[DocumentTemplate] = []
    for tpl_name, doc_type, body_html in built_ins:
        if tpl_name in existing_names:
            continue
        # Built-in files are ours — stored verbatim, no sanitizer pass
        # (a seeded copy must render exactly like the file it
        # came from; see create_template_async for why the sanitizer runs
        # at render time instead).
        body = body_html
        if engine and partials:
            body = engine.inline_includes(body, partials)
        is_default = (
            doc_type not in existing_default_types
            and doc_type not in created_default_types
        )
        if is_default:
            created_default_types.add(doc_type)
        tpl = DocumentTemplate(
            organization_id=org_id,
            module=module,
            name=tpl_name,
            document_type=doc_type,
            body_html=body,
            is_default=is_default,
            created_by=user_id,
            # What this copy was made from, and what it looked like then
            # — the only way to tell later that the built-in moved on.
            source_builtin=tpl_name,
            source_checksum=builtin_checksum(body_html),
        )
        db.add(tpl)
        created.append(tpl)
    if created:
        await db.flush()
        for tpl in created:
            await _log_template_async(
                db,
                tpl,
                user_id=user_id,
                action=AuditAction.CREATE,
                snapshot={**_template_snapshot(tpl), 'seeded': True},
            )
        await db.flush()
        for t in created:
            await db.refresh(t)
    return created


# ---------------------------------------------------------------------------
# Built-in provenance
# ---------------------------------------------------------------------------


def builtin_checksum(body_html: str) -> str:
    """Fingerprint of a built-in layout, as stored on the copies made from it."""
    return hashlib.sha256(body_html.encode('utf-8')).hexdigest()


def builtin_has_moved_on(
    template: DocumentTemplate,
    built_ins: list[tuple[str, str, str]],
) -> bool:
    """Whether the built-in a copy was made from has changed since.

    A copy belongs to the organization: nothing here rewrites it, and nothing
    happens on its own. The answer exists so the screen can say what an
    organization otherwise had no way to find out — that it has been printing
    a layout the built-in has since moved past.
    """
    if not template.source_builtin or not template.source_checksum:
        return False
    for name, _doc_type, html in built_ins:
        if name == template.source_builtin:
            return builtin_checksum(html) != template.source_checksum
    return False


async def copy_builtin_alongside_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    module: str,
    user_id: uuid.UUID,
    template_id: uuid.UUID,
    built_ins: list[tuple[str, str, str]],
) -> DocumentTemplate:
    """Make a fresh copy of the built-in an existing copy came from.

    Alongside, never over: the organization's own copy is left exactly as it
    is, including whatever it has edited into it, and the new one does not
    become the default. Which of the two prints stays somebody's decision.
    """
    tpl = await get_template_async(db, org_id, template_id, module)
    if tpl is None:
        raise NotFoundException('template', get_current_lang())
    if not tpl.source_builtin:
        raise catalogue_refusal('template_not_builtin_copy')
    source = next(
        (b for b in built_ins if b[0] == tpl.source_builtin),
        None,
    )
    if source is None:
        raise NotFoundException('template', get_current_lang())

    _name, doc_type, body_html = source
    existing_names = {t.name for t in await list_templates_async(db, org_id, module)}
    name = tpl.source_builtin
    suffix = 2
    while name in existing_names:
        name = f'{tpl.source_builtin} ({suffix})'
        suffix += 1

    fresh = DocumentTemplate(
        organization_id=org_id,
        module=module,
        name=name,
        document_type=doc_type,
        body_html=body_html,
        is_default=False,
        created_by=user_id,
        source_builtin=tpl.source_builtin,
        source_checksum=builtin_checksum(body_html),
    )
    db.add(fresh)
    await db.flush()
    await _log_template_async(
        db,
        fresh,
        user_id=user_id,
        action=AuditAction.CREATE,
        snapshot={
            **_template_snapshot(fresh),
            'copied_from_builtin': tpl.source_builtin,
        },
    )
    await db.flush()
    await db.refresh(fresh)
    return fresh
