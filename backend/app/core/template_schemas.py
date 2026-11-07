"""Shared Pydantic schemas for DocumentTemplate."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: The ceiling on a template's body. One constant, two doors: the editor's
#: save and the import's file both refuse past it, so a template cannot
#: arrive by one door that the other would refuse to save.
BODY_MAX_LENGTH = 51200


class DocumentTemplateCreate(BaseModel):
    name: str = Field(max_length=255)
    module: str = Field(pattern='^(equipment|warehouse|purchase_orders)$')
    document_type: str = Field(default='DEFAULT', max_length=50)
    body_html: str = Field(max_length=BODY_MAX_LENGTH)
    is_default: bool = False


class DocumentTemplateUpdate(BaseModel):
    name: str | None = None
    document_type: str | None = None
    body_html: str | None = Field(default=None, max_length=BODY_MAX_LENGTH)
    is_default: bool | None = None


class DocumentTemplateSchema(BaseModel):
    id: UUID
    module: str
    name: str
    document_type: str
    body_html: str
    version: int
    is_default: bool
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime | None
    #: The built-in this copy was made from — null for a template written
    #: from scratch.
    source_builtin: str | None = None
    #: True when that built-in has changed since the copy was made. The copy
    #: belongs to the organization and nothing rewrites it; this is what the
    #: screen needs to say so.
    source_outdated: bool = False
    model_config = ConfigDict(from_attributes=True)


class PlaceholderInfo(BaseModel):
    """A field a template author can print in a user template.

    ``key`` is the literal Jinja2 expression (e.g. ``{{partner.name}}``),
    ``example`` a representative rendered value, ``possibly_empty`` marks
    fields that are absent for some documents, and ``document_types`` names
    the document types the field belongs to (``None`` = any type). A category
    custom field also carries its ``custom_field_label`` and the
    ``custom_field_categories`` that define it, apart from the English
    ``description``, so a client can phrase the sentence in its own language.
    """

    key: str
    description: str
    example: str | None = None
    possibly_empty: bool = False
    document_types: list[str] | None = None
    custom_field_label: str | None = None
    custom_field_categories: list[str] | None = None
