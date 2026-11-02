from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.exceptions import ServiceRejectionError

from .target_types import TargetType


class StageDefinition(BaseModel):
    """One stage of a workflow: its name and the people who decide it.

    An empty ``approver_user_ids`` is an open stage, decided by anyone who
    holds the approve grant. Stages saved before this shape also carry a
    ``role`` — a free-form label that never decided anything — which the
    schema now leaves out of what it reads and returns.
    """

    order: int
    label: str
    approver_user_ids: list[UUID] = []


class WorkflowScopeCondition(BaseModel):
    """One filter a module's settings put on what a workflow holds.

    ``document_types`` lists the kinds always held; ``value_above`` holds
    whatever is worth more than ``amount`` (in ``currency``) and, with
    ``unpriced_included``, whatever has no value to compare;
    ``foreign_currency`` holds anything priced in another currency than the
    organization's, which no threshold can be compared with.
    """

    kind: Literal['document_types', 'value_above', 'foreign_currency']
    document_types: list[str] = []
    amount: Decimal | None = None
    currency: str | None = None
    unpriced_included: bool = False


class WorkflowScope(BaseModel):
    """What an active workflow for a target type holds, in the owner's words.

    Answered by the module that owns the target and its gate, so the sentence
    an administrator reads before switching a workflow on is the rule the
    gate then applies. ``all`` with no ``required_by_settings`` is the
    workflow itself being the rule (the settings name nothing); ``nothing``
    is a workflow that holds nothing until the module's settings ask.
    ``required_by_settings`` names the settings that demand an approval of
    their own, whatever the workflow.
    """

    holds: Literal['all', 'some', 'nothing']
    conditions: list[WorkflowScopeCondition] = []
    required_by_settings: list[str] = []


class RequesterScope(BaseModel):
    """Whose submissions a workflow holds.

    ``everyone``, or the people and roles named — a role by the id the roles
    list gives it, the built-in levels included. Anybody else's document,
    order or checkout goes through without an approval. Choosing people and
    naming nobody is refused rather than read as "nobody": a workflow that
    holds nobody is a workflow switched off, and that is a different button.
    """

    everyone: bool
    user_ids: list[UUID] = []
    role_ids: list[UUID] = []

    @model_validator(mode='after')
    def _names_somebody(self) -> 'RequesterScope':
        if self.everyone and (self.user_ids or self.role_ids):
            raise ServiceRejectionError('approval_requester_scope_everyone_with_names')
        if not self.everyone and not (self.user_ids or self.role_ids):
            raise ServiceRejectionError('approval_requester_scope_names_nobody')
        return self


class RequesterLabel(BaseModel):
    """One person or role a workflow holds, named for the card that lists it."""

    kind: Literal['user', 'role']
    id: UUID
    name: str
    #: A built-in level, whose name the screen translates.
    is_system: bool = False


_EXPECTED_SCOPE_DESCRIPTION = (
    'The scope the switch-on dialog showed: the `scope` of the workflow as '
    'the workflow list returns it. {when} wherever the target type says what '
    'a workflow holds (422 `APPROVAL_SCOPE_REQUIRED`, naming this field, '
    'otherwise), so a script cannot bring a workflow into force under a rule '
    'it never read. The server answers 409 `APPROVAL_SCOPE_CHANGED` when the '
    'live scope differs. Not needed for a target type with no scope '
    'provider, for switching off, or for editing a workflow that is already '
    'on. The scope is readable from the list only, so a client creates the '
    'workflow off, reads its scope, then switches it on.'
)


class WorkflowCreate(BaseModel):
    target_type: TargetType
    name: str
    stages: list[StageDefinition]
    #: A workflow comes into force only when somebody switches it on, knowing
    #: what it will hold — so it is saved off unless the caller says otherwise.
    is_active: bool = False
    #: Whose submissions it holds. No default: the choice is the
    #: administrator's to make, never one an omitted field makes for them.
    requester_scope: RequesterScope
    #: Save a stage nobody could decide. The refusal is the default; this
    #: flag is the administrator saying they read it and mean it.
    allow_undecidable_stages: bool = False
    expected_scope: WorkflowScope | None = Field(
        default=None,
        description=_EXPECTED_SCOPE_DESCRIPTION.format(
            when='Required with `is_active: true`'
        ),
    )


class WorkflowUpdate(BaseModel):
    name: str | None = None
    stages: list[StageDefinition] | None = None
    is_active: bool | None = None
    requester_scope: RequesterScope | None = None
    allow_undecidable_stages: bool = False
    expected_scope: WorkflowScope | None = Field(
        default=None,
        description=_EXPECTED_SCOPE_DESCRIPTION.format(
            when='Required when the update switches an inactive workflow on'
        ),
    )


class WaitingRequestSchema(BaseModel):
    """One open request standing on a workflow, named the way its owner names it."""

    request_id: UUID
    target_type: str
    target_id: UUID
    #: The target's number or name, from the module that owns it.
    label: str


class WorkflowSchema(BaseModel):
    id: UUID
    organization_id: UUID
    target_type: str
    name: str
    stages: list[StageDefinition]
    is_active: bool
    requester_scope: RequesterScope
    created_at: datetime
    updated_at: datetime | None = None
    # When the workflow was deleted with history behind it. An archived
    # workflow is off the list and frozen; it is still read by its requests.
    archived_at: datetime | None = None
    # Whether every stage of this workflow has somebody who could decide it,
    # and at the first stage that does not, why — the same codes the enriched
    # request carries. ``None`` where the endpoint does not answer it (create,
    # update, single read); the list fills it for every row, so a dead end is
    # visible where it is fixed rather than where it parks a document.
    solvable: bool | None = None
    undecidable_reason: str | None = None
    # What the workflow holds while it is on — or would hold once switched on.
    # The list fills it for every row whose target type has a scope provider.
    scope: WorkflowScope | None = None
    # The people and roles ``requester_scope`` names, by name, for the card.
    # Filled by the list; empty for a workflow that holds everyone.
    requesters: list[RequesterLabel] = []
    # The requests already parked on a workflow that is a dead end: the
    # warning on the row is today's problem, not a theory, and these are the
    # records to open. Filled by the list only, and only for the dead ends.
    waiting_requests: list[WaitingRequestSchema] = []

    model_config = ConfigDict(from_attributes=True)


class WorkflowConfigured(BaseModel):
    """Whether a request for this target type would land anywhere.

    ``True`` is the engine's own test before it writes a request: an
    active workflow with at least one stage. Both refusals are covered
    here — no active workflow (``approval_no_active_workflow``) and an
    active one with no stages (``approval_workflow_no_stages``) — so the
    screen that offers the request button and the endpoint that receives
    it are one rule, asked twice.
    """

    configured: bool


class ApprovalDecisionSchema(BaseModel):
    id: UUID
    stage_order: int
    approver_id: UUID | None = None
    approver_name: str | None = None
    status: str
    notes: str | None = None
    decided_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApprovalRequestSchema(BaseModel):
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    target_type: str
    target_id: UUID
    status: str
    current_stage: int
    total_stages: int
    created_by: UUID
    created_by_name: str | None = None
    cancelled_by: UUID | None = None
    cancelled_at: datetime | None = None
    meta_data: dict[str, Any] | None = None
    workflow_stages: list[StageDefinition] | None = None
    decisions: list[ApprovalDecisionSchema] = []
    created_at: datetime
    target_summary: dict[str, Any] | None = None
    # the decision rule answered once, on the server, for the person
    # holding this response. ``None`` when the endpoint names no viewer.
    viewer_can_decide: bool | None = None
    # Whether the stage this request waits at has anybody who could decide
    # it, and if not, why — a dead end must not read as an empty queue.
    # ``None`` for the requests that are not waiting on anyone.
    solvable: bool | None = None
    undecidable_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ApproveRequest(BaseModel):
    notes: str | None = None


class RejectRequest(BaseModel):
    notes: str | None = None


class RequestApproval(BaseModel):
    target_type: str
    target_id: UUID
    meta_data: dict[str, Any] | None = None


class WaitingOnTarget(BaseModel):
    """How many requests of one kind of target wait on a workflow."""

    target_type: str
    count: int


class WorkflowWaiting(BaseModel):
    """What switching a workflow off would release, and what still demands it.

    ``settings_requiring_approval`` names the settings of the owning module
    that keep asking for an approval; released items would meet that demand
    with no workflow to carry it out.
    """

    total: int
    waiting: list[WaitingOnTarget]
    settings_requiring_approval: list[str]


class WorkflowDeletionResult(BaseModel):
    """What became of a workflow the user asked to delete.

    ``archived`` means it was kept because requests were already raised
    under it: it is off the list, frozen, and a new workflow for its target
    type is a new row. ``requests_kept`` counts those requests.
    """

    archived: bool
    requests_kept: int


class DocumentApprovalRequirement(BaseModel):
    """Whether confirming this document would send it to the approval queue.

    The answer to the one rule (``document_gate.document_needs_approval_async``),
    published so a screen about to confirm the document can name the
    consequence instead of recomputing the rule from a workflow list and a
    profile.
    """

    approval_required: bool
    #: Whether anyone can actually sign it off. The profile may demand an
    #: approval while the organization has no workflow to carry it out — the
    #: server then refuses confirmation — and a dialog that promised the
    #: approval queue in that state was promising an answer the server would
    #: deny. One rule, asked once, both halves published together.
    workflow_configured: bool = False
    #: Whether the stage the request would wait at has anybody who could
    #: decide it for the person asking. ``False`` only where the document
    #: would be sent to the queue (``approval_required`` and a configured
    #: workflow) and that stage is a dead end — confirming would park it
    #: where nobody can answer, and the dialog has to say so before the click.
    approval_solvable: bool = True
    #: Why, in the stable codes the approvals module uses for a dead end.
    undecidable_reason: str | None = None
    #: What the stage that nobody can decide is called.
    undecidable_stage: str | None = None
