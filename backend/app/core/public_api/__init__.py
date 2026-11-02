from app.core.public_api.admin import CoreAdminAPI
from app.core.public_api.ai_connections import CoreAIConnectionsAPI
from app.core.public_api.ai_usage import CoreAIUsageAPI
from app.core.public_api.announcements import CoreAnnouncementsAPI
from app.core.public_api.attachments import CoreAttachmentsAPI
from app.core.public_api.audit_log import CoreAuditLogAPI
from app.core.public_api.categories import CoreCategoriesAPI
from app.core.public_api.email import CoreEmailAPI
from app.core.public_api.events import CoreEventsAPI
from app.core.public_api.file_storage import CoreFileStorageAPI
from app.core.public_api.item_history import CoreItemHistoryAPI
from app.core.public_api.items import CoreItemsAPI
from app.core.public_api.labels import CoreLabelsAPI
from app.core.public_api.llm import CoreLlmAPI
from app.core.public_api.location_types import CoreStorageTypesAPI
from app.core.public_api.locations import CoreStoragesAPI
from app.core.public_api.notifications import CoreNotificationsAPI
from app.core.public_api.organizations import CoreOrganizationsAPI
from app.core.public_api.partners import CorePartnersAPI
from app.core.public_api.pdf import CorePdfAPI
from app.core.public_api.periods import CorePeriodsAPI
from app.core.public_api.product_templates import CoreProductTemplatesAPI
from app.core.public_api.queries import CoreQueriesAPI
from app.core.public_api.roles import CoreRolesAPI
from app.core.public_api.scheduler import CoreSchedulerAPI
from app.core.public_api.secrets import CoreSecretsAPI
from app.core.public_api.settings import CoreSettingsAPI
from app.core.public_api.stock import CoreStockAPI
from app.core.public_api.stock_moves import CoreStockMovesAPI
from app.core.public_api.templates import CoreTemplatesAPI
from app.core.public_api.uoms import CoreUomsAPI
from app.core.public_api.users import CoreUsersAPI
from app.core.public_api.valuation import CoreValuationAPI


class CoreAPI:
    """Facade exposing stable, module-safe Core API endpoints.

    Transaction semantics: All write methods use ``db.flush()``, never
    ``db.commit()``.  The caller (router / module handler) is responsible for
    committing the transaction.

    Exception — bulk import (``app.services.items._import``): the CSV/XLSX
    import commits in batches of 50 rows (large datasets) and wraps each row
    in a savepoint so a failed row rolls back only itself. All other
    paths are flush-only.
    """

    def __init__(self) -> None:
        self.ai_connections = CoreAIConnectionsAPI()
        self.ai_usage = CoreAIUsageAPI()
        self.admin = CoreAdminAPI()
        self.announcements = CoreAnnouncementsAPI()
        self.audit_log = CoreAuditLogAPI()
        self.items = CoreItemsAPI()
        self.item_history = CoreItemHistoryAPI()
        self.attachments = CoreAttachmentsAPI()
        self.labels = CoreLabelsAPI()
        self.llm = CoreLlmAPI()
        self.organizations = CoreOrganizationsAPI()
        self.roles = CoreRolesAPI()
        self.scheduler = CoreSchedulerAPI()
        self.locations = CoreStoragesAPI()
        self.location_types = CoreStorageTypesAPI()
        self.settings = CoreSettingsAPI()
        self.categories = CoreCategoriesAPI()
        self.email = CoreEmailAPI()
        self.events = CoreEventsAPI()
        self.notifications = CoreNotificationsAPI()
        self.users = CoreUsersAPI()
        self.file_storage = CoreFileStorageAPI()
        self.secrets = CoreSecretsAPI()
        self.uoms = CoreUomsAPI()
        self.product_templates = CoreProductTemplatesAPI()
        self.queries = CoreQueriesAPI()
        self.partners = CorePartnersAPI()
        self.pdf = CorePdfAPI()
        self.periods = CorePeriodsAPI()
        self.stock = CoreStockAPI()
        self.stock_moves = CoreStockMovesAPI()
        self.templates = CoreTemplatesAPI()
        self.valuation = CoreValuationAPI()

        # The register is the single source of what is deprecated: entries
        # added there start warning at runtime without another edit here.
        from app.core._core_api_deprecations import install_runtime_warnings

        install_runtime_warnings(self)


core_api = CoreAPI()

__all__ = [
    'CoreAPI',
    'CoreAIConnectionsAPI',
    'CoreAIUsageAPI',
    'CoreAdminAPI',
    'CoreAnnouncementsAPI',
    'CoreAttachmentsAPI',
    'CoreAuditLogAPI',
    'CoreCategoriesAPI',
    'CoreEmailAPI',
    'CoreEventsAPI',
    'CoreFileStorageAPI',
    'CoreItemHistoryAPI',
    'CoreItemsAPI',
    'CoreLabelsAPI',
    'CoreLlmAPI',
    'CoreNotificationsAPI',
    'CoreOrganizationsAPI',
    'CorePartnersAPI',
    'CorePdfAPI',
    'CorePeriodsAPI',
    'CoreProductTemplatesAPI',
    'CoreQueriesAPI',
    'CoreRolesAPI',
    'CoreSchedulerAPI',
    'CoreSecretsAPI',
    'CoreSettingsAPI',
    'CoreStockAPI',
    'CoreStockMovesAPI',
    'CoreStorageTypesAPI',
    'CoreStoragesAPI',
    'CoreTemplatesAPI',
    'CoreUomsAPI',
    'CoreUsersAPI',
    'CoreValuationAPI',
    'core_api',
]
