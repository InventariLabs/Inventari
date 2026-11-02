from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.logging import get_logger


@runtime_checkable
class ScanProvider(Protocol):
    """Protocol for classes that provide scanning capabilities."""

    async def can_handle(self, code: str) -> bool: ...

    async def handle(
        self, code: str, user: UserContextDTO, db: AsyncSession
    ) -> Any: ...


class ScanRegistry:
    """Registry for scan providers."""

    def __init__(self) -> None:
        self._providers: list[tuple[ScanProvider, int]] = []

    def register(self, provider: ScanProvider, priority: int = 100) -> None:
        from app.core.logging import get_logger

        logger = get_logger(__name__)
        provider_name = provider.__class__.__name__
        logger.info(
            f'✅ Registered ScanProvider: {provider_name} (priority: {priority})'
        )
        self._providers.append((provider, priority))
        self._providers.sort(key=lambda x: x[1])

    _MAX_CODE_LENGTH = 500
    _ALLOWED_CODE_PATTERN = __import__('re').compile(r'^[\w\-.:/?=&%#+@]+$')

    async def scan(self, code: str, user: UserContextDTO, db: AsyncSession) -> Any:
        logger = get_logger(__name__)
        logger.info('[ScanRegistry] Incoming code: %s', code)

        if not code or len(code) > self._MAX_CODE_LENGTH:
            logger.warning('[ScanRegistry] Code rejected: empty or exceeds max length')
            return None
        if not self._ALLOWED_CODE_PATTERN.match(code):
            logger.warning(
                '[ScanRegistry] Code rejected: contains disallowed characters'
            )
            return None

        clean_code = extract_scan_code(code)
        logger.info('[ScanRegistry] Cleaned code: %s', clean_code)

        for provider, priority in self._providers:
            if await provider.can_handle(clean_code):
                logger.info(
                    '[ScanRegistry] Provider %s (priority %s) is handling code',
                    provider.__class__.__name__,
                    priority,
                )
                result = await provider.handle(clean_code, user, db)
                if result:
                    return result

        logger.warning('[ScanRegistry] No provider handled code: %s', clean_code)
        return None


scan_registry = ScanRegistry()


def extract_scan_code(raw_code: str) -> str:
    """The code a scan actually resolves, as the registry sees it.

    A QR wraps the real code in a scan address (see
    :mod:`app.core.scan_links`, which owns both shapes it has printed); the
    registry and the labels router's 404 messaging must agree on the value
    that was looked up, so the extraction lives here instead of being
    re-implemented at the call site.
    """
    from app.core.scan_links import scanned_code

    code = scanned_code(raw_code)

    from app.core.barcode import normalize_barcode

    normalized = normalize_barcode(code)
    if normalized:
        code = normalized
    return code
