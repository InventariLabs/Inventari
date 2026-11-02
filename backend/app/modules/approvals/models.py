import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_facade import Base
from app.models.user import User


class ApprovalWorkflow(Base):
    __tablename__ = 'approval_workflows'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    #: Whose submissions the workflow holds: ``{"everyone": true}``, or
    #: ``{"everyone": false, "user_ids": [...], "role_ids": [...]}`` naming
    #: people and roles (the ids ``core_api.roles.list_for_org_async`` lists).
    #: Anybody else's document, order or checkout goes through without an
    #: approval. A role is read when something is submitted, so moving a
    #: person out of it frees their next submission; open requests stay.
    #: Workflows saved before the choice existed held everyone, and the
    #: column's default keeps them doing so.
    requester_scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text('\'{"everyone": true}\'::jsonb')
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    #: Set when a workflow with history is deleted. An archived workflow is
    #: off the list and frozen: its requests still read their stages from it,
    #: so nothing may rewrite them, and the next workflow for the same target
    #: type is a new row beside it.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # One live workflow per target type; archived ones step aside.
        Index(
            'uq_workflow_org_target',
            'organization_id',
            'target_type',
            unique=True,
            postgresql_where=text('archived_at IS NULL'),
        ),
    )


#: The states in which a request is still waiting on somebody.
OPEN_STATUSES = ('PENDING', 'IN_PROGRESS')


class ApprovalRequest(Base):
    __tablename__ = 'approval_requests'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('approval_workflows.id', ondelete='RESTRICT'),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='PENDING')
    current_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_stages: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: When an approval is spent rather than merely granted. Some targets ask
    #: for a decision that authorises one act -- an equipment checkout is the
    #: case that made this necessary -- and the approval has to stop passing
    #: the gate once that act has happened. A target whose approval is instead
    #: a state of the record (a document moves to CONFIRMED) leaves this NULL
    #: and the gate keeps answering as before.
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consumed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    workflow: Mapped['ApprovalWorkflow'] = relationship('ApprovalWorkflow')
    #: Stage order, not the table's: a row's new version lands wherever the
    #: page has room when a stage is decided, so the physical order is the
    #: table's history. Every reader -- the enriched trace, the document
    #: card, the queue -- needs the workflow's order without sorting.
    decisions: Mapped[list['ApprovalDecision']] = relationship(
        'ApprovalDecision',
        back_populates='request',
        cascade='all, delete-orphan',
        lazy='selectin',
        order_by=lambda: (
            ApprovalDecision.stage_order,
            ApprovalDecision.created_at,
            ApprovalDecision.id,
        ),
    )
    creator: Mapped['User'] = relationship('User', foreign_keys=[created_by])
    canceller: Mapped['User | None'] = relationship('User', foreign_keys=[cancelled_by])

    __table_args__ = (
        Index(
            'ix_approval_requests_target',
            'target_type',
            'target_id',
            'organization_id',
        ),
        Index(
            'uq_pending_request',
            'organization_id',
            'target_type',
            'target_id',
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'IN_PROGRESS')"),
        ),
    )


class ApprovalDecision(Base):
    __tablename__ = 'approval_decisions'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('approval_requests.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    stage_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='PENDING')
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    request: Mapped['ApprovalRequest'] = relationship(
        'ApprovalRequest', back_populates='decisions'
    )
    approver: Mapped['User | None'] = relationship('User', foreign_keys=[approver_id])
