"""Pydantic schemas for the AI Connections REST API.

Wire format for the router at ``/api/v1/ai-connections``: three CRUD
shapes plus two auxiliary shapes (purposes, binding request).

The api_key field is a SPECIAL case on this surface:

- AiConnectionCreate: plaintext (newly supplied by the user).
- AiConnectionUpdate: either plaintext or ``MASKED_VALUE`` (\"****\")
  meaning \"keep the existing cipher\" — the latter is the way the
  form sends \"I didn't change this field\" without re-typing the key.
- AiConnectionSchema: ALWAYS masked (``MASKED_VALUE`` when set,
  empty string when unset). The plaintext never leaves the backend.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

from app.core.exceptions import ServiceRejectionError
from app.core.llm.enums import LlmCapability, LlmProtocol, LlmProvider, protocol_for
from app.services.crypto_service import MASKED_VALUE


class AiConnectionCreate(BaseModel):
    """Request body for ``POST /ai-connections``."""

    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1, max_length=255)
    provider: LlmProvider
    api_key: str | None = None
    api_base_url: str = ''
    model_name: str = ''

    @field_validator('api_base_url', 'model_name', mode='before')
    @classmethod
    def _empty_means_unset(cls, value: object) -> object:
        """Read a form's null as "left empty", not as a type error.

        The create form drafts these fields as null (a blank input carries
        no value), and a strict `str` turned that draft into a raw 422 —
        "Input should be a valid string" with no field named and no way
        for the reader to know the same request with `''` passes.
        """
        return '' if value is None else value

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    capabilities: list[LlmCapability] = Field(default_factory=list)

    @field_validator('api_base_url')
    @classmethod
    def _base_url_required_where_the_client_builds_the_url(
        cls, value: str, info: ValidationInfo
    ) -> str:
        """An OpenAI-compatible client glues its request URL out of this
        field; saved empty, the connection looks ready and the first call
        dies on a relative path with a transport error that never names
        the real cause. Providers reached through an SDK (anthropic,
        google) keep their fixed endpoints and may leave it blank.

        A field validator, not a model validator, so the 422's ``loc``
        names ``api_base_url`` and the create form can land the refusal
        under the input it belongs to instead of parsing the message.
        ``provider`` sits earlier in the model, so ``info.data`` has it
        by the time this runs; a bogus provider fails its own check and
        simply never reaches this one. Raised keyed, so pydantic's
        envelope carries the catalog's sentence in the session's
        language (the eager ``ServiceRejectionError`` translates before
        pydantic wraps it, and the 422 handler strips the wrapper).
        """
        provider = info.data.get('provider')
        if provider is None:
            return value
        provider_value = getattr(provider, 'value', provider)
        if (
            protocol_for(provider_value) is LlmProtocol.OPENAI_COMPATIBLE
            and not value.strip()
        ):
            raise ServiceRejectionError('llm_base_url_required_for_http_provider')
        return value


class AiConnectionUpdate(BaseModel):
    """Request body for ``PUT /ai-connections/{id}`` (PATCH semantics).

    Every field is optional. The ``api_key`` string additionally accepts
    ``MASKED_VALUE`` to mean \"do not change\" — see the round-trip
    contract documented in the test module.
    """

    model_config = ConfigDict(extra='forbid')

    name: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = None
    api_base_url: str | None = None
    model_name: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    capabilities: list[LlmCapability] | None = None


class CapabilityCheck(BaseModel):
    """What happened the last time this capability was actually asked for."""

    ok: bool
    at: datetime | None = None
    purpose: str | None = None


class AiConnectionSchema(BaseModel):
    """Response shape for read paths.

    ``api_key\" is always ``MASKED_VALUE``-or-empty by the time it
    reaches this model — see ``mask_connection_secret`` in
    ``app.core.llm.secrets``.
    """

    id: UUID
    name: str
    provider: LlmProvider
    api_key: str  # MASKED_VALUE or \"\"
    api_base_url: str
    model_name: str
    temperature: float | None
    max_tokens: int | None
    top_p: float | None
    capabilities: list[LlmCapability]
    #: What the connection test found, per capability — see
    #: ``AiConnection.capability_checks``. A capability missing here has never
    #: been tested; the screens tell that apart from one that was tested and
    #: failed, which they could not do while only the claim was readable.
    capability_checks: dict[str, CapabilityCheck] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AiPurposeSchema(BaseModel):
    """Response shape for ``GET /ai-connections/purposes``.

    ``bound_connection_id`` is the raw choice from settings; ``usable``
    is the verdict from the same rules the client builder applies — the
    screens promise the purpose exactly when this is true.
    """

    key: str
    capability: LlmCapability
    label_key: str
    description_key: str
    owner_module: str
    bound_connection_id: UUID | None = None
    usable: bool = False


class SetBindingRequest(BaseModel):
    """Request body for ``PUT /ai-connections/bindings``.

    ``connection_id=None`` clears the binding — the UI offers an explicit
    \"not configured\" option in the purpose dropdown.
    """

    purpose_key: str = Field(min_length=1)
    connection_id: UUID | None = None


class TestConnectionRequest(BaseModel):
    """Request body for ``POST /ai-connections/test``.

    Either pass ``connection_id`` (test an existing row, in which case the
    stored cipher is used) OR the inline fields (test a draft before saving,
    in which case ``api_key`` is plaintext). The router validates that one
    of the two modes is present.
    """

    model_config = ConfigDict(extra='forbid')

    connection_id: UUID | None = None
    provider: LlmProvider | None = None
    api_key: str | None = None
    api_base_url: str | None = None
    model_name: str | None = None
    capabilities: list[LlmCapability] = Field(default_factory=list)
    """What the draft claims it can do — decides which contract probe runs.

    Ignored when ``connection_id`` is given; the stored row is authoritative.
    """


__all__ = [
    'AiConnectionCreate',
    'AiConnectionUpdate',
    'AiConnectionSchema',
    'AiPurposeSchema',
    'SetBindingRequest',
    'TestConnectionRequest',
    'MASKED_VALUE',  # re-exported for convenience in router tests
]
