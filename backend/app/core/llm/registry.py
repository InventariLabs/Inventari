"""Public resolver — given a purpose key, return a working LLM client.

This is the single entry point feature code calls::

    client = await get_client_for_purpose(db, org_id, "vision.extract")
    if client is None:
        # either the org has no AI configured, or the binding points
        # somewhere invalid; report a clear UI error.
    response = await client.complete(request)

Why a resolver, not a connection lookup? Three reasons:

1. **Bindings live in *settings*, not in the AiConnection row.** Each
   org has one or more connections in the pool; the org picks which
   connection is bound to which purpose via settings. The resolver
   reads settings, then loads the connection.

2. **Different purposes can bind to different connections.** A VISION
   connection (OpenRouter, multimodal model) and a TEXT connection
   (cheaper, JSON-tuned) are independently selectable.

3. **Core stays neutral.** The pool is Core-owned; each purpose is
   declared by the feature module that consumes it. The resolver does
   NOT hardcode "vision" or "recipes" — it uses ``spec.owner_module``
   to decide where the binding lives.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import llm_env_capabilities, settings
from app.core.llm.base import LlmClient
from app.core.llm.factory import get_client as factory_get_client
from app.core.llm.purpose_registry import get_purpose
from app.core.logging import get_logger

logger = get_logger(__name__)


async def get_connection_for_purpose(
    db: AsyncSession,
    org_id: UUID,
    purpose_key: str,
) -> Any | None:
    """The bound connection **row** — for a consumer that reads a
    credential instead of completing a request.

    Same two pieces ``get_client_for_purpose`` answers from — the choice
    (:func:`binding_from_settings`) and the verdict
    (:func:`connection_serves_async`) — so the two doors cannot disagree
    about what serves. A reader purpose (``url_fetch``) stops here: the
    consumer fetches with the key itself, and building an ``LlmClient``
    for a provider with no LLM protocol is a category error the factory
    refuses. The legacy env fallback does not apply either: it carries an
    LLM key, not a reader key.
    """
    spec = get_purpose(purpose_key)
    if spec is None:
        return None

    settings_dict = await _get_org_settings_decrypted(db, org_id)
    bound = binding_from_settings(settings_dict, purpose_key, spec.owner_module)
    if bound is None:
        return None

    return await connection_serves_async(db, org_id, bound, purpose_key)


async def get_client_for_purpose(
    db: AsyncSession,
    org_id: UUID,
    purpose_key: str,
) -> LlmClient | None:
    """Return the :class:`LlmClient` bound to *purpose_key* for *org_id*.

    Returns ``None`` for any of:
      - purpose_key not registered
      - no binding in settings and no env-var fallback
      - binding points to a row in another org (tenant guard)
      - connection lacks the purpose's required capability
      - db.get returned None for the bound UUID
      - the connection's recorded test for the capability failed

    The caller is expected to surface a clear UI error in any of these
    cases — never a silent fallthrough to a default model.

    Every answer here comes from the same two pieces the purposes list
    answers from — :func:`binding_from_settings` for the choice and
    :func:`connection_serves_async` for the verdict, plus the same env
    rule — so the two places that speak for a purpose cannot disagree.
    """
    spec = get_purpose(purpose_key)
    if spec is None:
        return None

    settings_dict = await _get_org_settings_decrypted(db, org_id)
    bound = binding_from_settings(settings_dict, purpose_key, spec.owner_module)
    if bound is None:
        # Nothing named in settings at all: the legacy env-var fallback
        # applies. A binding the verdict refuses is a decision the org
        # made, not an absence — it does not fall back to the environment.
        return _legacy_env_fallback(spec)

    conn = await connection_serves_async(db, org_id, bound, purpose_key)
    if conn is None:
        return None
    return factory_get_client(conn)


def binding_from_settings(
    settings_dict: dict[str, Any] | None,
    purpose_key: str,
    owner_module: str,
) -> UUID | None:
    """The raw answer to "what did this organization choose" — the UUID
    the settings name for *purpose_key*, or None when nothing is named.

    This is the org's decision, kept separate from
    :func:`connection_serves_async`'s verdict on purpose: the binding
    select renders it, the deletion guard protects it, and neither may
    re-interpret it by the rules the decision is itself measured against.
    A verdict folded into this field is how the select forgot the choice
    it was rendering and left the org no way to detach it.

    Bindings are written per purpose key into
    ``settings.ai.defaults[<key>]`` — a module with two purposes must not
    share one slot. The module-owned
    ``settings.modules.<owner_module>.ai_default_connection_id`` is the
    legacy home of choices made before that split and still reads, so an
    org that never re-binds keeps serving on its old choice; the first
    write through the bindings endpoint carries the slot across (see
    :meth:`app.core.public_api.ai_connections.CoreAIConnectionsAPI.set_binding_async`)
    so a later detach cannot be answered by the slot it meant to release.
    """
    if not settings_dict:
        return None

    # Core-owned: lives under settings.ai.defaults[<purpose>].
    ai_defaults = (settings_dict.get('ai') or {}).get('defaults') or {}
    raw = ai_defaults.get(purpose_key)
    if not raw:
        # Module-owned: settings.modules.<owner>.ai_default_connection_id.
        modules = settings_dict.get('modules') or {}
        raw = (modules.get(owner_module) or {}).get('ai_default_connection_id')
    if not raw:
        return None

    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


async def connection_serves_async(
    db: AsyncSession,
    org_id: UUID,
    conn_id: UUID,
    purpose_key: str,
) -> Any | None:
    """The verdict on a named connection: will this purpose actually run?

    The row must exist in this organization, carry the purpose's
    capability, and its recorded test for that capability must not have
    failed. Returns the loaded row — the client builder needs no second
    load — or None, and None is the whole sentence: a screen may promise
    the purpose to the reader exactly when the purposes list, built from
    this same chain, says ``usable``.

    Only a recorded failure disqualifies. "Never tested" is what every
    existing connection is, and refusing those would take image
    recognition away from everyone who has not pressed Test since
    upgrading.
    """
    spec = get_purpose(purpose_key)
    if spec is None:
        return None

    conn = await _get_connection(db, conn_id)
    if conn is None or conn.organization_id != org_id:
        # Cross-tenant OR stale binding — refuse silently so a malformed
        # frontend payload can't enumerate neighbour orgs' UUIDs.
        return None

    if spec.capability.value not in (conn.capabilities or []):
        return None

    # The claim is not the last word. A connection whose test for this very
    # capability came back failed is not a candidate for it, whatever the
    # checkbox says — that is how a model which cannot read images stayed on
    # the list of things to read images with.
    check = (conn.capability_checks or {}).get(spec.capability.value)
    if isinstance(check, dict) and check.get('ok') is False:
        logger.info(
            'Connection %s is not offered for %s: its %s test failed',
            conn.id,
            purpose_key,
            spec.capability.value,
        )
        return None

    return conn


def env_fallback_serves(purpose_key: str) -> bool:
    """Would the legacy env-var fallback hand out a client for this
    purpose?

    Same rule :func:`get_client_for_purpose` applies when no binding is
    named — so the purposes list can say ``usable`` for exactly the
    organizations the builder would serve, and the two places that speak
    for a purpose stay in agreement.
    """
    spec = get_purpose(purpose_key)
    return (
        spec is not None
        and bool(settings.LLM_API_KEY)
        and spec.capability.value in _env_capabilities()
    )


async def _get_connection(
    db: AsyncSession,
    conn_id: UUID,
) -> Any:
    """Single seam for ``db.get(AiConnection, conn_id)`` so the unit
    suite can patch it without fighting SQLAlchemy's session manager."""
    return await db.get(_ai_connection_model(), conn_id)


async def _get_org_settings_decrypted(
    db: AsyncSession,
    org_id: UUID,
) -> dict[str, Any] | None:
    """Convenience wrapper for the public org-settings API.

    ``core_api.organizations.get_settings_async`` already decrypts the
    JSONB blob via :func:`app.services.crypto_service.decrypt_settings`,
    so the binding UUIDs come back as strings — we parse to UUID at
    use-site.
    """
    from app.core.public_api import core_api

    return await core_api.organizations.get_settings_async(db, org_id)


def _env_capabilities() -> frozenset[str]:
    return llm_env_capabilities(settings.LLM_PROVIDER, settings.LLM_CAPABILITIES)


def _legacy_env_fallback(spec: Any) -> LlmClient | None:
    """Backward-compat: build a transient client for ``LLM_PROVIDER`` from
    ``LLM_API_KEY`` when no DB binding exists.

    Returns ``None`` (not raise) when the env var is unset — bare-env
    installs without AI enabled must not block other features — and when
    the purpose needs what ``LLM_CAPABILITIES`` does not declare: refused
    here, the caller answers "not set up" instead of the provider failing
    on an image its model cannot read.
    """
    api_key = settings.LLM_API_KEY
    if not api_key:
        return None

    capabilities = _env_capabilities()
    if spec.capability.value not in capabilities:
        logger.warning(
            'The environment model is not declared for %s, which %s needs: '
            'add it to LLM_CAPABILITIES if the model can do it',
            spec.capability.value,
            spec.key,
        )
        return None

    # Lazy import to avoid SQLAlchemy model load when only the fallback
    # path is exercised (the public db path imports it above).
    from app.models.ai_connection import AiConnection

    transient = AiConnection(
        provider=settings.LLM_PROVIDER,
        api_key_enc=api_key,
        api_base_url=settings.LLM_API_BASE_URL or '',
        model_name=settings.LLM_MODEL or '',
        capabilities=sorted(capabilities),
    )
    return factory_get_client(transient)


def _ai_connection_model() -> Any:
    """Late-bound import to keep ``app.core.llm.registry`` importable
    without the SQLAlchemy metadata (avoids circular import during
    test collection)."""
    from app.models.ai_connection import AiConnection

    return AiConnection
