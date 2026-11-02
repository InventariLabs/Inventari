"""What the public demo shows that the shared seed does not.

``seed_demo_data`` is written for every stack — developers, the QA fixture and
the test suite run it, and ``--clean`` finds its rows again by the ``SEED-``
marker they carry. The public demo is never cleaned: ``demo reset`` drops the
schema and rebuilds it. There the marker was the first thing a visitor read,
on every shelf's code, on the stock take and in the notes of every purchase
order, and seven screens opened on their empty state because nothing in the
shared seed fills them.

This is the step only ``demo reset`` runs, after the shared seed: it takes the
marker off the rows a visitor reads, names the organization, adds the two
colleagues an approval needs, gives each of the seven screens the smallest
amount of work that makes it legible, and puts a photograph on every recipe.
Every step leaves rows it already wrote alone, so a reset that runs it twice
ends in the same demo.
"""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.database import SessionLocal
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User
from app.services.storage._codes import (
    default_template_for,
    parse_template,
    plan_branch_codes,
    stored_template,
)
from app.services.token_service import get_password_hash
from seed_demo_data import (
    DEMO_ASSIGNEES,
    SEED_PREFIX,
    TODAY,
    _food_leaves_by_zone,
    _get_food_leaf_locations,
    _org_currency,
    _resolve_category_ids,
)

#: The demo's own name. "My Organization" is what ``create-admin`` calls the
#: organization it opens, and it is printed on every PDF the demo produces.
DEMO_ORGANIZATION_NAME = 'Larkspur Trading Co.'

#: The colleagues an approval needs: one asks, one signs off the first stage,
#: and the administrator — the visitor — is asked for the second. They are
#: two of the people the shared seed already issued laptops to, and nobody
#: can sign in as them: their passwords are drawn and thrown away.
DEMO_TEAM = DEMO_ASSIGNEES[:2]

#: Replaces the shared seed's marker in each purchase order's notes, in the
#: order the orders are numbered.
DEMO_PO_NOTES = [
    'Laptops for the two November starters and two for the loan pool.',
    'Quarterly refresh of the support desk.',
    'Partly delivered; the rest is on back order with the supplier.',
]

#: The purchase-order approval: above the threshold, an order goes to a team
#: lead and then to finance. Documents are deliberately left without a
#: workflow — one would hold every receipt a visitor confirms for approval.
DEMO_APPROVAL_THRESHOLD = Decimal('10000')
DEMO_APPROVAL_WORKFLOW = 'Purchase orders over 10,000'
DEMO_APPROVAL_STAGES = [
    {'order': 1, 'role': 'manager', 'label': 'Team lead', 'approver_user_ids': []},
    {'order': 2, 'role': 'admin', 'label': 'Finance', 'approver_user_ids': []},
]
DEMO_APPROVAL_NOTES = 'Budgeted for this quarter; the old units go to the loan pool.'

#: The asset the administrator signs for, so "My assets" has a row.
DEMO_ADMIN_ASSET = 'iPhone 15 Pro'
DEMO_ADMIN_ASSET_NOTES = 'Work phone, with case and charger.'

#: The running attestation: who has answered, and what one of them found.
DEMO_CAMPAIGN_NAME = 'Autumn equipment check'
DEMO_CAMPAIGN_DESCRIPTION = 'Confirm you still hold the equipment issued to you.'
DEMO_DISPUTE_REASON = 'The hinge on the lid is cracked and the screen flickers.'

#: Labels printed in one batch: some already stuck on assets, the rest on the
#: roll waiting for one. ``STM`` is the prefix the label screen offers.
DEMO_LABEL_PREFIX = 'STM'
DEMO_LABELS_ON_ASSETS = 6
DEMO_LABELS_ON_THE_ROLL = 6

#: (rule match, zone the goods go to, priority). A category is matched by its
#: code, a product by its name.
DEMO_PUTAWAY_RULES = [
    ({'category': 'dairy'}, 'Cold Storage', 50),
    ({'category': 'frozen_meals'}, 'Freezer Zone', 50),
    ({'product': 'Damson Plums'}, 'Cold Storage', 10),
]

#: (supplier code, product name, price per unit). The workshop's ingredients
#: come from the wholesalers, the laptops from the IT distributors — two of
#: them for the same model, so the price list has something to compare.
DEMO_SUPPLIER_PRICES = [
    ('FFD-004', 'Damson Plums', Decimal('3.20')),
    ('MCC-005', 'White Sugar', Decimal('1.05')),
    ('MCC-005', 'Cassia Cinnamon', Decimal('22.50')),
    ('SUP-001', 'Dell Latitude 5540', Decimal('4100.00')),
    ('ITD-002', 'Dell Latitude 5540', Decimal('4180.00')),
    ('ITD-002', 'ThinkPad T14s Gen 4', Decimal('5650.00')),
]

#: (ingredient, minimum, maximum, safety stock). The production run leaves
#: 13.6 kg of plums against a minimum of 20, so the replenishment screen has
#: a suggestion to make; sugar and cinnamon are well above theirs. Each is
#: bought from the supplier whose price list names it.
DEMO_REORDER_POINTS = [
    ('Damson Plums', Decimal('20'), Decimal('40'), Decimal('10')),
    ('White Sugar', Decimal('5'), Decimal('25'), Decimal('2')),
    ('Cassia Cinnamon', Decimal('0.1'), Decimal('0.5'), Decimal('0.1')),
]


#: The recipe photographs and ``sources.json``, which names each one's page,
#: author and licence. Only licences that ask nothing of a copier are shipped
#: (``tests/unit/test_the_demo_recipe_photos_are_free_to_ship.py``).
DEMO_RECIPE_PHOTOS = Path(__file__).resolve().parent / 'seed_assets' / 'demo_recipes'


def _now() -> datetime:
    return datetime.now(UTC)


def _code_body() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(4))


def _location_codes(db, org_id) -> set[str]:
    return {
        code
        for (code,) in db.query(StorageLocation.short_code).filter(
            StorageLocation.organization_id == org_id
        )
    }


def _number_the_warehouses(db, org_id) -> dict[str, str]:
    """Give each warehouse's inside the codes its template numbers it with.

    Every sandbox is built from the same seed rows in the same order, so
    both trees walk the same way and take the same codes — which is what
    makes a shelf's sticker worth printing: the demo's label sheet carries
    codes that resolve in whichever sandbox a visitor was handed, and two
    sandboxes print the same sheet. The codes are the business format a
    warehouse already names itself with (``A-01``, ``A-01-01``, through
    ``default_template_for`` on this organization's profile).

    A warehouse's own code is left alone — outside the tree a warehouse
    keeps whatever prefix gave it, like a real business's own racks do
    below. An organization whose profile does not number with a tree keeps
    ``LOC-`` codes everywhere, which the marker drop below still hands out.

    Returns the codes the numbering replaced, old -> new, so a picking line
    that quotes a shelf's code follows it there.
    """
    from app.core.exceptions import ValidationException
    from app.models.label_pool import LabelPool
    from app.services.storage._queries import not_archived_condition

    org = db.get(Organization, org_id)
    default = default_template_for(org.active_profile_id if org else None)
    rows = (
        db.query(StorageLocation)
        .filter(
            StorageLocation.organization_id == org_id,
            StorageLocation.usage == LocationUsage.INTERNAL.value,
            not_archived_condition(),
        )
        .order_by(StorageLocation.name.asc())
        .all()
    )
    in_use = _location_codes(db, org_id) | {
        code
        for (code,) in db.query(LabelPool.short_code).filter(
            LabelPool.organization_id == org_id
        )
        if code
    }
    by_id = {row.id: row for row in rows}
    renamed: dict[str, str] = {}
    for root in (row for row in rows if row.parent_id is None):
        raw = stored_template(root) or default
        try:
            template = parse_template(raw)
        except ValidationException:
            # A template written into settings that no longer parses: the
            # profile's answer rather than no code at all — the same fall
            # ``template_of_async`` makes for one numbered by hand.
            template = parse_template(default)
        if not template.is_tree:
            # A prefix template (a household's ``LOC``): nothing to number
            # with here, and the marker drop below gives the LOC- codes.
            continue
        given = plan_branch_codes(rows, template, root.id, in_use, renumber=False)
        for location_id, code in given.items():
            location = by_id[location_id]
            if not code or code == location.short_code:
                continue
            in_use.add(code)
            renamed[location.short_code] = code
            location.short_code = code
    return renamed


def _drop_the_seed_marker(db, org_id) -> int:
    """Take ``SEED-`` off every row a visitor reads.

    A shelf inside a warehouse takes the code its template numbers it with
    (``A-01-01``, the same one in every sandbox — see
    ``_number_the_warehouses``); what the numbering does not reach — a
    warehouse's own code, a place outside the tree — keeps its four
    characters under the prefix the application gives locations
    (``LOC-``), and a body another code already holds draws a fresh one. A
    picking line keeps its shelf's code as text — the row the
    picker reads — so it follows its shelf to whatever code the shelf took.
    """
    from app.modules.purchase_orders.models import PurchaseOrder
    from app.modules.stock_takes.models import StockTake
    from app.modules.warehouse.models import WmsPickLine, WmsPickSession

    marked = f'{SEED_PREFIX}%'
    changed = 0
    taken = _location_codes(db, org_id)
    renamed: dict[str, str] = {}
    for was, now in _number_the_warehouses(db, org_id).items():
        renamed[was] = now
        taken.add(now)
        changed += 1
    # The numbering wrote codes the query below must not find under the
    # marker: without the flush it matches rows as the database still has
    # them — the seed's ``SEED-`` — and would rename a numbered shelf a
    # second time, under the prefix, on top of its template code.
    db.flush()
    for location in db.query(StorageLocation).filter(
        StorageLocation.organization_id == org_id,
        StorageLocation.short_code.like(marked),
    ):
        code = 'LOC-' + location.short_code.removeprefix(SEED_PREFIX)
        while code in taken:
            code = 'LOC-' + _code_body()
        taken.add(code)
        renamed[location.short_code] = code
        location.short_code = code
        changed += 1

    for line in (
        db.query(WmsPickLine)
        .join(WmsPickSession, WmsPickSession.id == WmsPickLine.session_id)
        .filter(
            WmsPickSession.organization_id == org_id,
            WmsPickLine.bin_location.is_not(None),
        )
        .all()
    ):
        text = line.bin_location
        if text is None:
            continue
        walked = text
        for was, now in renamed.items():
            walked = walked.replace(was, now)
        if walked != text:
            line.bin_location = walked
            changed += 1

    for take in db.query(StockTake).filter(
        StockTake.organization_id == org_id, StockTake.name.like(marked)
    ):
        take.name = take.name.removeprefix(SEED_PREFIX)
        changed += 1

    orders = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.notes.like(marked),
        )
        .order_by(PurchaseOrder.number)
        .all()
    )
    for order, notes in zip(orders, DEMO_PO_NOTES, strict=False):
        order.notes = notes
        changed += 1
    db.flush()
    return changed


def _hire_the_team(db, org_id) -> list[User]:
    """The two colleagues, as members nobody can sign in as.

    An address is unique across the instance, and on the public demo every
    visitor's organization hires the same two people. The first organization
    keeps their plain addresses; a later one hires them under its own tag
    (``ava.brennan+<org>@example.com``). Reusing the account another
    organization already had made its colleagues decide this one's orders.
    """
    team = []
    for name, plain in DEMO_TEAM:
        email = plain
        user = db.query(User).filter(User.email == email).first()
        if user is not None and user.organization_id != org_id:
            local, domain = plain.split('@')
            email = f'{local}+{str(org_id)[:8]}@{domain}'
            user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(
                id=uuid.uuid4(),
                organization_id=org_id,
                email=email,
                full_name=name,
                hashed_password=get_password_hash(secrets.token_urlsafe(24)),
                role='user',
                is_active=True,
            )
            db.add(user)
        team.append(user)
    db.flush()
    return team


def _hand_the_history_to_the_team(db, org_id, team) -> int:
    """Let the colleagues have written, confirmed and closed the seeded documents.

    The shared seed signs everything it writes with the account it seeds for,
    and in a visitor's sandbox that account is the visitor: History opened on
    a fortnight of work "by Demo Visitor", done before they arrived. The two
    colleagues take the documents in turn, with the stock movements and the
    record history those documents wrote. Returns how many documents moved.
    """
    from app.models.item_history import ItemHistory
    from app.models.stock_move import StockMove, StockMoveReferenceType
    from app.modules.warehouse.models import Document
    from seed_demo_data import _seeded_document_ids

    ids = _seeded_document_ids(db, org_id)
    documents = (
        db.query(Document)
        .filter(Document.id.in_(ids))
        .order_by(Document.created_at, Document.number)
        .all()
    )
    for index, doc in enumerate(documents):
        colleague = team[index % len(team)].id
        doc.created_by = colleague
        if doc.confirmed_by is not None:
            doc.confirmed_by = colleague
        if doc.completed_by is not None:
            doc.completed_by = colleague
        db.query(StockMove).filter(
            StockMove.organization_id == org_id,
            StockMove.reference_type == StockMoveReferenceType.DOCUMENT,
            StockMove.reference_id == doc.id,
        ).update({StockMove.created_by: colleague}, synchronize_session=False)
        db.query(ItemHistory).filter(
            ItemHistory.organization_id == org_id,
            ItemHistory.source_document_id == doc.id,
        ).update({ItemHistory.user_id: colleague}, synchronize_session=False)
    db.flush()
    return len(documents)


def _queue_an_approval(db, org_id, admin, team) -> int:
    """An order over the threshold, half-way through its approval.

    Ava asked for it, Marcus signed the team-lead stage, and the finance stage
    waits for the administrator — a request the visitor can decide. The order
    after it went through both stages, so the dashboard has a history as well
    as a queue.
    """
    from app.modules.approvals.models import ApprovalWorkflow
    from app.modules.purchase_orders.models import POSettings, PurchaseOrder

    if (
        db.query(ApprovalWorkflow)
        .filter(ApprovalWorkflow.organization_id == org_id)
        .count()
    ):
        return 0
    orders = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.organization_id == org_id)
        .order_by(PurchaseOrder.number)
        .all()
    )
    waiting = next((po for po in orders if po.status == 'DRAFT'), None)
    approved = next((po for po in orders if po.status == 'CONFIRMED'), None)
    if waiting is None or approved is None:
        return 0

    workflow = ApprovalWorkflow(
        id=uuid.uuid4(),
        organization_id=org_id,
        target_type='purchase_order',
        name=DEMO_APPROVAL_WORKFLOW,
        stages=DEMO_APPROVAL_STAGES,
        is_active=True,
    )
    db.add(workflow)
    settings = db.query(POSettings).filter(POSettings.organization_id == org_id).first()
    if settings is None:
        settings = POSettings(organization_id=org_id)
        db.add(settings)
    settings.approval_threshold = DEMO_APPROVAL_THRESHOLD

    requester, team_lead = team
    waiting.status = 'PENDING_APPROVAL'
    waiting.created_by = requester.id
    _request(
        db, workflow, waiting, requester, [(team_lead, 'APPROVED'), (None, 'PENDING')]
    )
    approved.created_by = requester.id
    decided = _request(
        db,
        workflow,
        approved,
        requester,
        [(team_lead, 'APPROVED'), (admin, 'APPROVED')],
    )
    approved.confirmed_at = decided + timedelta(hours=1)
    db.flush()
    return 2


def _let_the_visitor_decide_their_own_orders(org) -> None:
    """An order the visitor confirms into approval is theirs to approve.

    The colleagues are names on a page: the visitor is the only person who can
    sign in, and the door refuses a self-decision, so every order they sent to
    approval waited for good. This is the switch a small organization whose
    administrator is the only approver turns on, and refusing such an order
    instead would keep the approval itself out of a visitor's reach.
    """
    from app.modules.approvals._settings import SELF_APPROVE_SETTING

    settings = dict(org.settings or {})
    settings['module:approvals'] = {
        **settings.get('module:approvals', {}),
        SELF_APPROVE_SETTING: True,
    }
    org.settings = settings


def _request(db, workflow, order, requester, decisions) -> datetime:
    """One request on *order*, its stages decided as *decisions* say.

    Returns when the last decided stage was decided.
    """
    from app.modules.approvals.models import ApprovalDecision, ApprovalRequest

    asked = order.created_at + timedelta(hours=1)
    pending = any(status == 'PENDING' for _who, status in decisions)
    request = ApprovalRequest(
        id=uuid.uuid4(),
        organization_id=order.organization_id,
        workflow_id=workflow.id,
        target_type='purchase_order',
        target_id=order.id,
        status='IN_PROGRESS' if pending else 'APPROVED',
        current_stage=len(decisions),
        total_stages=len(decisions),
        created_by=requester.id,
        created_at=asked,
        meta_data={'notes': DEMO_APPROVAL_NOTES},
    )
    db.add(request)
    decided = asked
    for stage, (approver, status) in enumerate(decisions, start=1):
        when = None
        if status != 'PENDING':
            decided = asked + timedelta(hours=3 * stage)
            when = decided
        db.add(
            ApprovalDecision(
                id=uuid.uuid4(),
                approval_request_id=request.id,
                stage_order=stage,
                approver_id=approver.id if approver else None,
                status=status,
                decided_at=when,
                created_at=when or asked,
            )
        )
    return decided


def _issue_the_administrator_a_kit(db, org_id, admin) -> int:
    """Check one asset out to the administrator, so "My assets" has a row."""
    from app.modules.equipment.models import EquipmentAssignment

    if (
        db.query(EquipmentAssignment)
        .filter(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.assigned_to_email == admin.email,
        )
        .count()
    ):
        return 0
    issued = db.query(EquipmentAssignment.item_id).filter(
        EquipmentAssignment.organization_id == org_id,
        EquipmentAssignment.checked_in_at.is_(None),
    )
    checked_out_at = _now() - timedelta(days=40)
    phone = (
        db.query(Item)
        .filter(
            Item.organization_id == org_id,
            Item.is_deleted.is_(False),
            Item.name == DEMO_ADMIN_ASSET,
            Item.id.not_in(issued),
            # Not a phone a delivery opened after the day it is issued.
            Item.created_at <= checked_out_at,
        )
        .order_by(Item.created_at, Item.id)
        .first()
    )
    if phone is None:
        return 0
    db.add(
        EquipmentAssignment(
            id=uuid.uuid4(),
            organization_id=org_id,
            item_id=phone.id,
            assigned_to_name=admin.full_name or admin.email,
            assigned_to_email=admin.email,
            checkout_location_id=phone.storage_location_id,
            checked_out_at=checked_out_at,
            checked_out_by=admin.id,
            checkout_notes=DEMO_ADMIN_ASSET_NOTES,
        )
    )
    # The check-out service sets this too; an asset in somebody's hands that
    # still reads AVAILABLE is a contradiction the demo cannot explain.
    meta = dict(phone.meta_data or {})
    meta['equipment'] = {
        **(meta.get('equipment') or {}),
        'equipment_status': 'DEPLOYED',
    }
    phone.meta_data = meta
    db.flush()
    return 1


def _run_an_attestation(db, org_id, admin) -> int:
    """A campaign launched four days ago: one confirmed, one disputed, the rest due.

    Built the way launching one builds it — one response per person, an item
    row per asset they hold — without the invitation email: the addresses are
    in the documentation domain, and no visitor reads that mail anyway.
    """
    from app.modules.equipment.models import AuditCampaign, EquipmentAssignment

    if db.query(AuditCampaign).filter(AuditCampaign.organization_id == org_id).count():
        return 0
    assignments = (
        db.query(EquipmentAssignment)
        .filter(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.is_(None),
            EquipmentAssignment.assigned_to_email.is_not(None),
        )
        .order_by(EquipmentAssignment.checked_out_at)
        .all()
    )
    if not assignments:
        return 0
    launched = _now() - timedelta(days=4)
    campaign = AuditCampaign(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=DEMO_CAMPAIGN_NAME,
        description=DEMO_CAMPAIGN_DESCRIPTION,
        scope_type='ALL',
        launched_at=launched,
        # Far enough out that the reminder scheduler has nothing to send
        # before the next reset.
        deadline=datetime.combine(TODAY + timedelta(days=17), time(23, 59), UTC),
        status='ACTIVE',
        created_by=admin.id,
        created_at=launched - timedelta(hours=1),
    )
    db.add(campaign)

    people: dict[str, list[Any]] = {}
    for assignment in assignments:
        people.setdefault(assignment.assigned_to_email.lower(), []).append(assignment)
    answers = ['CONFIRMED', 'DISPUTED']
    for index, held in enumerate(people.values()):
        status = answers[index] if index < len(answers) else 'PENDING'
        responded = launched + timedelta(days=1, hours=index) if index < 2 else None
        _answer(db, campaign, held, status, responded)
    db.flush()
    return 1


def _answer(db, campaign, held, status, responded) -> None:
    """One person's response to *campaign*, covering every asset they hold."""
    from app.modules.equipment.models import AuditResponse, AuditResponseItem

    disputed = status == 'DISPUTED'
    response = AuditResponse(
        id=uuid.uuid4(),
        campaign_id=campaign.id,
        organization_id=campaign.organization_id,
        assignee_email=held[0].assigned_to_email.lower(),
        assignee_name=held[0].assigned_to_name,
        token=secrets.token_urlsafe(64),
        token_expires_at=campaign.deadline,
        status=status,
        responded_at=responded,
        email_sent_at=campaign.launched_at,
        dispute_type='DAMAGED' if disputed else None,
        dispute_reason=DEMO_DISPUTE_REASON if disputed else None,
    )
    db.add(response)
    for assignment in held:
        db.add(
            AuditResponseItem(
                id=uuid.uuid4(),
                response_id=response.id,
                assignment_id=assignment.id,
                item_id=assignment.item_id,
                item_name=assignment.item.name,
                serial_number=assignment.item.serial_number,
                status=status,
                dispute_type=response.dispute_type,
                dispute_reason=response.dispute_reason,
            )
        )


def _print_labels(db, org_id, admin) -> int:
    """A printed batch of labels: some on assets, the rest still on the roll."""
    from app.models.label_pool import LabelPool

    if db.query(LabelPool).filter(LabelPool.organization_id == org_id).count():
        return 0
    candidates = (
        db.query(Item)
        .filter(
            Item.organization_id == org_id,
            Item.is_deleted.is_(False),
            Item.serial_number.is_not(None),
            Item.label_code.is_(None),
        )
        .order_by(Item.name, Item.id)
        .all()
    )
    # One asset of each product first: the first six by name were six of
    # the same UPS, and the Labels list read as one row copied six times.
    firsts: dict[uuid.UUID | None, Item] = {}
    for item in candidates:
        firsts.setdefault(item.template_id, item)
    rest = [item for item in candidates if firsts.get(item.template_id) is not item]
    assets = [*firsts.values(), *rest][:DEMO_LABELS_ON_ASSETS]
    taken = _location_codes(db, org_id)
    printed = _now() - timedelta(days=12)
    batch = DEMO_LABELS_ON_ASSETS + DEMO_LABELS_ON_THE_ROLL
    for index in range(batch):
        code = f'{DEMO_LABEL_PREFIX}-{_code_body()}'
        while code in taken:
            code = f'{DEMO_LABEL_PREFIX}-{_code_body()}'
        taken.add(code)
        asset = assets[index] if index < len(assets) else None
        db.add(
            LabelPool(
                id=uuid.uuid4(),
                organization_id=org_id,
                short_code=code,
                created_by=admin.id,
                label_type='GENERIC',
                is_assigned=asset is not None,
                item_id=asset.id if asset else None,
                assigned_at=printed + timedelta(days=1) if asset else None,
                printed_at=printed,
                created_at=printed,
            )
        )
        if asset is not None:
            asset.label_code = code
    db.flush()
    return batch


def _shelves_by_zone(db, org_id) -> dict[str, list]:
    hierarchy = {
        loc.id: loc
        for loc in db.query(StorageLocation).filter(
            StorageLocation.organization_id == org_id
        )
    }
    leaves = sorted(_get_food_leaf_locations(hierarchy), key=lambda loc: loc.name)
    return _food_leaves_by_zone(hierarchy, leaves)


def _templates_by_name(db, org_id, names) -> dict[str, ProductTemplate]:
    return {
        template.name: template
        for template in db.query(ProductTemplate).filter(
            ProductTemplate.organization_id == org_id,
            ProductTemplate.name.in_(list(names)),
        )
    }


def _write_putaway_rules(db, org_id) -> int:
    """Where a receipt's lines go: dairy to the fridges, ready meals to the freezer."""
    from app.modules.warehouse.models.putaway_rule import PutawayRule
    from app.modules.warehouse.models.putaway_rule_location import (
        PutawayRuleLocation,
    )

    if db.query(PutawayRule).filter(PutawayRule.organization_id == org_id).count():
        return 0
    zones = _shelves_by_zone(db, org_id)
    categories = _resolve_category_ids(db, org_id)
    products = _templates_by_name(
        db, org_id, [m['product'] for m, _z, _p in DEMO_PUTAWAY_RULES if 'product' in m]
    )
    written = 0
    for match, zone, priority in DEMO_PUTAWAY_RULES:
        shelves = zones.get(zone) or []
        category_id = categories.get(match.get('category'))
        product = products.get(match.get('product'))
        if not shelves or (category_id is None and product is None):
            continue
        rule = PutawayRule(
            id=uuid.uuid4(),
            organization_id=org_id,
            category_id=category_id,
            product_template_id=product.id if product else None,
            priority=priority,
        )
        db.add(rule)
        for position, shelf in enumerate(shelves[:2]):
            db.add(
                PutawayRuleLocation(
                    organization_id=org_id,
                    rule_id=rule.id,
                    location_id=shelf.id,
                    position=position,
                )
            )
        written += 1
    db.flush()
    return written


def _fullest_shelf(db, template_id):
    """The shelf that holds most of a product."""
    from sqlalchemy import func

    row = (
        db.query(Item.storage_location_id)
        .filter(Item.template_id == template_id, Item.is_deleted.is_(False))
        .group_by(Item.storage_location_id)
        .order_by(func.sum(Item.quantity).desc())
        .first()
    )
    return row[0] if row else None


def _set_reorder_points(db, org_id) -> int:
    """Reorder points for the workshop's ingredients, one of them already crossed."""
    from app.modules.purchase_orders.models import ReorderRule

    if db.query(ReorderRule).filter(ReorderRule.organization_id == org_id).count():
        return 0
    partners = {
        partner.code: partner
        for partner in db.query(Partner).filter(Partner.organization_id == org_id)
    }
    bought_from = {}
    for code, name, _price in DEMO_SUPPLIER_PRICES:
        bought_from.setdefault(name, partners.get(code))
    templates = _templates_by_name(db, org_id, [row[0] for row in DEMO_REORDER_POINTS])
    written = 0
    for name, minimum, maximum, safety in DEMO_REORDER_POINTS:
        template = templates.get(name)
        shelf = _fullest_shelf(db, template.id) if template else None
        if shelf is None:
            continue
        supplier = bought_from.get(name)
        db.add(
            ReorderRule(
                id=uuid.uuid4(),
                organization_id=org_id,
                product_template_id=template.id,
                storage_location_id=shelf,
                min_quantity=minimum,
                max_quantity=maximum,
                safety_stock=safety,
                preferred_partner_id=supplier.id if supplier else None,
            )
        )
        written += 1
    db.flush()
    return written


def _record_supplier_prices(db, org_id) -> int:
    """What the suppliers charge for the workshop's ingredients and the laptops."""
    from app.modules.purchase_orders.models import PartnerPricelist

    if (
        db.query(PartnerPricelist)
        .filter(PartnerPricelist.organization_id == org_id)
        .count()
    ):
        return 0
    currency = _org_currency(db, org_id)
    partners = {
        partner.code: partner
        for partner in db.query(Partner).filter(Partner.organization_id == org_id)
    }
    templates = _templates_by_name(
        db, org_id, [name for _code, name, _price in DEMO_SUPPLIER_PRICES]
    )
    written = 0
    for code, name, price in DEMO_SUPPLIER_PRICES:
        partner, template = partners.get(code), templates.get(name)
        if partner is None or template is None:
            continue
        db.add(
            PartnerPricelist(
                id=uuid.uuid4(),
                organization_id=org_id,
                partner_id=partner.id,
                product_template_id=template.id,
                unit_price=price,
                currency=currency,
                uom_id=template.uom_id,
                valid_from=TODAY - timedelta(days=60),
            )
        )
        written += 1
    db.flush()
    return written


def _photograph_the_recipes(db, org_id) -> int:
    """Give each demo recipe its photograph, stored the way an upload is.

    Through ``store_cover``, the call the recipe page's own "Add photo" makes:
    the file is re-encoded and kept in the app's storage, so the demo shows
    nothing it fetches from another host.

    On a demo that storage admits a write only while the instance total has
    room (``DEMO_UPLOAD_TOTAL_MB``), and every visitor's organization stores
    its own copies. Once the room is spent the recipes stay without their
    photographs: a sandbox without them beats no sandbox at all.
    """
    import asyncio
    import json

    from app.core.exceptions import AppException
    from app.modules.recipes._recipe_cover import store_cover
    from app.modules.recipes.models.recipe import Recipe

    manifest = json.loads((DEMO_RECIPE_PHOTOS / 'sources.json').read_text())
    photo_of = {row['recipe']: row['file'] for row in manifest['photos']}
    recipes = (
        db.query(Recipe)
        .filter(
            Recipe.organization_id == org_id,
            Recipe.name.in_(list(photo_of)),
            Recipe.image_url.is_(None),
        )
        .all()
    )

    async def _store() -> dict:
        stored = {}
        for recipe in recipes:
            try:
                stored[recipe.id] = await store_cover(
                    org_id,
                    recipe.id,
                    (DEMO_RECIPE_PHOTOS / photo_of[recipe.name]).read_bytes(),
                    'image/jpeg',
                )
            except AppException as refused:
                if refused.status_code != 413:
                    raise
                break
        return stored

    stored = asyncio.run(_store())
    for recipe_id, url in stored.items():
        db.get(Recipe, recipe_id).image_url = url
    db.flush()
    return len(stored)


def dress_for_visitors(db, org_id, admin_id, *, report=None) -> dict:
    """Dress an organization the shared seed has filled, for the public demo."""
    say = report if report is not None else (lambda _message: None)
    admin = db.get(User, admin_id)
    org = db.get(Organization, org_id)
    org.name = DEMO_ORGANIZATION_NAME
    # The seed is mostly module-made rows; with this off the Products list
    # opens on "N products are hidden" for every visitor.
    org.settings = {**(org.settings or {}), 'show_module_data': True}
    _let_the_visitor_decide_their_own_orders(org)
    unmarked = _drop_the_seed_marker(db, org_id)
    team = _hire_the_team(db, org_id)
    summary = {
        'seed_markers_removed': unmarked,
        'documents_by_the_team': _hand_the_history_to_the_team(db, org_id, team),
        'approval_requests': _queue_an_approval(db, org_id, admin, team),
        'my_assets': _issue_the_administrator_a_kit(db, org_id, admin),
        'attestation_campaigns': _run_an_attestation(db, org_id, admin),
        'labels': _print_labels(db, org_id, admin),
        'putaway_rules': _write_putaway_rules(db, org_id),
        'reorder_rules': _set_reorder_points(db, org_id),
        'supplier_prices': _record_supplier_prices(db, org_id),
        'recipe_photos': _photograph_the_recipes(db, org_id),
    }
    db.commit()
    for key, count in summary.items():
        say(f'  Showcase: {count} {key.replace("_", " ")}')
    return summary


def dress_from_cli(*, admin_email: str, report=print) -> dict:
    """Dress the administrator's organization; ``manage.py demo reset`` calls this."""
    from app.core.file_storage.service import FileStorageService

    FileStorageService.initialize_from_settings()
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == admin_email).first()
        if admin is None or admin.organization_id is None:
            raise RuntimeError(f'{admin_email} not found — run the demo seed first.')
        return dress_for_visitors(db, admin.organization_id, admin.id, report=report)
    finally:
        db.close()
