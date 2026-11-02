"""Integration tests for the public ``approvals_api`` surface.

Covers:
- DTO conversion (ApprovalWorkflowDTO stages coercion, ApprovalRequestDTO shape)
- Async service methods: get_active_workflow, create_workflow, update_workflow,
  delete_workflow, request_approval, approve_stage, reject_request,
  check_and_block, get_request, list_requests
- meta_data round-trip
- list filter combinations (target_type, status, target_id)
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals.approvals_api import approvals_api
from app.modules.approvals.exceptions import ApprovalRequiredError
from app.modules.approvals.models import ApprovalDecision, ApprovalRequest
from app.modules.approvals.schemas import StageDefinition

# ---------------------------------------------------------------------------
# Async fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def api_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name=f'Approvals API Test Org {uuid.uuid4().hex[:8]}',
        enabled_modules=['core', 'approvals'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def api_requester(
    real_async_db_session: AsyncSession, api_org: Organization
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f'api_requester_{suffix}@example.com',
        hashed_password='x',
        full_name='API Requester',
        organization_id=api_org.id,
        role='user',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def api_approver(
    real_async_db_session: AsyncSession, api_org: Organization
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f'api_approver_{suffix}@example.com',
        hashed_password='x',
        full_name='API Approver',
        organization_id=api_org.id,
        role='manager',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def api_approver2(
    real_async_db_session: AsyncSession, api_org: Organization
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f'api_approver2_{suffix}@example.com',
        hashed_password='x',
        full_name='API Approver Two',
        organization_id=api_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# get_active_workflow
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetActiveWorkflow:
    async def test_returns_none_when_no_workflow(
        self, real_async_db_session: AsyncSession, api_org: Organization
    ) -> None:
        result = await approvals_api.get_active_workflow(
            real_async_db_session, api_org.id, 'document'
        )
        assert result is None

    async def test_returns_dto_with_coerced_stages(
        self, real_async_db_session: AsyncSession, api_org: Organization
    ) -> None:
        stages_in = [
            {
                'order': 1,
                'role': 'manager',
                'label': 'Manager',
                'approver_user_ids': [],
            }
        ]
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'My Workflow',
            stages_in,
            is_active=True,
        )

        result = await approvals_api.get_active_workflow(
            real_async_db_session, api_org.id, 'document'
        )
        assert result is not None
        assert result.name == 'My Workflow'
        assert result.is_active is True
        # Stages must be coerced into StageDefinition objects.
        assert len(result.stages) == 1
        assert isinstance(result.stages[0], StageDefinition)
        assert result.stages[0].order == 1
        assert result.stages[0].label == 'Manager'

    async def test_does_not_return_inactive_workflow(
        self, real_async_db_session: AsyncSession, api_org: Organization
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Inactive',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'M',
                    'approver_user_ids': [],
                }
            ],
            is_active=False,
        )
        result = await approvals_api.get_active_workflow(
            real_async_db_session, api_org.id, 'document'
        )
        assert result is None


# ---------------------------------------------------------------------------
# create_workflow / update_workflow / delete_workflow
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCreateUpdateDeleteWorkflow:
    async def test_create_returns_workflow_dto(
        self, real_async_db_session: AsyncSession, api_org: Organization
    ) -> None:
        result = await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Created',
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
        assert result.id is not None
        assert result.organization_id == api_org.id
        assert result.name == 'Created'
        assert result.is_active is True
        assert result.created_at is not None
        # Stages coerced
        assert isinstance(result.stages[0], StageDefinition)

    async def test_update_returns_updated_dto(
        self, real_async_db_session: AsyncSession, api_org: Organization
    ) -> None:
        created = await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Original',
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
        updated = await approvals_api.update_workflow(
            real_async_db_session,
            api_org.id,
            created.id,
            name='Renamed',
        )
        assert updated.name == 'Renamed'
        assert updated.id == created.id

    async def test_delete_removes_workflow(
        self, real_async_db_session: AsyncSession, api_org: Organization
    ) -> None:
        created = await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'To Delete',
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
        await approvals_api.delete_workflow(
            real_async_db_session, api_org.id, created.id
        )
        result = await approvals_api.get_active_workflow(
            real_async_db_session, api_org.id, 'document'
        )
        assert result is None


# ---------------------------------------------------------------------------
# request_approval
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRequestApproval:
    async def test_returns_dto_with_pending_decision(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Single Stage',
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
        target_id = uuid.uuid4()
        result = await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            target_id,
            api_requester.id,
        )
        assert result.status == 'PENDING'
        assert result.current_stage == 1
        assert result.total_stages == 1
        assert result.target_id == target_id
        assert result.created_by == api_requester.id
        assert len(result.decisions) == 1
        assert result.decisions[0].status == 'PENDING'
        assert result.decisions[0].stage_order == 1

    async def test_meta_data_is_preserved(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'With Meta',
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
        meta = {'reason': 'audit needed', 'ticket': 'change request 42'}
        result = await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
            meta_data=meta,
        )
        assert result.meta_data == meta


# ---------------------------------------------------------------------------
# approve_stage / reject_request
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestApproveAndReject:
    async def test_approve_single_stage_returns_completed_dto(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        result = await approvals_api.approve_stage(
            real_async_db_session,
            api_org.id,
            req.id,
            api_approver.id,
            notes='OK',
        )
        assert result.status == 'APPROVED'
        assert len(result.decisions) == 1
        assert result.decisions[0].status == 'APPROVED'
        assert result.decisions[0].notes == 'OK'
        assert result.decisions[0].approver_id == api_approver.id

    async def test_approve_first_stage_of_multi_returns_in_progress(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
        api_approver2: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Multi',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'M',
                    'approver_user_ids': [],
                },
                {
                    'order': 2,
                    'role': 'admin',
                    'label': 'A',
                    'approver_user_ids': [],
                },
            ],
            is_active=True,
        )
        req = await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        result = await approvals_api.approve_stage(
            real_async_db_session, api_org.id, req.id, api_approver.id
        )
        assert result.status == 'IN_PROGRESS'
        assert result.current_stage == 2
        # The new pending decision must have been created.
        pending = [d for d in result.decisions if d.status == 'PENDING']
        assert len(pending) == 1
        assert pending[0].stage_order == 2

    async def test_reject_returns_rejected_dto(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        result = await approvals_api.reject_request(
            real_async_db_session,
            api_org.id,
            req.id,
            api_approver.id,
            notes='No',
        )
        assert result.status == 'REJECTED'
        assert result.decisions[0].status == 'REJECTED'
        assert result.decisions[0].notes == 'No'


# ---------------------------------------------------------------------------
# get_request / list_requests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetAndListRequests:
    async def test_get_request_returns_none_when_missing(
        self, real_async_db_session: AsyncSession, api_org: Organization
    ) -> None:
        result = await approvals_api.get_request(
            real_async_db_session, api_org.id, uuid.uuid4()
        )
        assert result is None

    async def test_get_request_returns_dto_when_present(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
        created = await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        result = await approvals_api.get_request(
            real_async_db_session, api_org.id, created.id
        )
        assert result is not None
        assert result.id == created.id

    async def test_list_requests_filters_by_target_type(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
        for _ in range(3):
            await approvals_api.request_approval(
                real_async_db_session,
                api_org.id,
                'document',
                uuid.uuid4(),
                api_requester.id,
            )
        all_reqs = await approvals_api.list_requests(real_async_db_session, api_org.id)
        assert len(all_reqs) == 3
        doc_reqs = await approvals_api.list_requests(
            real_async_db_session, api_org.id, target_type='document'
        )
        assert len(doc_reqs) == 3
        eq_reqs = await approvals_api.list_requests(
            real_async_db_session, api_org.id, target_type='equipment_checkout'
        )
        assert eq_reqs == []

    async def test_list_requests_filters_by_status(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
        req1 = await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        await approvals_api.approve_stage(
            real_async_db_session, api_org.id, req1.id, api_approver.id
        )
        approved = await approvals_api.list_requests(
            real_async_db_session, api_org.id, status='APPROVED'
        )
        assert len(approved) == 1
        pending = await approvals_api.list_requests(
            real_async_db_session, api_org.id, status='PENDING'
        )
        assert len(pending) == 1

    async def test_list_requests_filters_by_target_id(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
        target_x = uuid.uuid4()
        target_y = uuid.uuid4()
        await approvals_api.request_approval(
            real_async_db_session, api_org.id, 'document', target_x, api_requester.id
        )
        await approvals_api.request_approval(
            real_async_db_session, api_org.id, 'document', target_y, api_requester.id
        )
        only_x = await approvals_api.list_requests(
            real_async_db_session, api_org.id, target_id=target_x
        )
        assert len(only_x) == 1
        assert only_x[0].target_id == target_x

    async def test_list_requests_returns_dtos(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        result = await approvals_api.list_requests(real_async_db_session, api_org.id)
        assert len(result) == 1
        # Public API returns DTOs, not ORM models.
        from app.modules.approvals.approvals_dtos import ApprovalRequestDTO

        assert isinstance(result[0], ApprovalRequestDTO)


# ---------------------------------------------------------------------------
# check_and_block
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCheckAndBlock:
    async def test_noop_when_no_workflow(
        self, real_async_db_session: AsyncSession, api_org: Organization
    ) -> None:
        # No workflow configured -> check_and_block should not raise.
        await approvals_api.check_and_block(
            real_async_db_session, api_org.id, 'document', uuid.uuid4()
        )

    async def test_raises_when_pending(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
        target_id = uuid.uuid4()
        await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            target_id,
            api_requester.id,
        )
        with pytest.raises(ApprovalRequiredError):
            await approvals_api.check_and_block(
                real_async_db_session, api_org.id, 'document', target_id
            )

    async def test_raises_when_rejected(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
        target_id = uuid.uuid4()
        req = await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            target_id,
            api_requester.id,
        )
        await approvals_api.reject_request(
            real_async_db_session, api_org.id, req.id, api_approver.id
        )
        with pytest.raises(ApprovalRequiredError):
            await approvals_api.check_and_block(
                real_async_db_session, api_org.id, 'document', target_id
            )

    async def test_passes_when_approved(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
        target_id = uuid.uuid4()
        req = await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            target_id,
            api_requester.id,
        )
        await approvals_api.approve_stage(
            real_async_db_session, api_org.id, req.id, api_approver.id
        )
        # Should not raise.
        await approvals_api.check_and_block(
            real_async_db_session, api_org.id, 'document', target_id
        )

    async def test_raises_when_no_request_exists(
        self, real_async_db_session: AsyncSession, api_org: Organization
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
        with pytest.raises(ApprovalRequiredError):
            await approvals_api.check_and_block(
                real_async_db_session, api_org.id, 'document', uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# DTO shape contracts
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDtoShape:
    async def test_request_dto_decisions_contains_approver_id(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        result = await approvals_api.approve_stage(
            real_async_db_session,
            api_org.id,
            req.id,
            api_approver.id,
            notes='ok',
        )
        dec = result.decisions[0]
        assert dec.approver_id == api_approver.id
        assert dec.decided_at is not None
        assert dec.created_at is not None

    async def test_workflow_dto_stages_coerce_approver_user_ids(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_approver: User,
    ) -> None:
        # UUIDs are passed as strings to avoid the JSON-serialization edge case
        # in the existing ``stages`` JSON column (UUID objects are not JSON
        # serializable). The DTO coercion must then turn them back into UUIDs.
        approver_uuid = api_approver.id
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Restricted',
            [
                {
                    'order': 1,
                    'role': 'admin',
                    'label': 'Admin',
                    'approver_user_ids': [str(approver_uuid)],
                }
            ],
            is_active=True,
        )
        result = await approvals_api.get_active_workflow(
            real_async_db_session, api_org.id, 'document'
        )
        assert result is not None
        assert result.stages[0].approver_user_ids == [approver_uuid]

    async def test_request_dto_persists_decision_row(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
    ) -> None:
        """Approve through the API and verify a single PENDING decision
        existed before and a single APPROVED decision exists after."""
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        decisions_before = (
            (
                await real_async_db_session.execute(
                    select(ApprovalDecision).where(
                        ApprovalDecision.approval_request_id == req.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(decisions_before) == 1
        assert decisions_before[0].status == 'PENDING'

        await approvals_api.approve_stage(
            real_async_db_session, api_org.id, req.id, api_approver.id
        )
        decisions_after = (
            (
                await real_async_db_session.execute(
                    select(ApprovalDecision).where(
                        ApprovalDecision.approval_request_id == req.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(decisions_after) == 1
        assert decisions_after[0].status == 'APPROVED'

    async def test_request_row_state_after_full_flow(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
    ) -> None:
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
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
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        await approvals_api.approve_stage(
            real_async_db_session, api_org.id, req.id, api_approver.id
        )
        # Re-query the underlying request to confirm the persistence path.
        row = (
            (
                await real_async_db_session.execute(
                    select(ApprovalRequest).where(ApprovalRequest.id == req.id)
                )
            )
            .scalars()
            .one()
        )
        assert row.status == 'APPROVED'
        assert row.current_stage == 1

    # ------------------------------------------------------------------
    # pending_for_user_id filter
    # ------------------------------------------------------------------

    async def test_list_requests_filters_by_pending_for_user_open_stage(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
        api_approver2: User,
    ) -> None:
        """An open stage (empty approver list) surfaces for any user."""
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Open stage',
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
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )

        for user in (api_approver, api_approver2):
            visible = await approvals_api.list_requests(
                real_async_db_session,
                api_org.id,
                pending_for_user_id=user.id,
            )
            assert any(r.id == req.id for r in visible), (
                f'open-stage request must be visible to {user.id}'
            )

    async def test_list_requests_filters_by_pending_for_user_assigned(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
        api_approver2: User,
    ) -> None:
        """An assigned approver sees the request; another user does not."""
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Assigned stage',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'M',
                    'approver_user_ids': [str(api_approver.id)],
                }
            ],
            is_active=True,
        )
        req = await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )

        visible_to_assigned = await approvals_api.list_requests(
            real_async_db_session,
            api_org.id,
            pending_for_user_id=api_approver.id,
        )
        assert any(r.id == req.id for r in visible_to_assigned)

        visible_to_outsider = await approvals_api.list_requests(
            real_async_db_session,
            api_org.id,
            pending_for_user_id=api_approver2.id,
        )
        assert not any(r.id == req.id for r in visible_to_outsider)

    async def test_list_requests_filters_by_pending_for_user_terminal_excluded(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
    ) -> None:
        """Terminal (APPROVED/REJECTED/CANCELLED) requests are excluded."""
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Open stage',
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
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        await approvals_api.approve_stage(
            real_async_db_session, api_org.id, req.id, api_approver.id
        )

        visible = await approvals_api.list_requests(
            real_async_db_session,
            api_org.id,
            pending_for_user_id=api_approver.id,
        )
        assert not any(r.id == req.id for r in visible)

    async def test_list_requests_pending_for_user_multi_stage_current_only(
        self,
        real_async_db_session: AsyncSession,
        api_org: Organization,
        api_requester: User,
        api_approver: User,
        api_approver2: User,
    ) -> None:
        """Only the approver of the current stage sees the request."""
        await approvals_api.create_workflow(
            real_async_db_session,
            api_org.id,
            'document',
            'Two stage',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'M',
                    'approver_user_ids': [str(api_approver.id)],
                },
                {
                    'order': 2,
                    'role': 'admin',
                    'label': 'A',
                    'approver_user_ids': [str(api_approver2.id)],
                },
            ],
            is_active=True,
        )
        req = await approvals_api.request_approval(
            real_async_db_session,
            api_org.id,
            'document',
            uuid.uuid4(),
            api_requester.id,
        )
        # current_stage = 1 → only api_approver sees it.
        stage1_visible = await approvals_api.list_requests(
            real_async_db_session,
            api_org.id,
            pending_for_user_id=api_approver.id,
        )
        assert any(r.id == req.id for r in stage1_visible)
        stage2_visible = await approvals_api.list_requests(
            real_async_db_session,
            api_org.id,
            pending_for_user_id=api_approver2.id,
        )
        assert not any(r.id == req.id for r in stage2_visible)

        # Advance to stage 2 → only api_approver2 sees it.
        await approvals_api.approve_stage(
            real_async_db_session, api_org.id, req.id, api_approver.id
        )
        stage1_after = await approvals_api.list_requests(
            real_async_db_session,
            api_org.id,
            pending_for_user_id=api_approver.id,
        )
        stage2_after = await approvals_api.list_requests(
            real_async_db_session,
            api_org.id,
            pending_for_user_id=api_approver2.id,
        )
        assert not any(r.id == req.id for r in stage1_after)
        assert any(r.id == req.id for r in stage2_after)
