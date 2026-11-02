"""Two acts the organization log used to miss entirely.

The journal's own contract says a state-changing act on a record an
organization owns writes one row here. Editing fifty items at once wrote
only the per-item history and said so in a comment; taking somebody out of
the organization wrote nothing at all, while inviting them and changing
their role both wrote. Access changes are a first-order audit category
precisely because they are the ones an intruder would want unrecorded.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.services.items._date_meta import legacy_date_in_meta


def _entries(db_session: Session, org_id: UUID, target_type: str) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == target_type,
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


@pytest.mark.integration
class TestTheLogSeesABulkEdit:
    def test_editing_two_items_at_once_writes_two_entries(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_items_batch: list[Item],
    ) -> None:
        org_id = test_items_batch[0].organization_id
        before = len(_entries(db_session, org_id, 'item'))

        targets = test_items_batch[:2]
        resp = client.patch(
            '/api/v1/items/bulk',
            headers=auth_headers,
            json={
                'item_ids': [str(i.id) for i in targets],
                'update_data': {'brand': 'Back Room Brand'},
            },
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        entries = _entries(db_session, org_id, 'item')
        assert len(entries) - before == 2
        latest = entries[-2:]
        for entry in latest:
            assert entry.meta_data is not None
            assert entry.meta_data.get('bulk') is True
            assert entry.snapshot is not None
            assert entry.snapshot['after']['brand'] == 'Back Room Brand'

    def test_the_bulk_row_names_what_the_record_took(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_items_batch: list[Item],
    ) -> None:
        """The bulk row says what the record took, nothing else.

        A freeze date used to be the example of a field the record lacks:
        the setattr loop dropped it, and the snapshot named it anyway. The
        batch now keeps it where the single edit keeps it, in ``meta_data``,
        so the row names it — beside the date it replaced, not a blank. That
        no field of the schema is left without a writer is held on its own,
        in ``test_the_bulk_edit_writes_what_it_accepts``.
        """
        org_id = test_items_batch[0].organization_id
        target = test_items_batch[0]
        frozen_before = legacy_date_in_meta(target.meta_data, 'freeze_date')
        assert frozen_before is not None

        resp = client.patch(
            '/api/v1/items/bulk',
            headers=auth_headers,
            json={
                'item_ids': [str(target.id)],
                'update_data': {'freeze_date': '2026-12-01', 'brand': 'Held Brand'},
            },
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        entry = _entries(db_session, org_id, 'item')[-1]
        assert entry.snapshot is not None
        assert entry.snapshot['before']['freeze_date'] == frozen_before
        assert entry.snapshot['after']['freeze_date'] == '2026-12-01'
        assert entry.snapshot['after']['brand'] == 'Held Brand'


@pytest.mark.integration
class TestTheLogSeesAMemberLeaving:
    def test_removing_a_member_writes_an_entry(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_household,
        test_user,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        member = h.create_user(test_household, email='leaving@example.com')
        db_session.commit()

        before = len(_entries(db_session, test_household.id, 'org_member'))
        resp = client.post(
            f'/api/v1/organizations/my/remove-member/{member.id}',
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        entries = _entries(db_session, test_household.id, 'org_member')
        assert len(entries) - before == 1
        entry = entries[-1]
        assert entry.snapshot is not None
        assert entry.snapshot['name'] == 'leaving@example.com'
        assert entry.snapshot['before']['organization'] is True
        assert entry.snapshot['after']['organization'] is False
