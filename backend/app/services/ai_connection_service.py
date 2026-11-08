"""Service for the AI Connections pool.

Per AGENTS.md §3 (Golden Path), the architecture linter forbids the
Public API from touching Core ORM models directly — every read and
write through :mod:`app.core.public_api.ai_connections` goes through
this service. The service owns the model class so the linter stops
emitting "Direct import of 'app.models.X' in Public API" notices and
the router gets a clean DTOs-out contract.

The methods here are transaction-aware: writes call ``db.add()`` /
``db.flush()``; the caller (router) commits. This mirrors the
convention used by UserService, OrganizationService, etc.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.llm._outbound import guard_llm_url
from app.core.llm.enums import LlmCapability
from app.core.llm.secrets import (
    encrypt_connection_secret,
    mask_connection_secret,
)
from app.core.logging import get_logger
from app.schemas.ai_connection import (
    AiConnectionSchema,
)

if TYPE_CHECKING:
    from app.models.ai_connection import AiConnection

logger = get_logger(__name__)


class _Unset:
    """The absence of a key, carried from the request DTO into the service.

    ``None`` cannot stand for both "clear it" and "you did not send it", and
    a blanket ``if value is not None`` erases the first — the defect this
    exists for: a cleared API base URL answered 200 and kept the old address
    (AGENTS.md §2b). A key the payload did not send arrives as ``UNSET`` and
    never reaches the column.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return 'UNSET'


UNSET: Final = _Unset()


class AiConnectionService:
    """All model access for the AI Connections pool."""

    # ----- read ---------------------------------------------------------------

    async def list_for_org(
        self, db: AsyncSession, org_id: uuid.UUID
    ) -> list[AiConnectionSchema]:
        from app.models.ai_connection import AiConnection

        result = await db.scalars(
            select(AiConnection)
            .where(AiConnection.organization_id == org_id)
            .order_by(AiConnection.created_at)
        )
        return [_to_schema(c) for c in result.all()]

    async def get_for_org(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        conn_id: uuid.UUID,
    ) -> AiConnectionSchema | None:
        conn = await self._get_raw(db, conn_id)
        if conn is None or conn.organization_id != org_id:
            return None
        return _to_schema(conn)

    async def get_raw_for_org(
        self, db: AsyncSession, org_id: uuid.UUID, conn_id: uuid.UUID
    ) -> AiConnection | None:
        """Return the ORM row scoped to *org_id*, or None on missing /
        cross-tenant. Used by the test endpoint to call list_models()
        with the stored cipher without re-implementing the tenant guard.
        """
        conn = await self._get_raw(db, conn_id)
        if conn is None or conn.organization_id != org_id:
            return None
        return conn

    def build_transient(
        self,
        *,
        org_id: uuid.UUID,
        provider: str,
        api_key_plaintext: str,
        api_base_url: str,
        model_name: str,
    ) -> AiConnection:
        """Build an unsaved AiConnection for the pre-save test endpoint.

        The returned row is NEVER added to the session — it exists only
        so the LLM client can read ``api_key_enc``. Kept in the service
        (not the router / public API) so the ORM import stays in the
        layer that owns it. The organization rides along even without a
        row id: the refusal memory keys a draft by its organization and
        route, and without this the drafts of every organization using
        the same provider default would share one key.
        """
        from app.models.ai_connection import AiConnection

        return AiConnection(
            organization_id=org_id,
            provider=provider,
            api_key_enc=encrypt_connection_secret(api_key_plaintext),
            api_base_url=api_base_url,
            model_name=model_name,
        )

    async def test_connection(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        *,
        connection_id: uuid.UUID | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        api_base_url: str | None = None,
        model_name: str | None = None,
        capabilities: list[str] | None = None,
    ) -> dict:
        """Check a connection in two stages, and say which one failed.

        ``list_models()`` proves the credentials work and the provider is
        reachable. It proves nothing about whether the model can answer in
        the shape the app needs — and that is the failure people actually
        hit: a green test in Settings, then extraction falling over in the
        field after switching to a weaker model.

        So the second stage sends one real request through the registered
        contract probe for whatever this connection claims it can do, and
        judges the answer with the feature's own parser.

        Two modes (router validates that one is provided):
        - ``connection_id`` set → load the stored ORM row (tenant-guarded).
        - ``provider`` set → build a transient in-memory row from the draft,
          so the UI can test before saving.

        Raises ``RuntimeError`` on any provider HTTP/SDK error so the router
        can translate to 400. Stays in the service because the LLM client
        expects an ORM row (carrying ``api_key_enc``) — exposing that row via
        public_api would trip the CoreAPI model-leak lint.

        The org's AI limit gates the probe before the provider is reached: the
        test is a billed call and the ledger books it against the same monthly
        ceiling vision and extraction draw on, so an organization that is out
        of budget is refused here rather than billed again. Both stages sit
        behind that gate — the contract probe is the one that spends. That
        refusal is the counter's ``HTTPException`` (429) and travels through
        the router unchanged.
        """
        from app.services.ai_usage_service import enforce_ai_limit_async

        # Same counter, same period, as every other AI call. The refusal is a
        # 429 whose body names the ceiling and carries the numbers; it leaves
        # this service as the HTTPException the router re-raises.
        await enforce_ai_limit_async(db, org_id, 'connection_test')

        from app.core.llm.factory import get_client

        if connection_id is not None:
            conn = await self.get_raw_for_org(db, org_id, connection_id)
            if conn is None:
                return {'ok': False, 'models': [], 'error': 'not_found'}
            declared = [str(c) for c in (conn.capabilities or [])]
        else:
            assert provider is not None  # router narrows
            conn = self.build_transient(
                org_id=org_id,
                provider=provider,
                api_key_plaintext=api_key or '',
                api_base_url=api_base_url or '',
                model_name=model_name or '',
            )
            declared = [str(c) for c in (capabilities or [])]

        from app.core.llm.enums import protocol_for

        if protocol_for(str(conn.provider)) is None:
            # A reader credential is not an LLM endpoint: no models to list
            # and no contract to probe. Its test reads one page with the
            # connection's own key — the call an import makes — so a key
            # that passes here is a key an import can use, and one that
            # does not fails in the registry instead of on the first
            # recipe someone tries to save.
            return await self._probe_reader_connection(
                conn, persist=connection_id is not None
            )

        client = get_client(conn)
        # Stage one. Errors surface to the caller — the router maps to 400,
        # which is the "credentials do not work" verdict.
        models = await client.list_models()

        contract = await self._probe_contract(db, org_id, client, declared)
        if not contract['checked']:
            verdict = 'unchecked'
        elif contract['ok']:
            verdict = 'ok'
        else:
            verdict = 'contract_failed'

        # The probe's verdict belongs on the row, not only in the toast that
        # showed it once. A connection whose vision test failed used to keep
        # its VISION badge and stay on the list of candidates for reading
        # photographs, with nothing anywhere to say the model had been asked
        # and had not managed. A draft has no row to write to.
        if connection_id is not None and contract['checked']:
            self._record_capability_check(conn, contract)
        # ``ok`` keeps its original meaning — the provider answered us. The
        # richer question is ``verdict``.
        return {
            'ok': True,
            'verdict': verdict,
            'models': models,
            'contract': contract,
        }

    async def _probe_reader_connection(
        self, conn: AiConnection, *, persist: bool
    ) -> dict:
        """Test a reader connection by reading one page with its key.

        Without a key the connection is the free tier — a legal state with
        nothing to test, and the answer says so rather than spending a
        request against a rate limit the whole installation shares. A key
        the reader refuses is a credentials failure like stage one's, and
        the row keeps no check for it: recorded checks speak about
        contract failures, not about keys that never opened the door.
        """
        import httpx

        from app.core.llm.secrets import decrypt_connection_secret

        if not conn.api_key_enc:
            return {
                'ok': True,
                'verdict': 'unchecked',
                'models': [],
                'contract': {
                    'checked': False,
                    'ok': False,
                    'purpose': 'recipes.url_fetch',
                    'reason': 'no_key_free_tier',
                    'schema_enforced': False,
                },
            }

        key = decrypt_connection_secret(conn.api_key_enc)
        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                response = await http.get(
                    'https://r.jina.ai/https://example.com',
                    headers={'Authorization': f'Bearer {key}'},
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f'the reader service could not be reached: {exc}'
            ) from exc

        if response.status_code != 200:
            raise RuntimeError(
                'the reader refused this key '
                f'(HTTP {response.status_code}) — re-enter it in the '
                'connection form'
            )
        contract = {
            'checked': True,
            'ok': bool(response.text.strip()),
            'purpose': 'recipes.url_fetch',
            'detail': f'{len(response.text)} characters read',
            'schema_enforced': False,
        }
        if persist:
            self._record_capability_check(conn, contract)
        return {
            'ok': True,
            'verdict': 'ok' if contract['ok'] else 'contract_failed',
            'models': [],
            'contract': contract,
        }

    @staticmethod
    def _record_capability_check(conn: AiConnection, contract: dict) -> None:
        """Write the probe's verdict onto the connection, under its capability.

        Keyed by capability rather than by purpose: the reader's question is
        "can this connection read images", and the purpose that was used to
        find out is a detail — kept in the entry, not in the key.
        """
        from app.core.llm.purpose_registry import get_purpose

        spec = get_purpose(str(contract.get('purpose') or ''))
        if spec is None:
            return
        checks = dict(conn.capability_checks or {})
        checks[spec.capability.value] = {
            'ok': bool(contract['ok']),
            'at': datetime.now(UTC).isoformat(),
            'purpose': spec.key,
        }
        conn.capability_checks = checks

    async def _probe_contract(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        client: object,
        declared_capabilities: list[str],
    ) -> dict:
        """Stage two: ask the model to do the job once, and judge the answer.

        The call is billed like any other. A test that is free to run is a
        test people run in a loop against a metered provider.
        """
        from app.core.llm.json_retry import complete_json
        from app.services.ai_usage_service import log_llm_usage_async

        spec = _probe_for(declared_capabilities)
        if spec is None or spec.probe is None:
            return {
                'checked': False,
                'ok': False,
                'purpose': None,
                'reason': 'no_probe_for_capabilities',
                'schema_enforced': False,
            }

        request = spec.probe.build_request()
        # No schema on the wire means the answer rides on the parser and one
        # retry. The caller has to be told that, or a green result claims more
        # confidence than it earned.
        schema_enforced = request.json_schema is not None
        attempts = 0
        last_answer = ''

        async def record(response: object) -> None:
            nonlocal attempts, last_answer
            attempts += 1
            last_answer = getattr(response, 'content', '')
            await log_llm_usage_async(
                db=db,
                user_id=None,
                organization_id=str(org_id),
                response=response,
                action_type='connection_test',
                client=client,
            )

        try:
            parsed, _response = await complete_json(
                client,  # type: ignore[arg-type]
                request,
                validate=spec.probe.validate,
                on_response=record,
            )
        except (ValueError, TypeError) as err:
            logger.info(
                'Connection test: %s answered outside the contract (%s)',
                spec.key,
                err,
            )
            return {
                'checked': True,
                'ok': False,
                'purpose': spec.key,
                'attempts': attempts,
                'schema_enforced': schema_enforced,
                'answer_preview': _preview(last_answer),
                'error': str(err),
            }

        result = {
            'checked': True,
            'ok': True,
            'purpose': spec.key,
            'attempts': attempts,
            'schema_enforced': schema_enforced,
        }
        # What the model read, beside what the probe drew. The verdict stays
        # what it was — a well-formed answer is a pass — because a date read
        # as "31 January 2027" is right in a way no equality test approves of,
        # and calling that a failure would train people to ignore the test.
        # The reading travels so the person choosing a model can see the
        # difference the verdict cannot express.
        if spec.probe.read_back is not None:
            try:
                result['reading'] = spec.probe.read_back(parsed)
            except Exception:  # a report must never fail a pass
                logger.warning(
                    'Connection test: %s could not describe its reading',
                    spec.key,
                    exc_info=True,
                )
        return result

    # ----- write --------------------------------------------------------------

    async def create(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        *,
        name: str,
        provider: str,
        api_key: str | None,
        api_base_url: str,
        model_name: str,
        temperature: float | None,
        max_tokens: int | None,
        top_p: float | None,
        capabilities: list[LlmCapability],
    ) -> AiConnectionSchema:
        from app.models.ai_connection import AiConnection

        _guard_base_url(api_base_url)

        conn = AiConnection(
            organization_id=org_id,
            name=name,
            provider=provider,
            api_key_enc=(encrypt_connection_secret(api_key) if api_key else ''),
            api_base_url=api_base_url,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            capabilities=[c.value for c in capabilities],
        )
        db.add(conn)
        await db.flush()
        await db.refresh(conn)
        return _to_schema(conn)

    async def update(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        conn_id: uuid.UUID,
        *,
        new_api_key: str | None | _Unset,
        masked_marker: bool,
        name: str | None | _Unset = UNSET,
        api_base_url: str | None | _Unset = UNSET,
        model_name: str | None | _Unset = UNSET,
        temperature: float | None | _Unset = UNSET,
        max_tokens: int | None | _Unset = UNSET,
        top_p: float | None | _Unset = UNSET,
        capabilities: list[LlmCapability] | None | _Unset = UNSET,
    ) -> AiConnectionSchema | None:
        """PATCH semantics. ``masked_marker=True`` is set by the public
        API when the request body carried ``MASKED_VALUE``; in that
        case ``new_api_key`` is ignored (the cipher stays put).

        Presence decides, not truthiness: a field the payload carried is
        written — a named null clearing it — and a field it did not carry is
        left alone. Two of the columns are NOT NULL with an empty string as
        their cleared state (``api_base_url``, ``model_name``, the value a
        provider with a fixed endpoint keeps), so a named null reaches them
        as ``''``; ``name`` is the connection's identity under a unique key
        per organisation, so there is no honest cleared state and it is
        refused by name instead. A null API key is refused too: callers can
        keep it by omitting the field or replace it with a string (AGENTS.md
        §2b).
        """
        from app.services.crypto_service import MASKED_VALUE

        conn = await self._get_raw(db, conn_id)
        if conn is None or conn.organization_id != org_id:
            return None

        if not isinstance(name, _Unset):
            if name is None:
                raise ServiceRejectionError('field_cannot_be_cleared', fields='name')
            conn.name = name
        if not isinstance(new_api_key, _Unset):
            if new_api_key is None:
                raise ServiceRejectionError('field_cannot_be_cleared', fields='api_key')
            if not masked_marker and new_api_key != MASKED_VALUE:
                conn.api_key_enc = encrypt_connection_secret(new_api_key)
        if not isinstance(api_base_url, _Unset):
            base = api_base_url or ''
            _guard_base_url(base)
            _require_base_url_for_openai_compatible(conn.provider, base)
            conn.api_base_url = base
        if not isinstance(model_name, _Unset):
            conn.model_name = model_name or ''
        if not isinstance(temperature, _Unset):
            conn.temperature = temperature
        if not isinstance(max_tokens, _Unset):
            conn.max_tokens = max_tokens
        if not isinstance(top_p, _Unset):
            conn.top_p = top_p
        if not isinstance(capabilities, _Unset):
            conn.capabilities = [c.value for c in capabilities or []]

        await db.flush()
        await db.refresh(conn)
        return _to_schema(conn)

    async def delete(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        conn_id: uuid.UUID,
    ) -> bool:
        """Delete by id; returns False when missing or cross-tenant.

        Does NOT enforce the 'still bound' check — that is a higher-
        level business rule and lives in the Public API (which raises
        :class:`ConnectionStillBoundError` for the router to map to 409).
        """
        conn = await self._get_raw(db, conn_id)
        if conn is None or conn.organization_id != org_id:
            return False
        await db.delete(conn)
        await db.flush()
        return True

    async def is_bound_to_any_purpose(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        conn_id: uuid.UUID,
    ) -> bool:
        """Check *all* registered purposes for a binding that points
        to *conn_id*. Used by the delete guard."""
        from app.core.llm.purpose_registry import all_purposes
        from app.services._org_reads import get_by_id_async
        from app.services.crypto_service import decrypt_settings

        conn_id_str = str(conn_id)
        organization = await get_by_id_async(db, org_id)
        settings = decrypt_settings(organization.settings or {}) if organization else {}

        # Build a quick lookup of any registered purpose key.
        registered_keys = {p.key for p in all_purposes()}

        ai_defaults = (settings.get('ai') or {}).get('defaults') or {}
        for spec_key, raw in ai_defaults.items():
            if spec_key not in registered_keys:
                continue
            if str(raw) == conn_id_str:
                return True

        modules = settings.get('modules') or {}
        for _module_name, module_settings in modules.items():
            if not isinstance(module_settings, dict):
                continue
            raw = module_settings.get('ai_default_connection_id')
            if raw and str(raw) == conn_id_str:
                return True

        return False

    # ----- internal seam ------------------------------------------------------

    async def _get_raw(
        self, db: AsyncSession, conn_id: uuid.UUID
    ) -> AiConnection | None:
        """Single seam for ``db.get(AiConnection, conn_id)``. Tests
        patch this on the service instance so the unit suite does not
        have to fight SQLAlchemy session state."""
        from app.models.ai_connection import AiConnection

        return await db.get(AiConnection, conn_id)


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


# How much of an off-contract answer travels back to the UI. It is the only
# part of the failure the user can act on — but the whole answer would be a
# wall of text where a verdict belongs.
_ANSWER_PREVIEW = 400


def _preview(answer: str) -> str:
    stripped = answer.strip()
    if len(stripped) <= _ANSWER_PREVIEW:
        return stripped
    return stripped[:_ANSWER_PREVIEW] + '…'


def _probe_for(declared_capabilities: list[str]):
    """Pick the most demanding purpose this connection claims it can serve.

    Vision before text: a connection that says it reads images gets asked to,
    because that is the path a weaker model gives out on first.
    """
    from app.core.llm.purpose_registry import all_purposes

    have = set(declared_capabilities)
    for capability in (LlmCapability.VISION, LlmCapability.TEXT):
        if capability.value not in have:
            continue
        for spec in all_purposes():
            if spec.capability is capability and spec.probe is not None:
                return spec
    return None


def _require_base_url_for_openai_compatible(provider: str, api_base_url: str) -> None:
    """The update-side twin of the create schema's rule: the provider is
    not part of the update payload, so the stored row answers whether this
    client builds its URL from the base. Keyed, so the 400 the handler
    builds carries the catalog's sentence in the session's language."""
    from app.core.exceptions import ServiceRejectionError
    from app.core.llm.enums import LlmProtocol, protocol_for

    if (
        protocol_for(provider) is LlmProtocol.OPENAI_COMPATIBLE
        and not api_base_url.strip()
    ):
        raise ServiceRejectionError('llm_base_url_required_for_http_provider')


def _guard_base_url(api_base_url: str | None) -> None:
    """Refuse to persist a base URL pointing at the internal network.

    The client-side guard blocks the outbound request, but a stored
    malicious URL would fire on every later use of the connection —
    including background jobs, outside any user request. Webhooks validate
    on write for the same reason (``modules/webhooks/router.py``).

    An empty value is legitimate: providers with a fixed endpoint (Anthropic,
    Google) leave it blank and the client fills in its own default.
    """
    if not api_base_url:
        return
    guard_llm_url(api_base_url)


# ----------------------------------------------------------------------
# Adapter
# ----------------------------------------------------------------------


def _to_schema(conn: AiConnection) -> AiConnectionSchema:
    """Mask the secret, then build the response schema."""
    masked = mask_connection_secret(conn.api_key_enc)
    return AiConnectionSchema(
        id=conn.id,
        name=conn.name,
        provider=conn.provider,  # type: ignore[arg-type]
        api_key=masked,
        api_base_url=conn.api_base_url,
        model_name=conn.model_name,
        temperature=conn.temperature,
        max_tokens=conn.max_tokens,
        top_p=conn.top_p,
        capabilities=[LlmCapability(c) for c in (conn.capabilities or [])],
        capability_checks=dict(conn.capability_checks or {}),
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


__all__ = ['AiConnectionService']
