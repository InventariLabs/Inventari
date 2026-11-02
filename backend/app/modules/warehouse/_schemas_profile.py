"""Document Profile Pydantic schemas (update + read).

Extracted from ``schemas.py`` to keep that file under the 400-LOC lint limit.
``schemas.py`` re-exports both classes (noqa: F401) so existing callers
(``_profile_router.py``, ``document_profile_service.py``) keep importing from
``.schemas`` unchanged.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .models import DocumentType


class DocumentProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    value_tracking_enabled: bool | None = None
    tax_handling: str | None = None
    default_tax_rate: Decimal | None = Field(
        default=None, max_digits=5, decimal_places=2
    )
    require_partner_tax_id: bool | None = None
    require_unit_price: bool | None = None
    confirm_shelf_by_scan: bool | None = None
    numbering_format: str | None = Field(default=None, max_length=100)
    number_padding: int | None = Field(default=None, ge=3, le=6)
    type_labels: dict[str, str] | None = None
    default_unit: str | None = Field(default=None, max_length=20)
    visible_line_fields: list[str] | None = None
    print_template: str | None = Field(default=None, max_length=50)
    # The organization's own template (a seeded copy of a built-in layout,
    # or one written from scratch) that the printout renders instead of the
    # filesystem family when set. ``print_template`` keeps the preset
    # family for when no user template is chosen.
    default_template_id: UUID | None = None
    default_currency: str | None = Field(default=None, max_length=3)
    # The shelf goods coded DAMAGE or QUALITY_HOLD are received onto when they
    # carry no batch to hold back; ``null`` names none.
    quarantine_location_id: UUID | None = None
    approval_threshold: Decimal | None = Field(
        default=None, max_digits=14, decimal_places=2, ge=0
    )
    approval_required_for_types: list[str] | None = None
    # The registered pick-order strategy the warehouse is walked by;
    # ``null`` is "nothing chosen", which walks the default. A name no
    # strategy answers any more (its module went away) also walks the
    # default — the choice survives whatever happened to its module.
    pick_order_strategy: str | None = Field(default=None, max_length=50)
    # Carrier name → the carrier's tracking page with ``{tracking_number}``
    # where the number goes. Read before the built-in templates.
    tracking_url_templates: dict[str, str] | None = None

    @field_validator('tracking_url_templates')
    @classmethod
    def validate_tracking_url_templates(
        cls, v: dict[str, str] | None
    ) -> dict[str, str] | None:
        if v is None:
            return v
        from app.core.exceptions import ServiceRejectionError

        templates: dict[str, str] = {}
        for carrier, template in v.items():
            name, url = carrier.strip(), template.strip()
            if (
                not name
                or len(name) > 100
                or len(url) > 500
                or not url.startswith(('https://', 'http://'))
                or '{tracking_number}' not in url
            ):
                raise ServiceRejectionError(
                    'document_tracking_template_invalid', carrier=carrier
                )
            templates[name] = url
        return templates

    @field_validator('tax_handling')
    @classmethod
    def validate_tax_handling(cls, v: str | None) -> str | None:
        if v is not None and v not in {'NONE', 'SIMPLE_RATE', 'PER_LINE_RATE'}:
            raise ValueError('tax_handling must be NONE, SIMPLE_RATE, or PER_LINE_RATE')
        return v

    @model_validator(mode='after')
    def validate_type_labels(self) -> DocumentProfileUpdate:
        if self.type_labels is not None:
            allowed_keys = {doc_type.value for doc_type in DocumentType}
            for key in self.type_labels:
                if key not in allowed_keys:
                    raise ValueError(
                        'type_labels keys must be IN, OUT, INT, INTERNAL_IN, '
                        'INTERNAL_OUT, ADJUSTMENT, CORRECTION, or SCRAP; '
                        f'got {key}'
                    )
        return self


class DocumentProfileSchema(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    value_tracking_enabled: bool
    tax_handling: str
    default_tax_rate: Decimal | None
    require_partner_tax_id: bool | None
    require_unit_price: bool
    confirm_shelf_by_scan: bool
    numbering_format: str
    number_padding: int
    type_labels: dict[str, str] | None
    default_unit: str
    visible_line_fields: list[str] | None
    print_template: str
    # The organization's own template rendered on the printout when set.
    default_template_id: UUID | None
    default_currency: str | None
    quarantine_location_id: UUID | None
    approval_threshold: Decimal | None
    approval_required_for_types: list[str] | None
    pick_order_strategy: str | None = None
    tracking_url_templates: dict[str, str] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PickOrderStrategySchema(BaseModel):
    """One registered pick order, for the warehouse settings' chooser.

    ``label_key`` is where the owning module's catalogue holds the words for
    it — the full form (``<module>:pickOrderStrategies.<name>``) the screen
    reads and falls back to the bare name on. ``is_default`` marks the walk
    used when nothing is chosen.
    """

    name: str
    module: str
    label_key: str
    is_default: bool
