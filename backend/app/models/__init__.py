# Core-shared model living in app.core (document_templates table) — register
# it with the rest of the metadata so module FKs (e.g.
# document_profiles.default_template_id) always resolve.
from app.core.template_models import DocumentTemplate  # noqa: F401
from app.models.ai_connection import AiConnection
from app.models.ai_usage_log import AIUsageLog
from app.models.announcement import Announcement
from app.models.audit_log import AuditLog
from app.models.category import Category
from app.models.email_job import EmailJob  # noqa: F401
from app.models.event_delivery import EventDelivery
from app.models.event_outbox import EventOutbox  # noqa: F401
from app.models.item import Item
from app.models.item_attachment import ItemAttachment
from app.models.item_history import ItemHistory
from app.models.item_import_job import ItemImportJob  # noqa: F401
from app.models.label_pool import LabelPool
from app.models.location_relocation import LocationRelocation
from app.models.module_installation import ModuleInstallation  # noqa: F401
from app.models.notification import Notification
from app.models.organization import Organization, OrganizationInvitation
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.role import Role, UserRole
from app.models.stock_anchor import StockAnchor
from app.models.stock_ledger_total import StockLedgerTotal
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.stock_reservation import StockReservation
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.system_setting import SystemSetting
from app.models.uom import Uom, UomCategory
from app.models.user import User

__all__ = [
    'AiConnection',
    'AIUsageLog',
    'User',
    'Organization',
    'OrganizationInvitation',
    'StorageType',
    'StorageLocation',
    'Category',
    'Item',
    'ItemHistory',
    'LabelPool',
    'LocationRelocation',
    'ItemAttachment',
    'Notification',
    'Announcement',
    'AuditLog',
    'SystemSetting',
    'UomCategory',
    'Uom',
    'ProductTemplate',
    'Role',
    'UserRole',
    'StockAnchor',
    'StockLedgerTotal',
    'StockLot',
    'StockMove',
    'StockReservation',
    'StockValuationLayer',
    'Partner',
    'EventDelivery',
]
