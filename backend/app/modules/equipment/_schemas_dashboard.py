from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.core.template_schemas import (
    DocumentTemplateCreate as _CoreDocumentTemplateCreate,
)
from app.core.template_schemas import (
    DocumentTemplateUpdate as _CoreDocumentTemplateUpdate,
)

EquipmentDocumentType = Literal['CHECKOUT', 'CHECKIN', 'UNIVERSAL']
"""The protocols this module knows how to print, and nothing else.

``document_type`` is a plain string on the shared table on purpose — each
module means something different by it. What the shared *write* schema then
did was accept any fifty characters, defaulting to 'DEFAULT', which is not a
protocol this module renders: a template saved under it is inert, and the
screen that lists it has no label for it, so it printed the raw token. The
vocabulary belongs to the module, so the module is where it is declared.
"""


class RecentActivityItem(BaseModel):
    item_name: str
    action: str
    timestamp: str


class ByCategory(BaseModel):
    category_name: str
    count: int


class WarrantyAlert(BaseModel):
    item_id: UUID
    item_name: str
    category_code: str
    serial_number: str | None
    warranty_until: date
    days_remaining: int
    assigned_to: str | None


class EquipmentDashboard(BaseModel):
    total_assets: int
    active_assignments: int
    in_maintenance: int
    retired: int
    by_status: dict[str, int]
    by_category: list[ByCategory]
    recent_activity: list[RecentActivityItem]
    warranty_alerts: list[WarrantyAlert]
    # warranties that already lapsed — sorted oldest expiry first.
    expired_warranty_alerts: list[WarrantyAlert] = []


class DocumentTemplateCreate(_CoreDocumentTemplateCreate):
    document_type: EquipmentDocumentType = 'CHECKOUT'


class DocumentTemplateUpdate(_CoreDocumentTemplateUpdate):
    document_type: EquipmentDocumentType | None = None
