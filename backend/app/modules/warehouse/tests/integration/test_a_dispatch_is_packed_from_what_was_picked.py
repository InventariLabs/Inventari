"""A dispatch is packed from what was picked, and nothing else.

Packing sits between "all picked" and completion. A package holds goods that
came off the shelf and are not in another box yet — the line's picked
quantity (``done_quantity``, which the picking session writes) is the bound,
shared by every package of the document. Packing is optional, it is open
only while the dispatch is confirmed, and every package write leaves an entry
in the organization's journal.

The service is called directly on a real ``AsyncSession`` so the statements
are attributed to coverage; the HTTP doors are in the sibling file
``test_packing_endpoints.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditTargetType
from app.core.exceptions import EntityNotFoundError, ServiceRejectionError
from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.modules.warehouse import packing_service as svc
from app.modules.warehouse._picking_session_ops import (
    cancel_pick_session_async,
    confirm_short_pick_async,
    skip_pick_line_async,
    undo_pick_async,
)
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentPackage,
    DocumentPackageLine,
    DocumentStatus,
    WmsPickLine,
    WmsPickSession,
)
from app.modules.warehouse.schemas import DocumentComplete, DocumentLineExecution
from app.modules.warehouse.services import complete_document


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Packing Org', enabled_modules=['core', 'warehouse'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def user(real_async_db_session: AsyncSession, org: Organization) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session, org, email='packer@example.com', role='admin'
    )


async def _dispatch(
    db: AsyncSession,
    org: Organization,
    user: User,
    picked: list[tuple[str, Decimal, Decimal]],
    *,
    doc_type: str = 'OUT',
    status: str = DocumentStatus.CONFIRMED.value,
) -> Document:
    """A dispatch whose lines are ``(name, expected, picked)``."""
    doc = Document(
        organization_id=org.id,
        type=doc_type,
        number=f'OUT/2026/{uuid.uuid4().hex[:4]}',
        status=status,
        created_by=user.id,
    )
    db.add(doc)
    await db.flush()
    for i, (name, expected, done) in enumerate(picked, start=1):
        db.add(
            DocumentLine(
                document_id=doc.id,
                name=name,
                quantity=expected,
                expected_quantity=expected,
                done_quantity=done,
                line_number=i,
            )
        )
    await db.flush()
    await db.refresh(doc, attribute_names=['lines'])
    return doc


async def _session_line(
    db: AsyncSession,
    doc: Document,
    user: User,
    *,
    status: str = 'picked',
    picked: Decimal = Decimal(0),
    line_index: int = 0,
) -> tuple[WmsPickSession, WmsPickLine]:
    """A session open on the dispatch's *line_index*-th line, standing at *status*."""
    session = WmsPickSession(
        organization_id=doc.organization_id,
        document_id=doc.id,
        assigned_to=user.id,
        status='active',
    )
    db.add(session)
    await db.flush()
    pick_line = WmsPickLine(
        session_id=session.id,
        document_line_id=doc.lines[line_index].id,
        pick_order=line_index,
        status=status,
        picked_quantity=picked,
        expected_quantity=doc.lines[line_index].expected_quantity,
    )
    db.add(pick_line)
    await db.flush()
    return session, pick_line


@pytest.mark.integration
class TestAPackageHoldsWhatWasPicked:
    async def test_a_line_is_packed_up_to_its_picked_quantity(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(10), Decimal(6))])
        package = await svc.create_package_async(db, org.id, doc.id, user.id)

        await svc.set_line_async(
            db, org.id, doc.id, package.id, doc.lines[0].id, Decimal(6), user.id
        )

        view = await svc.view_async(db, org.id, doc.id)
        assert view.packages[0].code == f'{doc.number}-P1'
        assert view.packages[0].lines[0].quantity == Decimal(6)
        assert view.lines[0].picked_quantity == Decimal(6)
        assert view.lines[0].packed_quantity == Decimal(6)
        assert view.lines[0].remaining_quantity == Decimal(0)
        assert view.editable is True

    async def test_packing_more_than_was_picked_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """Ten ordered, six picked: the four still on the shelf go in no box."""
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(10), Decimal(6))])
        package = await svc.create_package_async(db, org.id, doc.id, user.id)

        with pytest.raises(ServiceRejectionError) as refused:
            await svc.set_line_async(
                db, org.id, doc.id, package.id, doc.lines[0].id, Decimal(7), user.id
            )

        assert refused.value.key == 'packing_exceeds_picked'
        assert refused.value.kwargs == {'name': 'Bolt M8', 'remaining': '6'}

    async def test_what_another_package_holds_is_not_available_again(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(10), Decimal(6))])
        line_id = doc.lines[0].id
        first = await svc.create_package_async(db, org.id, doc.id, user.id)
        second = await svc.create_package_async(db, org.id, doc.id, user.id)
        await svc.set_line_async(
            db, org.id, doc.id, first.id, line_id, Decimal(4), user.id
        )

        with pytest.raises(ServiceRejectionError) as refused:
            await svc.set_line_async(
                db, org.id, doc.id, second.id, line_id, Decimal(3), user.id
            )
        assert refused.value.kwargs['remaining'] == '2'

        await svc.set_line_async(
            db, org.id, doc.id, second.id, line_id, Decimal(2), user.id
        )
        view = await svc.view_async(db, org.id, doc.id)
        assert [p.number for p in view.packages] == [1, 2]
        assert view.lines[0].packed_quantity == Decimal(6)

    async def test_a_package_may_be_refilled_within_its_own_share(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """Setting 5 where 4 stand needs one more picked unit, not five."""
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(5), Decimal(5))])
        line_id = doc.lines[0].id
        package = await svc.create_package_async(db, org.id, doc.id, user.id)
        await svc.set_line_async(
            db, org.id, doc.id, package.id, line_id, Decimal(4), user.id
        )

        await svc.set_line_async(
            db, org.id, doc.id, package.id, line_id, Decimal(5), user.id
        )

        view = await svc.view_async(db, org.id, doc.id)
        assert view.packages[0].lines[0].quantity == Decimal(5)

    async def test_zero_takes_the_line_out_of_the_package(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(5), Decimal(5))])
        line_id = doc.lines[0].id
        package = await svc.create_package_async(db, org.id, doc.id, user.id)
        await svc.set_line_async(
            db, org.id, doc.id, package.id, line_id, Decimal(5), user.id
        )

        await svc.set_line_async(
            db, org.id, doc.id, package.id, line_id, Decimal(0), user.id
        )

        rows = (await db.scalars(select(DocumentPackageLine))).all()
        assert rows == []
        view = await svc.view_async(db, org.id, doc.id)
        assert view.lines[0].remaining_quantity == Decimal(5)

    async def test_a_line_of_another_document_is_not_found(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(5), Decimal(5))])
        other = await _dispatch(db, org, user, [('Nut M8', Decimal(5), Decimal(5))])
        package = await svc.create_package_async(db, org.id, doc.id, user.id)

        with pytest.raises(EntityNotFoundError) as missing:
            await svc.set_line_async(
                db, org.id, doc.id, package.id, other.lines[0].id, Decimal(1), user.id
            )
        assert missing.value.resource == 'document_line'


async def _product_dispatch(
    db: AsyncSession,
    org: Organization,
    user: User,
    picked: list[tuple[ProductTemplate, Decimal]],
) -> Document:
    """A dispatch whose lines name a catalogue product, ``(product, picked)``."""
    doc = await _dispatch(db, org, user, [])
    for i, (template, done) in enumerate(picked, start=1):
        db.add(
            DocumentLine(
                document_id=doc.id,
                product_template_id=template.id,
                name=template.name,
                quantity=done,
                expected_quantity=done,
                done_quantity=done,
                line_number=i,
            )
        )
    await db.flush()
    await db.refresh(doc, attribute_names=['lines'])
    return doc


async def _product(db: AsyncSession, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id, name=name, barcode=f'BC-{uuid.uuid4().hex[:10]}'
    )
    db.add(template)
    await db.flush()
    return template


@pytest.mark.integration
class TestAScanPacksTheLineItNames:
    """A scan puts one more of the scanned product into the package.

    The line is found the way the picking session finds it — the product the
    line names, through its own template or through its record — so a code
    the picker could scan is a code the packer can scan.
    """

    async def test_each_scan_adds_one_of_the_scanned_product(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        bolt = await _product(db, org, 'Bolt M8')
        nut = await _product(db, org, 'Nut M8')
        doc = await _product_dispatch(
            db, org, user, [(bolt, Decimal(3)), (nut, Decimal(2))]
        )
        package = await svc.create_package_async(db, org.id, doc.id, user.id)

        for _ in range(2):
            await svc.scan_into_package_async(
                db, org.id, doc.id, package.id, str(nut.barcode), Decimal(1), user.id
            )

        view = await svc.view_async(db, org.id, doc.id)
        assert [(ln.product_name, ln.quantity) for ln in view.packages[0].lines] == [
            ('Nut M8', Decimal(2))
        ]

    async def test_a_full_line_hands_the_scan_to_the_next_line_of_the_product(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """Two lines of one product — two lots, say: the first packed fills the second."""
        db = real_async_db_session
        bolt = await _product(db, org, 'Bolt M8')
        doc = await _product_dispatch(
            db, org, user, [(bolt, Decimal(1)), (bolt, Decimal(1))]
        )
        package = await svc.create_package_async(db, org.id, doc.id, user.id)

        for _ in range(2):
            await svc.scan_into_package_async(
                db, org.id, doc.id, package.id, str(bolt.barcode), Decimal(1), user.id
            )

        view = await svc.view_async(db, org.id, doc.id)
        assert [ln.remaining_quantity for ln in view.lines] == [Decimal(0), Decimal(0)]

    async def test_a_scan_past_what_was_picked_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        bolt = await _product(db, org, 'Bolt M8')
        doc = await _product_dispatch(db, org, user, [(bolt, Decimal(1))])
        package = await svc.create_package_async(db, org.id, doc.id, user.id)
        await svc.scan_into_package_async(
            db, org.id, doc.id, package.id, str(bolt.barcode), Decimal(1), user.id
        )

        with pytest.raises(ServiceRejectionError) as refused:
            await svc.scan_into_package_async(
                db, org.id, doc.id, package.id, str(bolt.barcode), Decimal(1), user.id
            )

        assert refused.value.key == 'packing_exceeds_picked'
        assert refused.value.kwargs == {'name': 'Bolt M8', 'remaining': '0'}

    async def test_a_product_the_dispatch_does_not_carry_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        bolt = await _product(db, org, 'Bolt M8')
        stranger = await _product(db, org, 'Washer M8')
        doc = await _product_dispatch(db, org, user, [(bolt, Decimal(1))])
        package = await svc.create_package_async(db, org.id, doc.id, user.id)

        with pytest.raises(ServiceRejectionError) as refused:
            await svc.scan_into_package_async(
                db,
                org.id,
                doc.id,
                package.id,
                str(stranger.barcode),
                Decimal(1),
                user.id,
            )

        assert refused.value.key == 'packing_scan_not_in_document'
        assert refused.value.kwargs == {'name': 'Washer M8'}

    async def test_a_code_nothing_carries_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        bolt = await _product(db, org, 'Bolt M8')
        doc = await _product_dispatch(db, org, user, [(bolt, Decimal(1))])
        package = await svc.create_package_async(db, org.id, doc.id, user.id)

        with pytest.raises(ServiceRejectionError) as refused:
            await svc.scan_into_package_async(
                db, org.id, doc.id, package.id, 'NO-SUCH-CODE', Decimal(1), user.id
            )

        assert refused.value.key == 'packing_scan_unrecognized'
        assert refused.value.kwargs == {'code': 'NO-SUCH-CODE'}


@pytest.mark.integration
class TestPackAll:
    async def test_one_package_takes_everything_picked_and_not_packed(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(
            db,
            org,
            user,
            [
                ('Bolt M8', Decimal(10), Decimal(10)),
                ('Nut M8', Decimal(4), Decimal(3)),
                ('Washer', Decimal(2), Decimal(0)),
            ],
        )
        first = await svc.create_package_async(db, org.id, doc.id, user.id)
        await svc.set_line_async(
            db, org.id, doc.id, first.id, doc.lines[0].id, Decimal(4), user.id
        )

        await svc.pack_all_async(db, org.id, doc.id, user.id)

        view = await svc.view_async(db, org.id, doc.id)
        last = view.packages[-1]
        assert last.number == 2
        assert [(ln.product_name, ln.quantity) for ln in last.lines] == [
            ('Bolt M8', Decimal(6)),
            ('Nut M8', Decimal(3)),
        ]
        assert all(line.remaining_quantity == 0 for line in view.lines)

    async def test_nothing_left_to_pack_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(10), Decimal(10))])
        await svc.pack_all_async(db, org.id, doc.id, user.id)

        with pytest.raises(ServiceRejectionError) as refused:
            await svc.pack_all_async(db, org.id, doc.id, user.id)
        assert refused.value.key == 'packing_nothing_to_pack'


@pytest.mark.integration
class TestPackagesComeAndGo:
    async def test_the_weight_is_recorded_and_cleared(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(1), Decimal(1))])
        package = await svc.create_package_async(
            db, org.id, doc.id, user.id, weight_kg=Decimal('1.250')
        )

        await svc.update_package_async(
            db, org.id, doc.id, package.id, user.id, {'weight_kg': Decimal('2.5')}
        )
        assert (await svc.view_async(db, org.id, doc.id)).packages[
            0
        ].weight_kg == Decimal('2.5')

        # An absent key leaves the weight alone.
        await svc.update_package_async(db, org.id, doc.id, package.id, user.id, {})
        assert (await svc.view_async(db, org.id, doc.id)).packages[
            0
        ].weight_kg == Decimal('2.5')

        # A named null clears it.
        await svc.update_package_async(
            db, org.id, doc.id, package.id, user.id, {'weight_kg': None}
        )
        assert (await svc.view_async(db, org.id, doc.id)).packages[0].weight_kg is None

    async def test_deleting_a_package_unpacks_what_it_held(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(3), Decimal(3))])
        package = await svc.pack_all_async(db, org.id, doc.id, user.id)

        await svc.delete_package_async(db, org.id, doc.id, package.id, user.id)

        view = await svc.view_async(db, org.id, doc.id)
        assert view.packages == []
        assert view.lines[0].remaining_quantity == Decimal(3)
        # Picked stays picked: unpacking is not putting goods back.
        assert view.lines[0].picked_quantity == Decimal(3)

    async def test_deleting_a_middle_package_closes_the_gap_in_the_numbers(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """Numbers stay 1..N, so "package N of M" is never more than M."""
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(3), Decimal(3))])
        first, middle, last = [
            await svc.create_package_async(db, org.id, doc.id, user.id)
            for _ in range(3)
        ]
        await svc.set_line_async(
            db, org.id, doc.id, last.id, doc.lines[0].id, Decimal(2), user.id
        )

        await svc.delete_package_async(db, org.id, doc.id, middle.id, user.id)

        view = await svc.view_async(db, org.id, doc.id)
        assert [(p.id, p.number) for p in view.packages] == [
            (first.id, 1),
            (last.id, 2),
        ]
        assert view.packages[1].code == f'{doc.number}-P2'
        assert view.packages[1].lines[0].quantity == Decimal(2)
        # The next package takes the number after the last one standing.
        added = await svc.create_package_async(db, org.id, doc.id, user.id)
        assert added.number == 3

    async def test_a_missing_package_is_not_found(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(3), Decimal(3))])

        with pytest.raises(EntityNotFoundError) as missing:
            await svc.delete_package_async(db, org.id, doc.id, uuid.uuid4(), user.id)
        assert missing.value.resource == 'package'


@pytest.mark.integration
class TestOnlyAnOpenDispatchIsPacked:
    async def test_a_completed_dispatchs_packages_refuse_changes(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(3), Decimal(3))])
        package = await svc.pack_all_async(db, org.id, doc.id, user.id)
        doc.status = DocumentStatus.COMPLETED.value
        await db.flush()

        attempts = [
            svc.create_package_async(db, org.id, doc.id, user.id),
            svc.pack_all_async(db, org.id, doc.id, user.id),
            svc.update_package_async(
                db, org.id, doc.id, package.id, user.id, {'weight_kg': Decimal(1)}
            ),
            svc.set_line_async(
                db, org.id, doc.id, package.id, doc.lines[0].id, Decimal(1), user.id
            ),
            svc.delete_package_async(db, org.id, doc.id, package.id, user.id),
        ]
        for attempt in attempts:
            with pytest.raises(ServiceRejectionError) as refused:
                await attempt
            assert refused.value.key == 'packing_document_not_open'

        view = await svc.view_async(db, org.id, doc.id)
        assert view.editable is False
        assert view.packages[0].lines[0].quantity == Decimal(3)

    async def test_a_receipt_is_not_packed(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(
            db, org, user, [('Bolt M8', Decimal(3), Decimal(3))], doc_type='IN'
        )

        with pytest.raises(ServiceRejectionError) as refused:
            await svc.create_package_async(db, org.id, doc.id, user.id)
        assert refused.value.key == 'packing_not_a_dispatch'


@pytest.mark.integration
class TestAnotherOrganizationSeesNothing:
    async def test_another_organization_cannot_read_or_pack_the_dispatch(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(3), Decimal(3))])
        package = await svc.pack_all_async(db, org.id, doc.id, user.id)
        stranger = Organization(name='Elsewhere', enabled_modules=['core'])
        db.add(stranger)
        await db.flush()

        for attempt in (
            svc.view_async(db, stranger.id, doc.id),
            svc.create_package_async(db, stranger.id, doc.id, user.id),
            svc.delete_package_async(db, stranger.id, doc.id, package.id, user.id),
        ):
            with pytest.raises(EntityNotFoundError) as missing:
                await attempt
            assert missing.value.resource == 'document'

        assert await svc.list_packages_async(db, stranger.id, doc.id) == []
        assert (await db.scalars(select(DocumentPackage))).all() == [package]


@pytest.mark.integration
class TestEveryPackageWriteReachesTheJournal:
    async def test_create_fill_weigh_pack_all_and_delete_are_logged(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(5), Decimal(5))])
        line_id = doc.lines[0].id
        package = await svc.create_package_async(db, org.id, doc.id, user.id)
        await svc.set_line_async(
            db, org.id, doc.id, package.id, line_id, Decimal(2), user.id
        )
        await svc.update_package_async(
            db, org.id, doc.id, package.id, user.id, {'weight_kg': Decimal('0.8')}
        )
        await svc.pack_all_async(db, org.id, doc.id, user.id)
        await svc.delete_package_async(db, org.id, doc.id, package.id, user.id)

        entries = await core_api.audit_log.list_for_target_async(
            db, org.id, AuditTargetType.DOCUMENT, doc.id
        )
        snapshots = [e.snapshot or {} for e in entries]
        journal = [
            (e.action, snapshot.get('code'), e.user_id)
            for e, snapshot in reversed(list(zip(entries, snapshots, strict=True)))
        ]
        code1, code2 = f'{doc.number}-P1', f'{doc.number}-P2'
        assert journal == [
            ('CREATE', code1, user.id),
            ('UPDATE', code1, user.id),
            ('UPDATE', code1, user.id),
            ('CREATE', code2, user.id),
            ('HARD_DELETE', code1, user.id),
        ]
        filled = snapshots[-2]
        assert filled['name'] == 'Bolt M8'
        assert (filled['quantity'], filled['old_quantity']) == ('2', '0')
        assert snapshots[-3]['weight_value'] == '0.8'


@pytest.mark.integration
class TestPackagesNeverHoldMoreThanWasDone:
    async def test_completing_below_what_the_packages_hold_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """Six picked and boxed; completing with four would ship a box of six."""
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(10), Decimal(6))])
        await svc.pack_all_async(db, org.id, doc.id, user.id)
        body = DocumentComplete(
            lines=[
                DocumentLineExecution(
                    line_id=doc.lines[0].id,
                    done_quantity=Decimal(4),
                    discrepancy_code='SHORTAGE',
                )
            ]
        )

        with pytest.raises(ServiceRejectionError) as refused:
            await complete_document(db, org.id, doc.id, user.id, body)

        assert refused.value.key == 'packing_exceeds_done'
        assert refused.value.kwargs == {
            'name': 'Bolt M8',
            'packed': '6',
            'done': '4',
        }

    async def test_undoing_a_pick_that_a_package_holds_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(10), Decimal(6))])
        session, pick_line = await _session_line(
            db, doc, user, status='picked', picked=Decimal(6)
        )
        await svc.pack_all_async(db, org.id, doc.id, user.id)

        with pytest.raises(ServiceRejectionError) as refused:
            await undo_pick_async(db, session.id, org.id, pick_line.id)

        assert refused.value.key == 'wms_undo_line_is_packed'
        assert refused.value.kwargs == {'name': 'Bolt M8', 'packed': '6'}
        await db.refresh(doc.lines[0])
        assert doc.lines[0].done_quantity == Decimal(6)

    async def test_skipping_a_line_a_package_holds_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """Six picked part-way and boxed: a skip would empty a line a box holds."""
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(10), Decimal(6))])
        session, pick_line = await _session_line(
            db, doc, user, status='pending', picked=Decimal(6)
        )
        await svc.pack_all_async(db, org.id, doc.id, user.id)

        with pytest.raises(ServiceRejectionError) as refused:
            await skip_pick_line_async(db, session.id, org.id, pick_line.id)

        assert refused.value.key == 'wms_skip_line_is_packed'
        assert refused.value.kwargs == {'name': 'Bolt M8', 'packed': '6'}
        await db.refresh(pick_line)
        assert pick_line.status == 'pending'
        assert pick_line.picked_quantity == Decimal(6)
        await db.refresh(doc.lines[0])
        assert doc.lines[0].done_quantity == Decimal(6)

    async def test_short_confirming_below_what_a_package_holds_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """Six picked and boxed; counting four would ship a box of six."""
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(10), Decimal(6))])
        session, pick_line = await _session_line(
            db, doc, user, status='picked', picked=Decimal(6)
        )
        await svc.pack_all_async(db, org.id, doc.id, user.id)

        with pytest.raises(ServiceRejectionError) as refused:
            await confirm_short_pick_async(
                db,
                session.id,
                org.id,
                pick_line.id,
                Decimal(4),
                'SHORTAGE',
                replace_scans=True,
            )

        assert refused.value.key == 'packing_exceeds_done'
        assert refused.value.kwargs == {
            'name': 'Bolt M8',
            'packed': '6',
            'done': '4',
        }
        await db.refresh(pick_line)
        assert pick_line.picked_quantity == Decimal(6)
        await db.refresh(doc.lines[0])
        assert doc.lines[0].done_quantity == Decimal(6)

    async def test_short_confirming_what_a_package_holds_is_allowed(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """Six counted again as six is no shortage of the box: the door stays open."""
        db = real_async_db_session
        doc = await _dispatch(db, org, user, [('Bolt M8', Decimal(10), Decimal(6))])
        session, pick_line = await _session_line(
            db, doc, user, status='picked', picked=Decimal(6)
        )
        await svc.pack_all_async(db, org.id, doc.id, user.id)

        confirmed = await confirm_short_pick_async(
            db, session.id, org.id, pick_line.id, Decimal(6), 'SHORTAGE'
        )

        assert confirmed.status == 'short'
        await db.refresh(doc.lines[0])
        assert doc.lines[0].done_quantity == Decimal(6)

    async def test_cancelling_a_session_whose_picked_line_a_package_holds_is_refused(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """One line of two picked and boxed: a cancel used to zero it under the box."""
        db = real_async_db_session
        doc = await _dispatch(
            db,
            org,
            user,
            [('Bolt M8', Decimal(10), Decimal(6)), ('Nut M8', Decimal(5), Decimal(0))],
        )
        session, pick_line = await _session_line(
            db, doc, user, status='picked', picked=Decimal(6)
        )
        await svc.pack_all_async(db, org.id, doc.id, user.id)

        with pytest.raises(ServiceRejectionError) as refused:
            await cancel_pick_session_async(db, session.id, org.id, user.id)

        assert refused.value.key == 'wms_cancel_session_is_packed'
        assert refused.value.kwargs == {'name': 'Bolt M8', 'packed': '6'}
        await db.refresh(session)
        assert session.status == 'active'
        await db.refresh(pick_line)
        assert pick_line.status == 'picked'
        await db.refresh(doc.lines[0])
        assert doc.lines[0].done_quantity == Decimal(6)

    async def test_cancelling_leaves_what_the_session_never_wrote_standing(
        self, real_async_db_session: AsyncSession, org: Organization, user: User
    ) -> None:
        """The refusal names the session's own lines: an earlier pick a box
        holds is that line's record, and cancelling this session keeps it."""
        db = real_async_db_session
        doc = await _dispatch(
            db,
            org,
            user,
            [('Bolt M8', Decimal(10), Decimal(6)), ('Nut M8', Decimal(5), Decimal(3))],
        )
        package = await svc.create_package_async(db, org.id, doc.id, user.id)
        await svc.set_line_async(
            db, org.id, doc.id, package.id, doc.lines[0].id, Decimal(6), user.id
        )
        session, pick_line = await _session_line(
            db, doc, user, status='pending', picked=Decimal(3), line_index=1
        )

        await cancel_pick_session_async(db, session.id, org.id, user.id)

        await db.refresh(session)
        assert session.status == 'cancelled'
        await db.refresh(doc.lines[0])
        assert doc.lines[0].done_quantity == Decimal(6)
        await db.refresh(doc.lines[1])
        assert doc.lines[1].done_quantity == Decimal(0)
        await db.refresh(pick_line)
        assert pick_line.status == 'pending'
