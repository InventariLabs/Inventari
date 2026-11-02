"""Vision's public API for other modules.

One entry point, per the cross-module contract in AGENTS.md: a module that
wants extra fields read off a photographed label declares them here and never
touches vision's service, router or schemas.

Graceful degradation is automatic rather than promised — a registration on a
disabled vision module simply sits in a dict nothing reads, and the
contributing module's own screens keep working.
"""

from __future__ import annotations

from pydantic import BaseModel

from .field_contributions import (
    PRODUCT_CONTEXT,
    LabelFieldContribution,
    register_label_fields,
)

__all__ = ['PRODUCT_CONTEXT', 'VisionAPI', 'vision_api']


class VisionAPI:
    """Cross-module surface of the vision module."""

    PRODUCT_CONTEXT = PRODUCT_CONTEXT

    def register_label_fields(
        self,
        module: str,
        schema: type[BaseModel],
        instructions: str,
        context_tags: frozenset[str] | None = None,
    ) -> None:
        """Ask for *schema* to be read alongside the label's identity fields.

        Args:
            module: The contributing module. Gates the contribution and names
                the key its values arrive under in the response's ``extra``.
            schema: A Pydantic model of optional fields. Their ``description``
                text is what the model is actually asked, so write it for a
                reader of the photograph.
            instructions: One sentence on when these fields apply — the place
                to say "only if a clear table is visible".
            context_tags: The label intents this applies to; ``None`` for all.
        """
        register_label_fields(
            LabelFieldContribution(
                module=module,
                schema=schema,
                instructions=instructions,
                context_tags=context_tags,
            )
        )


vision_api = VisionAPI()
