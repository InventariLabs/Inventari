"""The two guarded write tools, through the posting rules they owe.

Every test here reads the database after the MCP call: the point of a write
tool is not the answer it returns but the rows it leaves — the record, its
movement, the item history, the register copy and the journal entry naming
the key.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.mcp_server.tests.conftest import KEY_PERMISSIONS, issue_key
from app.modules.warehouse.models import Document, DocumentLine


def _structured(result: dict) -> dict:
    assert result.get('isError') is not True, result
    return result['structuredContent']


def _refusal(result: dict) -> str:
    assert result['isError'] is True, result
    return result['content'][0]['text']


def _record(db: Session, item_id: UUID) -> Item:
    record = db.get(Item, item_id)
    assert record is not None
    return record


def _changes(history: ItemHistory | None) -> dict[str, Any]:
    assert history is not None
    changes = history.changes
    assert changes is not None
    return changes


def _meta(entry: AuditLog) -> dict[str, Any]:
    assert entry.meta_data is not None
    return entry.meta_data


def _audit_rows(db: Session, org: Organization, item_id: UUID) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org.id,
                AuditLog.target_id == item_id,
            )
            .order_by(AuditLog.created_at.desc())
        ).all()
    )


class TestCreateItem:
    def test_writes_the_record_its_opening_movement_and_the_reason(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org: Organization,
        mcp_write_key: str,
        shelf: StorageLocation,
    ) -> None:
        result = mcp_tool(
            mcp_write_key,
            'create_item',
            {'name': 'MCP Basil', 'quantity': 4, 'location_id': str(shelf.id)},
        )

        payload = _structured(result)
        db_session.expire_all()
        record = db_session.get(Item, UUID(payload['id']))
        assert record is not None
        assert record.organization_id == mcp_org.id
        assert record.name == 'MCP Basil'
        assert Decimal(str(record.quantity)) == Decimal('4')

        moves = db_session.scalars(
            select(StockMove).where(
                StockMove.organization_id == mcp_org.id,
                StockMove.reference_id == record.id,
            )
        ).all()
        assert len(moves) == 1
        assert moves[0].to_location_id == shelf.id
        assert moves[0].from_location_id is None
        assert Decimal(str(moves[0].quantity)) == Decimal('4')

        history = db_session.scalars(
            select(ItemHistory)
            .where(ItemHistory.item_id == record.id)
            .order_by(ItemHistory.created_at.desc())
        ).first()
        changes = _changes(history)
        assert changes['reason'] == 'mcp_create'
        assert changes['mcp_request_id']

        call = next(
            row
            for row in _audit_rows(db_session, mcp_org, record.id)
            if (row.meta_data or {}).get('tool') == 'create_item'
        )
        assert call.reason == 'mcp_create'
        meta = _meta(call)
        assert meta['actor'] == {
            'type': 'api_key',
            'key_prefix': mcp_write_key[:15],
        }
        assert meta['mcp_request_id'] == changes['mcp_request_id']

    def test_needs_items_write(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org: Organization,
        mcp_user: User,
        shelf: StorageLocation,
    ) -> None:
        key = issue_key(
            db_session, mcp_org, mcp_user, permissions=list(KEY_PERMISSIONS)
        )

        result = mcp_tool(
            key,
            'create_item',
            {'name': 'MCP No Write', 'quantity': 1, 'location_id': str(shelf.id)},
        )

        assert 'PERMISSION_REQUIRED' in _refusal(result)
        assert (
            db_session.scalars(select(Item).where(Item.name == 'MCP No Write')).first()
            is None
        )


class TestCorrectStock:
    def test_one_adjustment_movement_named_by_the_calls_uuid(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org: Organization,
        mcp_write_key: str,
        item: Item,
    ) -> None:
        result = mcp_tool(
            mcp_write_key,
            'correct_stock',
            {
                'item_id': str(item.id),
                'quantity': 3,
                'reason': 'Two bottles broke in the cold room',
            },
        )

        payload = _structured(result)
        reference = UUID(payload['reference'])
        assert payload['reference'] != str(item.id)
        db_session.expire_all()
        moves = db_session.scalars(
            select(StockMove).where(StockMove.reference_id == reference)
        ).all()
        assert len(moves) == 1
        assert moves[0].reference_type == 'adjustment'
        assert moves[0].from_location_id == item.storage_location_id
        assert moves[0].to_location_id is None
        assert Decimal(str(moves[0].quantity)) == Decimal('2')

        assert Decimal(str(_record(db_session, item.id).quantity)) == Decimal('3')

        history = db_session.scalars(
            select(ItemHistory)
            .where(ItemHistory.item_id == item.id)
            .order_by(ItemHistory.created_at.desc())
        ).first()
        changes = _changes(history)
        assert changes['reason'] == 'mcp_correction'
        assert changes['reason_text'] == 'Two bottles broke in the cold room'
        assert changes['mcp_request_id'] == str(reference)

        call = next(
            row
            for row in _audit_rows(db_session, mcp_org, item.id)
            if (row.meta_data or {}).get('tool') == 'correct_stock'
        )
        assert call.reason == 'mcp_correction'
        meta = _meta(call)
        assert meta['actor'] == {
            'type': 'api_key',
            'key_prefix': mcp_write_key[:15],
        }
        assert meta['mcp_request_id'] == str(reference)

    def test_the_register_copy_is_absent_while_warehouse_is_off(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org: Organization,
        mcp_write_key: str,
        item: Item,
    ) -> None:
        result = mcp_tool(
            mcp_write_key,
            'correct_stock',
            {'item_id': str(item.id), 'quantity': 4, 'reason': 'Counted four'},
        )

        payload = _structured(result)
        assert payload['register_document_id'] is None
        assert payload['register_document_number'] is None
        reference = f'mcp:{payload["reference"]}'
        assert (
            db_session.scalars(
                select(Document).where(Document.external_reference == reference)
            ).first()
            is None
        )

    def test_warehouse_on_writes_the_register_document(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org: Organization,
        mcp_write_key: str,
        item: Item,
    ) -> None:
        mcp_org.enabled_modules = [*(mcp_org.enabled_modules or []), 'warehouse']
        db_session.commit()

        result = mcp_tool(
            mcp_write_key,
            'correct_stock',
            {'item_id': str(item.id), 'quantity': 4, 'reason': 'Counted four'},
        )

        payload = _structured(result)
        assert payload['register_document_id'] is not None
        assert payload['register_document_number'] is not None
        db_session.expire_all()
        document = db_session.get(Document, UUID(payload['register_document_id']))
        assert document is not None
        assert document.status == 'COMPLETED'
        assert document.external_reference == f'mcp:{payload["reference"]}'
        lines = db_session.scalars(
            select(DocumentLine).where(DocumentLine.document_id == document.id)
        ).all()
        assert len(lines) == 1
        assert lines[0].item_id == item.id
        assert Decimal(str(lines[0].quantity)) == Decimal('-1')
        assert lines[0].notes == 'Counted four'

    def test_a_missing_reason_is_refused_and_changes_nothing(
        self,
        mcp_tool,
        db_session: Session,
        mcp_write_key: str,
        item: Item,
    ) -> None:
        result = mcp_tool(
            mcp_write_key,
            'correct_stock',
            {'item_id': str(item.id), 'quantity': 3, 'reason': '   '},
        )

        assert 'REASON_REQUIRED' in _refusal(result)
        db_session.expire_all()
        assert Decimal(str(_record(db_session, item.id).quantity)) == Decimal('5')
        assert (
            db_session.scalars(
                select(StockMove).where(
                    StockMove.reference_type == 'adjustment',
                    StockMove.organization_id == item.organization_id,
                )
            ).first()
            is None
        )

    def test_needs_items_write(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org: Organization,
        mcp_user: User,
        item: Item,
    ) -> None:
        key = issue_key(
            db_session, mcp_org, mcp_user, permissions=list(KEY_PERMISSIONS)
        )

        result = mcp_tool(
            key,
            'correct_stock',
            {'item_id': str(item.id), 'quantity': 3, 'reason': 'A reason'},
        )

        assert 'PERMISSION_REQUIRED' in _refusal(result)
        db_session.expire_all()
        assert Decimal(str(_record(db_session, item.id).quantity)) == Decimal('5')

    def test_items_write_alone_is_enough(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org: Organization,
        mcp_user: User,
        item: Item,
    ) -> None:
        """The tool's own gate is items:write; it does not also demand read."""
        key = issue_key(
            db_session,
            mcp_org,
            mcp_user,
            permissions=['mcp_server:use', 'items:write'],
        )

        result = mcp_tool(
            key,
            'correct_stock',
            {'item_id': str(item.id), 'quantity': 2, 'reason': 'A reason'},
        )

        assert Decimal(str(_structured(result)['quantity'])) == Decimal('2')

    def test_another_organizations_record_does_not_open(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org_b: Organization,
        mcp_user_b: User,
        item: Item,
    ) -> None:
        key = issue_key(
            db_session,
            mcp_org_b,
            mcp_user_b,
            permissions=[*KEY_PERMISSIONS, 'items:write'],
        )

        result = mcp_tool(
            key,
            'correct_stock',
            {'item_id': str(item.id), 'quantity': 1, 'reason': 'A reason'},
        )

        assert 'ITEM_NOT_FOUND' in _refusal(result)
        db_session.expire_all()
        assert Decimal(str(_record(db_session, item.id).quantity)) == Decimal('5')

    def test_an_unknown_record_is_refused(
        self,
        mcp_tool,
        mcp_write_key: str,
    ) -> None:
        result = mcp_tool(
            mcp_write_key,
            'correct_stock',
            {
                'item_id': '00000000-0000-0000-0000-000000000001',
                'quantity': 1,
                'reason': 'A reason',
            },
        )

        assert 'ITEM_NOT_FOUND' in _refusal(result)
