from abc import ABC, abstractmethod
from typing import Any, TypeVar
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class BaseContribution(ABC):
    """Base class for all module contributions."""

    pass


class QuotaProvider(BaseContribution):
    """A provider that enforces business limits (SaaS quotas)."""

    @abstractmethod
    async def check_organization_limit(
        self, organization_id: UUID, limit_type: str, db: Any
    ) -> bool:
        """Returns True if the organization is allowed to perform the action."""
        pass

    @abstractmethod
    async def get_limit_value(
        self, organization_id: UUID, limit_type: str, db: Any
    ) -> int | float | None:
        """Returns the current limit value for display."""
        pass


class UploadPathResolver(BaseContribution):
    """Resolves ownership metadata for a stored file served under /uploads/.

    Core serves every uploaded file through a single route (``/uploads/{path}``),
    but the bookkeeping that records a file's existence and owning organization
    differs per upload family (item covers, recipe covers, item attachments,
    module attachments, …). Each resolver owns one path family: it inspects the
    path, verifies the caller's organization owns it, and returns enough
    metadata to serve the file — or ``None`` when the path is not for it.
    """

    @abstractmethod
    async def resolve(
        self,
        db: Any,
        file_path: str,
        organization_id: UUID,
    ) -> 'OwnedFileMeta | None':
        """Return metadata if this resolver owns ``file_path``, else ``None``."""
        raise NotImplementedError


class OwnedFileMeta(BaseContribution):
    """Metadata returned by an UploadPathResolver for an owned file.

    ``content_type``/``display_name`` are passed through to FileResponse.
    """

    def __init__(
        self,
        content_type: str | None = None,
        display_name: str | None = None,
    ) -> None:
        self.content_type = content_type
        self.display_name = display_name


class ContributionRegistry:
    """Registry for various extension points (contribution points)."""

    # All known extension points with documentation on expected contribution type.
    # Register unknown points will emit a warning — most likely a typo.
    #
    # A stable point is one backend code reads (tests/unit/
    # test_contribution_registry.py holds every one to a reader). Scan
    # providers register through ``scan_registry`` and a dashboard widget is
    # a frontend slot, so ``scan_providers`` and ``dashboard_widgets`` are
    # not points: listed here, a registration to them was accepted in
    # silence and reached nothing; unlisted, it warns.
    KNOWN_POINTS: frozenset[str] = frozenset(
        {
            'enrichment_providers',  # BaseContribution — item data enrichment (@experimental, no consumer)
            'quota_providers',  # QuotaProvider    — SaaS quota enforcement
            'item_interceptors',  # ItemInterceptor  — mutate/block item CRUD operations
            'storage_interceptors',  # StorageInterceptor — mutate/block storage CRUD operations
            'category_interceptors',  # CategoryInterceptor — mutate/block category CRUD operations
            'item_actions',  # ItemAction       — context-menu actions on single items (@experimental, no consumer)
            'settings_panels',  # SettingsPanel    — module config UI declarations (@experimental, no consumer)
            'upload_path_resolvers',  # UploadPathResolver — ownership for /uploads/ serving
        }
    )

    # Contribution points with no consumer yet — may change before stabilization.
    # Modules registering here get an info-level log instead of a warning.
    EXPERIMENTAL_POINTS: frozenset[str] = frozenset(
        {
            'enrichment_providers',
            'item_actions',
            'settings_panels',
        }
    )

    def __init__(self) -> None:
        self._contributions: dict[str, list[Any]] = {
            point: [] for point in self.KNOWN_POINTS
        }

    def register(self, point: str, contribution: BaseContribution) -> None:
        """Register a contribution to a specific extension point.

        Warns if the point is not in KNOWN_POINTS — likely a typo.
        Logs info for experimental points that have no consumer yet.
        """
        if point not in self.KNOWN_POINTS:
            logger.warning(
                'Registering to unknown contribution point: %s. Known points: %s',
                point,
                ', '.join(sorted(self.KNOWN_POINTS)),
            )
        elif point in self.EXPERIMENTAL_POINTS:
            logger.info(
                'Registering to experimental contribution point: %s — no consumer yet.',
                point,
            )
        if point not in self._contributions:
            self._contributions[point] = []
        self._contributions[point].append(contribution)

    def get(self, point: str) -> list[Any]:
        """Returns all contributions for a specific point."""
        return self._contributions.get(point, [])

    async def check_quota(
        self, organization_id: UUID, limit_type: str, db: Any
    ) -> bool:
        """Helper to check all registered quota providers. Returns False if any provider denies."""
        providers = self.get('quota_providers')
        if not providers:
            return True  # Default to allow if no quota module installed

        for provider in providers:
            if not await provider.check_organization_limit(
                organization_id, limit_type, db
            ):
                return False
        return True


# Global singleton
contribution_registry = ContributionRegistry()
