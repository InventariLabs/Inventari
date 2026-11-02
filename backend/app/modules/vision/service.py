"""Reading a label — the part that is vision's own.

Everything generic moved to Core (``core_api.llm.extract_from_images_async``):
quota, connection resolution, prompt shape, the retry when an answer does not
fit, the usage row per attempt. What is left here is the question — *this is
a photograph of a label; read what is printed on it* — plus the folding-in of
whatever other enabled modules asked to have read at the same time.

Gone with the move: ``storage_type``, which defaulted to ``'PANTRY'`` and
steered the prompt with sentences about frozen meat and dairy. A shelf's
temperature is one vertical's furniture, and the label already says what it
is; the scan's intent now travels as the ``context_tag`` the label was
printed with, which is a fact about the sticker rather than a guess about the
room.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import create_model
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.scan_registry import scan_registry

from ._image_helpers import compress_image
from .field_contributions import LabelFieldContribution, registered_label_fields
from .schemas import VisionExtractResponse, VisionExtractResult

logger = get_logger(__name__)

_PURPOSE = 'vision.extract'

_INSTRUCTIONS = (
    'These photographs all show the same item, or parts of one label on it. '
    'Read what is printed and combine information from every photograph. '
    'Do not infer anything that is not legible in the pictures.'
)


class VisionService:
    """Label extraction. Static methods — the service holds no state."""

    @staticmethod
    def _compress_image(
        image_bytes: bytes,
        max_size: tuple[int, int] = (1600, 1600),
        quality: int = 85,
    ) -> bytes:
        """Compresses image and returns JPEG bytes."""
        return compress_image(image_bytes, max_size, quality)

    @staticmethod
    async def extract_from_bytes_list(
        image_bytes_list: Sequence[bytes],
        db: AsyncSession,
        organization_id: str | UUID,
        user_id: str | UUID | None = None,
        context_tag: str | None = None,
        action_type: str = 'extract_label',
        user: UserContextDTO | None = None,
        disable_reasoning: bool = True,
    ) -> VisionExtractResponse:
        """Read a label off one or more photographs of the same item.

        Args:
            context_tag: What the label was printed for. Decides which
                modules' extra fields are worth asking about — an asset
                sticker is never asked for a nutrition table.
            user: When given, a barcode legible in the photograph is put
                through the scan registry, so a photographed package is
                enriched by the same resolvers a scanned one is.
            disable_reasoning: Passed through to Core. Callers have no reason
                to change it; the model-comparison harness does, because a
                default nobody can vary is a default nobody can check.
        """
        org_uuid = (
            organization_id
            if isinstance(organization_id, UUID)
            else UUID(organization_id)
        )
        contributions = await _applicable_contributions(db, org_uuid, context_tag)
        schema = _compose_schema(contributions)
        instructions = '\n'.join(
            [_INSTRUCTIONS, *(c.instructions for c in contributions)]
        )

        raw = await core_api.llm.extract_from_images_async(
            db,
            org_uuid,
            purpose_key=_PURPOSE,
            schema=schema,
            instructions=instructions,
            images=list(image_bytes_list),
            action_type=action_type,
            user_id=user_id,
            disable_reasoning=disable_reasoning,
        )
        response = _split_response(raw, contributions)
        if user is not None:
            response.resolved = await _resolve_barcode(response.barcode, user, db)
        return response

    @staticmethod
    async def extract_contributed_fields(
        module: str,
        image_bytes_list: Sequence[bytes],
        db: AsyncSession,
        organization_id: str | UUID,
        user_id: str | UUID | None = None,
        action_type: str = 'extract_fields',
    ) -> dict[str, Any]:
        """Read only *module*'s contributed group off the photographs.

        For a picture that is not a label at all — a nutrition table, a rating
        plate — where asking for a product name would be noise. Vision still
        holds no opinion about what the group contains: it is looked up by the
        contributing module's own key.

        Raises:
            RuntimeError: no enabled module registered fields under *module*.
        """
        contribution = next(
            (c for c in registered_label_fields() if c.module == module), None
        )
        if contribution is None:
            raise RuntimeError(f'No label fields are registered by module "{module}"')

        org_uuid = (
            organization_id
            if isinstance(organization_id, UUID)
            else UUID(organization_id)
        )
        # A table photographed close up is legible far below full resolution,
        # and the caller here may be an API client that did not shrink it.
        compressed = [
            VisionService._compress_image(image, max_size=(1200, 1200))
            for image in image_bytes_list
        ]
        result = await core_api.llm.extract_from_images_async(
            db,
            org_uuid,
            purpose_key=_PURPOSE,
            schema=contribution.schema,
            instructions=contribution.instructions,
            images=compressed,
            action_type=action_type,
            user_id=user_id,
        )
        return result.model_dump()

    @staticmethod
    async def extract_from_base64_list(
        images_base64: Sequence[str],
        db: AsyncSession,
        organization_id: str | UUID,
        user_id: str | UUID | None = None,
        context_tag: str | None = None,
        action_type: str = 'extract_label',
        disable_reasoning: bool = True,
    ) -> VisionExtractResponse:
        """Base64 variant. Decodes once and delegates (no round-trips)."""
        return await VisionService.extract_from_bytes_list(
            [base64.b64decode(b64) for b64 in images_base64],
            db,
            organization_id,
            user_id=user_id,
            context_tag=context_tag,
            action_type=action_type,
            disable_reasoning=disable_reasoning,
        )


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


async def _applicable_contributions(
    db: AsyncSession, organization_id: UUID, context_tag: str | None
) -> list[LabelFieldContribution]:
    """The contributions this particular scan should carry.

    Both gates matter and for different reasons: the module gate keeps a
    switched-off feature from spending tokens, the intent gate keeps a
    switched-on one from asking a question the photograph cannot answer.
    """
    applicable = []
    for contribution in registered_label_fields():
        if not contribution.applies_to(context_tag):
            continue
        if await core_api.organizations.is_module_enabled_async(
            db, organization_id, contribution.module
        ):
            applicable.append(contribution)
    return applicable


def _compose_schema(
    contributions: Sequence[LabelFieldContribution],
) -> type[VisionExtractResult]:
    """The label schema with one nested optional group per contribution."""
    if not contributions:
        return VisionExtractResult
    fields: dict[str, Any] = {
        contribution.module: (contribution.schema | None, None)
        for contribution in contributions
    }
    composed = create_model(
        'ComposedLabelExtraction', __base__=VisionExtractResult, **fields
    )
    return composed


async def _resolve_barcode(
    barcode: str | None, user: UserContextDTO, db: AsyncSession
) -> dict[str, Any] | None:
    """Hand a barcode the model read to the same chain a scanner feeds.

    Scanning a barcode has always run it past the registered providers, one of
    which looks it up in the product database. Reading the *same* barcode off
    a photograph did not, so the two ways of pointing a camera at one package
    gave different answers — the scan filled in the manufacturer\'s data and
    the photo did not.

    Failure is silence on purpose: an unrecognised code, a resolver whose
    source is unavailable, a provider that raises — the user still gets
    everything the model read. Enrichment that can block a save is worse than
    no enrichment.
    """
    if not barcode:
        return None
    try:
        result = await scan_registry.scan(barcode, user, db)
    except Exception as exc:  # noqa: BLE001 — enrichment must never block a read
        logger.warning('[Vision] Resolver chain failed for %s: %s', barcode, exc)
        return None

    summary = getattr(result, 'stock_summary', None) or {}
    template = summary.get('template') if isinstance(summary, dict) else None
    return template if isinstance(template, dict) else None


def _split_response(
    raw: VisionExtractResult, contributions: Sequence[LabelFieldContribution]
) -> VisionExtractResponse:
    """Separate the label's own fields from the contributed groups."""
    data = raw.model_dump()
    extra: dict[str, Any] = {}
    for contribution in contributions:
        value = data.pop(contribution.module, None)
        if value:
            extra[contribution.module] = value
    return VisionExtractResponse(**data, extra=extra)
