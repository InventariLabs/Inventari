"""Helpers for resolving per-module service configuration from org settings.

LLM configuration lives in the AI Connections registry — modules resolve
clients via :func:`app.core.llm.registry.get_client_for_purpose` with a
bound ``AiConnection``, and the Jina Reader key lives there too (a
credential for an external provider belongs where every other credential is
visible, rotatable and testable).
:func:`resolve_jina_api_key_async` answers from the connection bound to
``recipes.url_fetch`` — the plaintext key, ``None`` for the reader's free
tier, and a refusal when the stored key cannot be read (see the
function's docstring).

Usage example::

    from app.core.module_settings import resolve_jina_api_key_async

    jina_key = await resolve_jina_api_key_async(db, org_id)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_jina_api_key_async(
    db: AsyncSession, organization_id: UUID | None
) -> str | None:
    """Return the reader key bound to ``recipes.url_fetch``, or ``None``.

    Reads the connection row through the same resolver every purpose uses
    — the org's choice and the verdict on it — and decrypts its key. There
    is intentionally no env-var fallback: the reader works without a key
    (free tier) and ``None`` is exactly that answer, for an org that never
    bound a connection as much as for one bound to a key-less row.

    :raises PermissionError: the stored key cannot be decrypted — the
        encryption key or salt has rotated since it was saved. Deliberately
        not swallowed: an import that fell back to "no key" would scrape
        through the free tier off a different account, and the operator
        would never learn the stored key is unreadable. The import doors
        carry ``@map_service_errors``, which turns this into a 403.
    """
    from app.core.llm.secrets import decrypt_connection_secret
    from app.core.public_api import core_api

    if organization_id is None:
        return None
    conn: Any = await core_api.llm.connection_for_purpose_async(
        db, organization_id, 'recipes.url_fetch'
    )
    if conn is None or not conn.api_key_enc:
        return None
    try:
        return decrypt_connection_secret(conn.api_key_enc) or None
    except RuntimeError as exc:
        raise PermissionError(str(exc)) from exc
