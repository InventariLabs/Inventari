from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from .schemas import RequesterScope, StageDefinition

ApprovalMetaData = dict[str, Any]


class ApprovalWorkflowDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    target_type: str
    name: str
    stages: list[StageDefinition]
    is_active: bool
    requester_scope: RequesterScope
    created_at: datetime
    updated_at: datetime | None = None
    archived_at: datetime | None = None

    @field_validator('stages', mode='before')
    @classmethod
    def _coerce_stages(cls, value: Any) -> Any:
        """Accept raw ``list[dict]`` from the DB JSON column and validate each
        entry against :class:`StageDefinition` so the API contract stays typed.
        """
        if value and isinstance(value, list) and isinstance(value[0], dict):
            return [StageDefinition.model_validate(stage) for stage in value]
        return value


class ApprovalDecisionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    approval_request_id: UUID
    stage_order: int
    approver_id: UUID | None = None
    status: str
    notes: str | None = None
    decided_at: datetime | None = None
    created_at: datetime


class ApprovalRequestDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    workflow_id: UUID
    target_type: str
    target_id: UUID
    status: str
    current_stage: int
    total_stages: int
    created_by: UUID
    meta_data: ApprovalMetaData | None = None
    created_at: datetime
    # Withdrawal is a terminal outcome like any decision, and a consumer has
    # to be able to say when it happened. Additive and optional, so existing
    # callers are unaffected.
    cancelled_by: UUID | None = None
    cancelled_at: datetime | None = None
    # A spend of the approval, for a target that acts once: set when the act
    # it authorised happened. NULL both for a target that never spends its
    # approvals (a document) and for one not yet acted on.
    consumed_at: datetime | None = None
    consumed_by: UUID | None = None
    decisions: list[ApprovalDecisionDTO] = []
    target_summary: dict[str, Any] | None = None


class FirstStageVerdictDTO(BaseModel):
    """Whether every stage a new request would pass has anybody to decide it."""

    solvable: bool
    undecidable_reason: str | None = None
    stage_label: str | None = None
