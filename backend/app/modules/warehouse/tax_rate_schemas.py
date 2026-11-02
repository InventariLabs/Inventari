from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaxRateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    code: str | None = Field(default=None, max_length=10)
    country: str | None = Field(default=None, max_length=2)
    is_default: bool = False


class TaxRateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    rate: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=5, decimal_places=2
    )
    code: str | None = Field(default=None, max_length=10)
    country: str | None = Field(default=None, max_length=2)
    is_default: bool | None = None


class TaxRateOut(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    rate: Decimal
    code: str | None
    country: str | None
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CountryRateOffer(BaseModel):
    name: str
    rate: Decimal
    is_standard: bool


class CountryRatesOut(BaseModel):
    country: str | None
    rates: list[CountryRateOffer]


class NameTaxRate(BaseModel):
    tax_rate_id: UUID | None


class ProductTaxRateOut(BaseModel):
    product_template_id: UUID
    tax_rate_id: UUID | None
    category_tax_rate_id: UUID | None


class CategoryTaxRateOut(BaseModel):
    category_id: UUID
    tax_rate_id: UUID


class TaxSummaryLine(BaseModel):
    tax_rate: Decimal
    tax_code: str | None
    net: Decimal
    tax: Decimal
    gross: Decimal
    line_count: int


class TaxSummaryResponse(BaseModel):
    org_tax_id: str | None
    org_country: str | None
    currency: str | None
    lines: list[TaxSummaryLine]
    total_net: Decimal
    total_tax: Decimal
    total_gross: Decimal
