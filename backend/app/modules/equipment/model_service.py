"""Equipment model (template) listing and CRUD."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.i18n.service import get_current_lang

from .schemas import EquipmentModelSchema

#: Where a model's category is kept.
#:
#: ``ProductTemplate`` is a Core table and carries no category column — a
#: model is a catalogue entry, and what a *thing* is filed under is the
#: item's business (AGENTS.md §4). The module's own answer therefore lives
#: in the module's own corner of ``meta_data``, beside the rest of what an
#: equipment model knows about itself. Before this, the field was accepted,
#: echoed back in the response as if stored, and dropped: twenty-six models,
#: none with a category, and no refusal anywhere.
_CATEGORY_KEY = 'category_id'


def _category_of(meta: dict[str, Any] | None) -> UUID | None:
    """The category a model's equipment metadata names, if it names one."""
    raw = (meta or {}).get(_CATEGORY_KEY)
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _with_category(
    equipment_meta: dict[str, Any] | None, category_id: UUID | None
) -> dict[str, Any]:
    """The module's metadata with the category written into it."""
    meta = dict(equipment_meta or {})
    if category_id is None:
        meta.pop(_CATEGORY_KEY, None)
    else:
        meta[_CATEGORY_KEY] = str(category_id)
    return meta


async def _category_names(db: AsyncSession, org_id: UUID) -> dict[UUID, str]:
    """Every category the organization can see, by id."""
    from app.core.public_api import core_api

    return {c.id: c.name for c in await core_api.categories.list_async(db, org_id)}


async def list_equipment_models(
    db: AsyncSession, org_id: UUID
) -> list[EquipmentModelSchema]:
    """Return ProductTemplates that have equipment meta_data for the org."""
    from app.core.public_api import core_api

    templates = await core_api.product_templates.list_for_org_async(
        db, org_id, limit=10_000
    )
    # One read for the whole list: the category's name is the only thing a
    # card can show, and the list used to hard-code None for every model, so
    # a category that had been saved would still have been invisible here.
    names = await _category_names(db, org_id)

    results = []
    for t in templates:
        if not t.meta_data or 'equipment' not in t.meta_data:
            continue
        equipment_meta = t.meta_data['equipment']
        category_id = _category_of(equipment_meta)
        results.append(
            EquipmentModelSchema(
                id=t.id,
                name=t.name,
                brand=t.brand,
                image_url=t.image_url,
                description=t.description,
                category_id=category_id,
                category_name=names.get(category_id) if category_id else None,
                equipment_meta=equipment_meta,
            )
        )

    results.sort(key=lambda x: x.name)
    return results


async def create_equipment_model(
    db: AsyncSession,
    org_id: UUID,
    name: str,
    brand: str | None = None,
    description: str | None = None,
    image_url: str | None = None,
    category_id: UUID | None = None,
    equipment_meta: dict[str, Any] | None = None,
    *,
    user_id: UUID,
) -> EquipmentModelSchema:
    from app.core.public_api import core_api

    stored_meta = _with_category(equipment_meta, category_id)
    tpl = await core_api.product_templates.create_async(
        db,
        org_id,
        name,
        brand=brand,
        description=description,
        image_url=image_url,
        meta_data={'equipment': stored_meta},
        user_id=user_id,
    )
    saved = tpl.meta_data.get('equipment', {}) if tpl.meta_data else {}
    saved_category = _category_of(saved)
    names = await _category_names(db, org_id) if saved_category else {}
    return EquipmentModelSchema(
        id=tpl.id,
        name=tpl.name,
        brand=tpl.brand,
        image_url=tpl.image_url,
        description=tpl.description,
        # Read back from what was stored, never echoed from the request: the
        # response used to confirm a category no row carried.
        category_id=saved_category,
        category_name=names.get(saved_category) if saved_category else None,
        equipment_meta=saved,
    )


async def update_equipment_model(
    db: AsyncSession,
    org_id: UUID,
    model_id: UUID,
    name: str | None = None,
    brand: str | None = None,
    description: str | None = None,
    image_url: str | None = None,
    category_id: UUID | None = None,
    equipment_meta: dict[str, Any] | None = None,
    *,
    user_id: UUID,
) -> EquipmentModelSchema:
    from app.core.public_api import core_api

    existing = await core_api.product_templates.get_async(db, org_id, model_id)
    if not existing:
        raise NotFoundException('template', get_current_lang())

    existing_equipment = (existing.meta_data or {}).get('equipment', {})
    # The category travels inside the module's metadata, so a request that
    # changes only the category still has to write that block — otherwise
    # `meta_data=None` means "leave it" and the change is dropped in silence,
    # which is the defect this closes.
    base = equipment_meta if equipment_meta is not None else existing_equipment
    stored_meta = _with_category(base, category_id)
    meta = {**(existing.meta_data or {}), 'equipment': stored_meta}

    tpl = await core_api.product_templates.update_async(
        db,
        model_id,
        org_id,
        name=name,
        brand=brand,
        description=description,
        image_url=image_url,
        meta_data=meta,
        user_id=user_id,
    )
    eq_meta = tpl.meta_data.get('equipment', {}) if tpl.meta_data else {}
    saved_category = _category_of(eq_meta)
    names = await _category_names(db, org_id) if saved_category else {}
    return EquipmentModelSchema(
        id=tpl.id,
        name=tpl.name,
        brand=tpl.brand,
        image_url=tpl.image_url,
        description=tpl.description,
        category_id=saved_category,
        category_name=names.get(saved_category) if saved_category else None,
        equipment_meta=eq_meta,
    )


async def delete_equipment_model(
    db: AsyncSession, org_id: UUID, model_id: UUID, user_id: UUID
) -> bool:
    from app.core.public_api import core_api

    existing = await core_api.product_templates.get_async(db, org_id, model_id)
    if not existing:
        return False
    if existing.organization_id != org_id and existing.organization_id is not None:
        return False
    if not existing.meta_data or 'equipment' not in existing.meta_data:
        return False

    await core_api.product_templates.delete_async(db, model_id, org_id, user_id)
    return True


async def clone_equipment_model(
    db: AsyncSession,
    org_id: UUID,
    model_id: UUID,
    new_name: str,
    *,
    user_id: UUID,
) -> EquipmentModelSchema:
    from app.core.public_api import core_api

    existing = await core_api.product_templates.get_async(db, org_id, model_id)
    if not existing:
        raise NotFoundException('template', get_current_lang())
    if existing.organization_id != org_id and existing.organization_id is not None:
        # 404 (not 403) on purpose: do not leak template existence across orgs.
        raise NotFoundException('template', get_current_lang())
    if not existing.meta_data or 'equipment' not in existing.meta_data:
        raise ServiceRejectionError('not_an_equipment_model')

    eq_meta = existing.meta_data.get('equipment', {})
    tpl = await core_api.product_templates.create_async(
        db,
        org_id,
        new_name,
        brand=existing.brand,
        description=existing.description,
        image_url=existing.image_url,
        meta_data={'equipment': eq_meta},
        user_id=user_id,
    )
    return EquipmentModelSchema(
        id=tpl.id,
        name=tpl.name,
        brand=tpl.brand,
        image_url=tpl.image_url,
        description=tpl.description,
        category_id=None,
        category_name=None,
        equipment_meta=eq_meta,
    )
