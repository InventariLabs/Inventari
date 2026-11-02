"""Integration tests for the enrichment helpers in
``app.modules.approvals._services_enrichment``.

Covers:
- list_requests (raw ORM)
- get_request (raw ORM)
- _enrich_request (per-request dict with names and stages)
- list_requests_enriched / get_request_enriched
- Multi-tenancy filtering
- Workflow not found (graceful degradation)
- User not found (graceful degradation)
"""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals import services
from app.modules.approvals._services_enrichment import (
    _enrich_request,
    get_request,
    get_request_enriched,
    list_requests,
    list_requests_enriched,
)

if TYPE_CHECKING:
    from app.modules.warehouse.models.document import Document

# ---------------------------------------------------------------------------
# Async fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def enrich_org(real_async_db_session: AsyncSession) -> Organization:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(
        name=f'Enrich Org {suffix}',
        enabled_modules=['core', 'approvals'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def enrich_requester(
    real_async_db_session: AsyncSession, enrich_org: Organization
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f'enrich_req_{suffix}@example.com',
        hashed_password='x',
        full_name='Enrich Requester',
        organization_id=enrich_org.id,
        role='user',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def enrich_approver(
    real_async_db_session: AsyncSession, enrich_org: Organization
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f'enrich_app_{suffix}@example.com',
        hashed_password='x',
        full_name='Enrich Approver',
        organization_id=enrich_org.id,
        role='manager',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


async def _create_workflow_and_request(
    db: AsyncSession,
    org: Organization,
    requester: User,
) -> UUID:
    """Helper: create a single-stage workflow and an approval request."""
    from app.modules.approvals.approvals_api import approvals_api

    await approvals_api.create_workflow(
        db,
        org.id,
        'document',
        'Enrichment Test',
        [
            {
                'order': 1,
                'role': 'manager',
                'label': 'Manager',
                'approver_user_ids': [],
            }
        ],
        is_active=True,
    )
    req = await approvals_api.request_approval(
        db, org.id, 'document', uuid.uuid4(), requester.id
    )
    return req.id


# ---------------------------------------------------------------------------
# list_requests (raw ORM)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListRequestsRaw:
    async def test_returns_empty_when_no_requests(
        self, real_async_db_session: AsyncSession, enrich_org: Organization
    ) -> None:
        result = await list_requests(real_async_db_session, enrich_org.id)
        assert result == []

    async def test_returns_orm_models(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        result = await list_requests(real_async_db_session, enrich_org.id)
        assert len(result) == 1
        # Raw ORM model, not DTO.
        from app.modules.approvals.models import ApprovalRequest

        assert isinstance(result[0], ApprovalRequest)
        # No enrichment applied: created_by_name attribute doesn't exist on ORM.
        assert not hasattr(result[0], 'created_by_name')

    async def test_filters_by_target_type(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        doc_reqs = await list_requests(
            real_async_db_session, enrich_org.id, target_type='document'
        )
        assert len(doc_reqs) == 1
        other = await list_requests(
            real_async_db_session, enrich_org.id, target_type='purchase_order'
        )
        assert other == []

    async def test_filters_by_status(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        pending = await list_requests(
            real_async_db_session, enrich_org.id, status='PENDING'
        )
        assert len(pending) == 1
        approved = await list_requests(
            real_async_db_session, enrich_org.id, status='APPROVED'
        )
        assert approved == []

    async def test_filters_by_target_id(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        target_id = uuid.uuid4()
        from app.modules.approvals.approvals_api import approvals_api

        await services.create_workflow(
            real_async_db_session,
            enrich_org.id,
            'document',
            'Single',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'M',
                    'approver_user_ids': [],
                }
            ],
            is_active=True,
        )
        await approvals_api.request_approval(
            real_async_db_session,
            enrich_org.id,
            'document',
            target_id,
            enrich_requester.id,
        )
        only = await list_requests(
            real_async_db_session, enrich_org.id, target_id=target_id
        )
        assert len(only) == 1
        assert only[0].target_id == target_id

    async def test_does_not_leak_other_org(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        other_org_id = uuid.uuid4()
        result = await list_requests(real_async_db_session, other_org_id)
        assert result == []


# ---------------------------------------------------------------------------
# get_request (raw ORM)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetRequestRaw:
    async def test_returns_none_when_missing(
        self, real_async_db_session: AsyncSession, enrich_org: Organization
    ) -> None:
        result = await get_request(real_async_db_session, enrich_org.id, uuid.uuid4())
        assert result is None

    async def test_returns_orm_model(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        req_id = await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        result = await get_request(real_async_db_session, enrich_org.id, req_id)
        assert result is not None
        from app.modules.approvals.models import ApprovalRequest

        assert isinstance(result, ApprovalRequest)
        assert result.id == req_id

    async def test_filters_by_org(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        req_id = await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        # Same id, different org -> None
        other_org_id = uuid.uuid4()
        result = await get_request(real_async_db_session, other_org_id, req_id)
        assert result is None


# ---------------------------------------------------------------------------
# _enrich_request
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEnrichRequest:
    async def test_adds_created_by_name_and_workflow_stages(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        req_id = await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        req = await get_request(real_async_db_session, enrich_org.id, req_id)
        assert req is not None
        enriched = await _enrich_request(real_async_db_session, req)

        assert enriched['id'] == req_id
        assert enriched['created_by_name'] == 'Enrich Requester'
        assert enriched['workflow_stages'] is not None
        assert len(enriched['workflow_stages']) == 1
        # Decisions include the initial PENDING one
        assert len(enriched['decisions']) == 1
        assert enriched['decisions'][0]['status'] == 'PENDING'
        # The pending decision has no approver yet.
        assert enriched['decisions'][0]['approver_name'] is None

    async def test_includes_approver_name_after_approval(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
        enrich_approver: User,
    ) -> None:
        from app.modules.approvals.approvals_api import approvals_api

        await services.create_workflow(
            real_async_db_session,
            enrich_org.id,
            'document',
            'Single',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'M',
                    'approver_user_ids': [],
                }
            ],
            is_active=True,
        )
        req = await approvals_api.request_approval(
            real_async_db_session,
            enrich_org.id,
            'document',
            uuid.uuid4(),
            enrich_requester.id,
        )
        await approvals_api.approve_stage(
            real_async_db_session,
            enrich_org.id,
            req.id,
            enrich_approver.id,
            notes='OK',
        )
        enriched_req = await get_request(real_async_db_session, enrich_org.id, req.id)
        assert enriched_req is not None
        enriched = await _enrich_request(real_async_db_session, enriched_req)
        assert enriched['status'] == 'APPROVED'
        assert enriched['decisions'][0]['status'] == 'APPROVED'
        assert enriched['decisions'][0]['approver_name'] == 'Enrich Approver'
        assert enriched['decisions'][0]['notes'] == 'OK'

    async def test_decision_approver_name_is_none_when_pending(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        """The PENDING decision has no approver yet, so approver_name is None.

        This documents the graceful-degradation contract in
        ``_enrich_request``: any field that the user-lookup helper returns
        ``None`` for must surface as ``None`` in the enriched dict (not raise).
        """
        req_id = await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        req = await get_request(real_async_db_session, enrich_org.id, req_id)
        assert req is not None
        enriched = await _enrich_request(real_async_db_session, req)
        assert enriched['decisions'][0]['approver_id'] is None
        assert enriched['decisions'][0]['approver_name'] is None


# ---------------------------------------------------------------------------
# list_requests_enriched / get_request_enriched
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEnrichedListAndGet:
    async def test_list_requests_enriched_returns_dicts_with_names(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        result, total = await list_requests_enriched(
            real_async_db_session, enrich_org.id
        )
        assert total == 1
        assert len(result) == 1
        assert result[0]['created_by_name'] == 'Enrich Requester'
        assert result[0]['workflow_stages'] is not None
        assert result[0]['status'] == 'PENDING'

    async def test_list_requests_enriched_filters(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        doc, _ = await list_requests_enriched(
            real_async_db_session, enrich_org.id, target_type='document'
        )
        assert len(doc) == 1
        pending, _ = await list_requests_enriched(
            real_async_db_session, enrich_org.id, status='PENDING'
        )
        assert len(pending) == 1
        approved, _ = await list_requests_enriched(
            real_async_db_session, enrich_org.id, status='APPROVED'
        )
        assert approved == []

    async def test_list_requests_enriched_accepts_a_status_set(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        """A comma-separated ``status`` matches any of the listed values.

        The queue defaults to the open states, which is two values, not one —
        a single-value filter cannot express that without a second request.
        """
        request_id = await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )

        open_states, open_total = await list_requests_enriched(
            real_async_db_session, enrich_org.id, status='PENDING,IN_PROGRESS'
        )
        assert len(open_states) == 1
        assert open_total == 1
        assert open_states[0]['id'] == request_id

        closed, closed_total = await list_requests_enriched(
            real_async_db_session,
            enrich_org.id,
            status='APPROVED,REJECTED,CANCELLED',
        )
        assert closed == []
        assert closed_total == 0

    async def test_list_requests_enriched_carries_cancellation_fields(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        """The schema promises cancelled_by/cancelled_at; the list must keep it.

        Cancelling stamps both columns, but the enriched dict never copied
        them, so every client saw null and could not tell a reader when a
        request was withdrawn.
        """
        from app.modules.approvals.approvals_api import approvals_api

        request_id = await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        await approvals_api.cancel_request(
            real_async_db_session, enrich_org.id, request_id, enrich_requester.id
        )

        result, _ = await list_requests_enriched(
            real_async_db_session, enrich_org.id, status='CANCELLED'
        )
        assert len(result) == 1
        assert result[0]['cancelled_at'] is not None
        assert result[0]['cancelled_by'] == enrich_requester.id

    async def test_list_requests_enriched_ignores_blank_status_entries(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        """Stray separators must not silently widen the filter to everything."""
        await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )

        result, _ = await list_requests_enriched(
            real_async_db_session, enrich_org.id, status=' PENDING , '
        )
        assert len(result) == 1

        none_match, _ = await list_requests_enriched(
            real_async_db_session, enrich_org.id, status=' , '
        )
        assert none_match == []

    async def test_get_request_enriched_returns_none_when_missing(
        self, real_async_db_session: AsyncSession, enrich_org: Organization
    ) -> None:
        result = await get_request_enriched(
            real_async_db_session, enrich_org.id, uuid.uuid4()
        )
        assert result is None

    async def test_get_request_enriched_returns_dict(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        req_id = await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        result = await get_request_enriched(
            real_async_db_session, enrich_org.id, req_id
        )
        assert result is not None
        assert result['id'] == req_id
        assert result['created_by_name'] == 'Enrich Requester'
        assert result['workflow_stages'] is not None

    async def test_get_request_enriched_filters_by_org(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        req_id = await _create_workflow_and_request(
            real_async_db_session, enrich_org, enrich_requester
        )
        # Different org should not see the request.
        other_org_id = uuid.uuid4()
        result = await get_request_enriched(real_async_db_session, other_org_id, req_id)
        assert result is None


# ---------------------------------------------------------------------------
# Target summary enrichment ("what to verify")
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEnrichmentTargetSummary:
    """Approvers need a lightweight preview of the document they're reviewing.

    The enrichment fetches a single batched IN-query (with COUNT subquery for
    lines_count) so the list endpoint stays O(1) queries regardless of result
    size. Non-document target types degrade to ``target_summary=None``.
    """

    async def _make_doc(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        *,
        number: str,
        total_gross: Decimal | None,
        currency: str | None,
        partner_snapshot: dict[str, Any] | None,
        lines_count: int,
    ) -> 'Document':
        from app.modules.warehouse.models.document import Document, DocumentLine

        doc = Document(
            organization_id=org_id,
            type='IN',
            number=number,
            status='DRAFT',
            partner_id=None,
            partner_snapshot=partner_snapshot,
            target_location_id=None,
            source_location_id=None,
            created_by=user_id,
            total_gross=total_gross,
            currency=currency,
        )
        for i in range(lines_count):
            doc.lines.append(
                DocumentLine(
                    line_number=i + 1,
                    quantity=Decimal('1'),
                    expected_quantity=Decimal('1'),
                    done_quantity=Decimal('0'),
                )
            )
        db.add(doc)
        await db.flush()
        return doc

    async def test_get_request_enriched_includes_target_summary_for_document(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        from decimal import Decimal

        from app.modules.approvals.approvals_api import approvals_api

        doc = await self._make_doc(
            real_async_db_session,
            enrich_org.id,
            enrich_requester.id,
            number='IN/2026/9001',
            total_gross=Decimal('250.00'),
            currency='USD',
            partner_snapshot={'name': 'ACME Supplier', 'code': 'ACME'},
            lines_count=3,
        )
        await real_async_db_session.commit()

        await approvals_api.create_workflow(
            real_async_db_session,
            enrich_org.id,
            'document',
            'Target Summary Test',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager',
                    'approver_user_ids': [],
                }
            ],
            is_active=True,
        )
        req = await approvals_api.request_approval(
            real_async_db_session,
            enrich_org.id,
            'document',
            doc.id,
            enrich_requester.id,
        )
        await real_async_db_session.commit()

        result = await get_request_enriched(
            real_async_db_session, enrich_org.id, req.id
        )

        assert result is not None
        assert result['target_summary'] is not None
        summary = result['target_summary']
        assert summary['id'] == str(doc.id)
        assert summary['number'] == 'IN/2026/9001'
        assert summary['type'] == 'IN'
        assert summary['partner_name'] == 'ACME Supplier'
        assert summary['total_value'] == '250.00'
        assert summary['currency'] == 'USD'
        assert summary['lines_count'] == 3
        # A document confirmed the ordinary way waits for a later execution:
        # the approval does not post it.
        assert summary['posts_on_approval'] is False

    async def test_list_requests_enriched_includes_target_summary_batch(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        from app.modules.approvals.approvals_api import approvals_api

        doc_a = await self._make_doc(
            real_async_db_session,
            enrich_org.id,
            enrich_requester.id,
            number='IN/2026/9101',
            total_gross=None,
            currency=None,
            partner_snapshot=None,
            lines_count=0,
        )
        doc_b = await self._make_doc(
            real_async_db_session,
            enrich_org.id,
            enrich_requester.id,
            number='IN/2026/9102',
            total_gross=None,
            currency=None,
            partner_snapshot=None,
            lines_count=0,
        )
        await real_async_db_session.commit()

        await approvals_api.create_workflow(
            real_async_db_session,
            enrich_org.id,
            'document',
            'Batch Test',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager',
                    'approver_user_ids': [],
                }
            ],
            is_active=True,
        )
        await approvals_api.request_approval(
            real_async_db_session,
            enrich_org.id,
            'document',
            doc_a.id,
            enrich_requester.id,
        )
        await approvals_api.request_approval(
            real_async_db_session,
            enrich_org.id,
            'document',
            doc_b.id,
            enrich_requester.id,
        )
        await real_async_db_session.commit()

        # Call the lightweight service-layer function (same code path as router).
        enriched, _ = await list_requests_enriched(real_async_db_session, enrich_org.id)

        assert len(enriched) == 2
        by_target = {r['target_id']: r for r in enriched}
        assert by_target[doc_a.id]['target_summary']['number'] == 'IN/2026/9101'
        assert by_target[doc_b.id]['target_summary']['number'] == 'IN/2026/9102'

    async def test_get_request_enriched_target_summary_none_for_unclaimed_target(
        self,
        real_async_db_session: AsyncSession,
        enrich_org: Organization,
        enrich_requester: User,
    ) -> None:
        """A target type nobody registered degrades to ``target_summary=None``.

               ``equipment_checkout`` used to prove this because no provider existed,
        but it now claims one; an unclaimed type keeps the contract
               honest.
        """
        from app.modules.approvals.approvals_api import approvals_api

        await approvals_api.create_workflow(
            real_async_db_session,
            enrich_org.id,
            'unclaimed',
            'Unclaimed Test',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager',
                    'approver_user_ids': [],
                }
            ],
            is_active=True,
        )
        req = await approvals_api.request_approval(
            real_async_db_session,
            enrich_org.id,
            'unclaimed',
            uuid.uuid4(),
            enrich_requester.id,
        )
        await real_async_db_session.commit()

        result = await get_request_enriched(
            real_async_db_session, enrich_org.id, req.id
        )

        assert result is not None
        assert result['target_summary'] is None
