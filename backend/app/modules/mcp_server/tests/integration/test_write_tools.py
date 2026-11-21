"""The two guarded write tools, through the posting rules they owe.

Every test here reads the database after the MCP call: the point of a write
tool is not the answer it returns but the rows it leaves — the record, its
movement, the item history, the register copy and the journal entry naming
the key.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.public_api import core_api
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

    def test_a_barcode_given_on_create_reads_back_and_is_searchable(
        self,
        mcp_tool,
        db_session: Session,
        mcp_write_key: str,
        shelf: StorageLocation,
    ) -> None:
        """The code lives on the product card, and the read tools follow it there.

        The record created with a barcode is read back by ``get_item`` with
        that barcode, ``search_items`` finds the stock row by the code, and
        both agree with the product card the workspace holds.
        """
        code = '5901234123457'
        created = _structured(
            mcp_tool(
                mcp_write_key,
                'create_item',
                {
                    'name': 'Olive oil 500 ml',
                    'quantity': 6,
                    'location_id': str(shelf.id),
                    'barcode': code,
                },
            )
        )
        assert created['barcode'] == code

        read_back = _structured(
            mcp_tool(mcp_write_key, 'get_item', {'item_id': created['id']})
        )
        assert read_back['item']['barcode'] == code

        found = _structured(mcp_tool(mcp_write_key, 'search_items', {'query': code}))
        assert [row['id'] for row in found['stock']] == [created['id']]
        assert found['stock'][0]['barcode'] == code

        db_session.expire_all()
        record = _record(db_session, UUID(created['id']))
        assert record.template is not None
        assert record.template.barcode == code

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

    def test_a_negative_quantity_is_refused_readably(
        self,
        mcp_tool,
        db_session: Session,
        mcp_write_key: str,
        shelf: StorageLocation,
    ) -> None:
        """The refusal names the code, where the DTO's refusal was a bare error.

        A negative quantity never reaches the DTO: the tool refuses it with
        QUANTITY_INVALID, so the model is told what was wrong instead of
        reading "Error executing tool create_item".
        """
        result = mcp_tool(
            mcp_write_key,
            'create_item',
            {
                'name': 'MCP Negative',
                'quantity': -2,
                'location_id': str(shelf.id),
            },
        )

        assert 'QUANTITY_INVALID' in _refusal(result)
        assert (
            db_session.scalars(select(Item).where(Item.name == 'MCP Negative')).first()
            is None
        )

    def test_no_location_is_refused_by_name_and_points_at_the_shelf_tools(
        self,
        mcp_tool,
        db_session: Session,
        mcp_write_key: str,
    ) -> None:
        """A record stands on a shelf, and the client learns which tool lists one.

        An omitted argument has to arrive as a named refusal that points at
        list_locations, not as the server library's validation text with a
        pydantic link, which tells an agent neither what is missing nor what
        to call next.
        """
        result = mcp_tool(mcp_write_key, 'create_item', {'name': 'MCP Nowhere'})

        refusal = _refusal(result)
        assert 'LOCATION_REQUIRED' in refusal
        assert 'list_locations' in refusal
        assert (
            db_session.scalars(select(Item).where(Item.name == 'MCP Nowhere')).first()
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

    def test_a_correction_committed_before_the_lock_is_the_baseline(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org: Organization,
        mcp_user: User,
        mcp_write_key: str,
        item: Item,
        monkeypatch,
    ) -> None:
        """The difference is measured under the lock, not on the pre-lock read.

        Another operator's correction takes the record from 5 to 7 and
        commits between this call's first read and its lock. The correction
        to 3 is then a change of -4 everywhere it is written: the movement,
        the register's line, the answer's previous quantity and the journal's
        before. Measured on the pre-lock read it was -2 in the register and
        in the answer beside a ledger that moved -4 — one document with the
        wrong sign for a change nobody made.
        """
        mcp_org.enabled_modules = [*(mcp_org.enabled_modules or []), 'warehouse']
        db_session.commit()

        first_read = core_api.items.get_async
        committed = False

        async def read_then_another_correction(db, organization_id, item_id):
            nonlocal committed
            found = await first_read(db, organization_id, item_id)
            if not committed:
                committed = True
                # A connection of its own, so the change commits for real
                # while this request's transaction is open and has read.
                async with AsyncSession(bind=db.bind, expire_on_commit=False) as other:
                    await core_api.items.update_quantity_async(
                        other,
                        organization_id,
                        item_id,
                        Decimal('7'),
                        user_id=mcp_user.id,
                        move_reference_type='adjustment',
                        move_reference_id=uuid4(),
                    )
                    await other.commit()
            return found

        monkeypatch.setattr(core_api.items, 'get_async', read_then_another_correction)

        result = mcp_tool(
            mcp_write_key,
            'correct_stock',
            {'item_id': str(item.id), 'quantity': 3, 'reason': 'Counted three'},
        )

        payload = _structured(result)
        assert Decimal(str(payload['previous_quantity'])) == Decimal('7')
        assert payload['register_document_id'] is not None

        db_session.expire_all()
        moves = db_session.scalars(
            select(StockMove).where(
                StockMove.reference_id == UUID(payload['reference'])
            )
        ).all()
        assert len(moves) == 1
        assert Decimal(str(moves[0].quantity)) == Decimal('4')

        lines = db_session.scalars(
            select(DocumentLine).where(
                DocumentLine.document_id == UUID(payload['register_document_id'])
            )
        ).all()
        assert len(lines) == 1
        assert Decimal(str(lines[0].quantity)) == Decimal('-4')

        call = next(
            row
            for row in _audit_rows(db_session, mcp_org, item.id)
            if (row.meta_data or {}).get('tool') == 'correct_stock'
        )
        assert call.snapshot is not None
        assert Decimal(call.snapshot['before']['quantity']) == Decimal('7')
        assert Decimal(str(_record(db_session, item.id).quantity)) == Decimal('3')

    def test_a_record_moved_while_the_call_waited_locks_its_new_group_too(
        self,
        mcp_tool,
        db_session: Session,
        mcp_org: Organization,
        mcp_user: User,
        mcp_write_key: str,
        item: Item,
        monkeypatch,
    ) -> None:
        """The group the record stands in once the call holds it is locked as well.

        Another operator moves the record to a second shelf and commits between
        this call's first read and its lock. The call locked the group it read,
        (product, first shelf); the record it then holds writes (product,
        second shelf), so that group is locked too before the first write, and
        the correction is posted where the record stands.

        That second lock is taken while the first one is held, after it, and
        so outside the one sorted order the Stock Posting Rules ask for. A
        single move during the wait, as here, cannot deadlock on it — nothing
        holds the new group in the other order. Two corrections that each find
        their record moved into the group the other locked first would wait on
        each other; PostgreSQL detects that deadlock and aborts one of the two
        transactions, whose tool call fails and posts nothing, and the agent
        can call it again.
        """
        second_shelf = StorageLocation(
            organization_id=mcp_org.id,
            created_by=mcp_user.id,
            name='Cold Storage B',
        )
        db_session.add(second_shelf)
        db_session.commit()
        first_shelf_id = item.storage_location_id
        second_shelf_id = second_shelf.id
        template_id = item.template_id

        first_read = core_api.items.get_async
        moved = False

        async def read_then_another_move(db, organization_id, item_id):
            nonlocal moved
            found = await first_read(db, organization_id, item_id)
            if not moved:
                moved = True
                # A connection of its own, so the move commits for real while
                # this request's transaction is open and has read.
                async with AsyncSession(bind=db.bind, expire_on_commit=False) as other:
                    await core_api.items.transfer_async(
                        other,
                        organization_id,
                        item_id,
                        second_shelf_id,
                        user_id=mcp_user.id,
                    )
                    await other.commit()
            return found

        locked: list[list[tuple[UUID, UUID | None]]] = []
        lock = core_api.stock.lock_async

        async def recording_lock(db, organization_id, *, keys=(), **kwargs):
            locked.append(list(keys))
            await lock(db, organization_id, keys=keys, **kwargs)

        monkeypatch.setattr(core_api.items, 'get_async', read_then_another_move)
        monkeypatch.setattr(core_api.stock, 'lock_async', recording_lock)

        result = mcp_tool(
            mcp_write_key,
            'correct_stock',
            {'item_id': str(item.id), 'quantity': 3, 'reason': 'Counted three'},
        )

        payload = _structured(result)
        assert locked == [
            [(template_id, first_shelf_id)],
            [(template_id, second_shelf_id)],
        ]
        db_session.expire_all()
        record = _record(db_session, item.id)
        assert record.storage_location_id == second_shelf_id
        assert Decimal(str(record.quantity)) == Decimal('3')
        moves = db_session.scalars(
            select(StockMove).where(
                StockMove.reference_id == UUID(payload['reference'])
            )
        ).all()
        assert len(moves) == 1
        assert moves[0].from_location_id == second_shelf_id
