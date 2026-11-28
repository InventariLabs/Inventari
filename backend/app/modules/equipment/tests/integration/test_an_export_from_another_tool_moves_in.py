"""A sheet exported by Snipe-IT or Shelf imports with the suggested mapping.

The header rows are the ones those tools write: the Snipe-IT custom asset
report, the Snipe-IT list export and the Shelf asset export. A place or a
category the sheet names is founded, or the row is refused by that name.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.contracts import SystemPermission
from app.core.import_sheet import read_rows
from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


def _sheet(headers: list[str], *rows: list[str]) -> bytes:
    out = io.StringIO()
    csv.writer(out).writerows([headers, *rows])
    return out.getvalue().encode('utf-8')


_SNIPE_REPORT = _sheet(
    [
        'Asset Name',
        'Asset Tag',
        'Model',
        'Model No.',
        'Category',
        'Manufacturer',
        'Serial',
        'Purchased',
        'Cost',
        'Warranty',
        'Warranty Expires',
        'Supplier',
        'Location',
        'Checked Out',
        'Notes',
        'Status',
    ],
    [
        'Drill 1',
        'A-001',
        'GSR 18',
        'GSR18',
        'Power Tools',
        'Bosch',
        'SR-1',
        '2024-03-10',
        '1,289.00',
        '24',
        '2026-03-10',
        'Tool Shop',
        'Workshop',
        '',
        'Spare battery',
        'Ready to Deploy',
    ],
    [
        'Iron 1',
        'A-002',
        'T12',
        '',
        'Soldering',
        'Hakko',
        'SR-2',
        '',
        '',
        '',
        '',
        '',
        'Workshop',
        'anna',
        '',
        'Out for Repair',
    ],
)

_SNIPE_LIST = _sheet(
    [
        'Name',
        'Asset Tag',
        'Category',
        'Manufacturer',
        'Location',
        'Model',
        'Purchase Date',
        'Purchase Cost',
    ],
    [
        'Laptop 7',
        'A-100',
        'Laptops',
        'Dell',
        'Office',
        'Latitude',
        '4/12/23',
        '4200.50',
    ],
)

_SHELF = _sheet(
    [
        'Name',
        'Asset ID',
        'Status',
        'Description',
        'Value',
        'Category',
        'Tags',
        'Location',
        'Custody',
        'Serial number',
        'Purchase date',
        'Warranty ends',
    ],
    [
        'Camera',
        'c1',
        'AVAILABLE',
        'Body only',
        '$1,289.00',
        'Photo',
        '',
        'Studio',
        '',
        'SH-1',
        '2024-01-05',
        '2025-01-05',
    ],
    [
        'Tripod',
        'c2',
        'IN_CUSTODY',
        '',
        '',
        'Photo',
        '',
        'Studio',
        'Piotr',
        'SH-2',
        '',
        '',
    ],
    [
        'Lamp',
        'c3',
        'CHECKED_OUT',
        '',
        '',
        'Photo',
        '',
        'Studio',
        '',
        'SH-3',
        '',
        '',
    ],
)


def _import(
    client: TestClient,
    headers: dict[str, str],
    content: bytes,
    **form: str,
) -> Any:
    """Analyze the sheet and import it with the mapping the analyze suggests."""
    analyzed = client.post(
        '/api/v1/equipment/import/analyze',
        headers=headers,
        files={'file': ('export.csv', content, 'text/csv')},
    )
    assert analyzed.status_code == status.HTTP_200_OK, analyzed.text
    return client.post(
        '/api/v1/equipment/import/execute',
        headers=headers,
        files={'file': ('export.csv', content, 'text/csv')},
        data={
            'mapping_json': json.dumps(analyzed.json()['suggested_mapping']),
            **form,
        },
    )


def _assets(db: Session, org: Organization) -> dict[str, Item]:
    db.expire_all()
    rows = db.scalars(select(Item).where(Item.organization_id == org.id))
    return {item.name: item for item in rows}


def _meta(item: Item) -> dict[str, Any]:
    return dict((item.meta_data or {})['equipment'])


def _places(db: Session, org: Organization) -> set[str]:
    db.expire_all()
    return set(
        db.scalars(
            select(StorageLocation.name).where(
                StorageLocation.organization_id == org.id,
                StorageLocation.usage == 'internal',
            )
        )
    )


def _categories(db: Session, org: Organization) -> dict[str, str | None]:
    db.expire_all()
    rows = db.scalars(select(Category).where(Category.organization_id == org.id))
    return {category.name: category.context_tag for category in rows}


def test_the_snipe_it_custom_report(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_org: Organization,
    db_session: Session,
) -> None:
    resp = _import(client, eq_auth_headers, _SNIPE_REPORT)

    assert resp.status_code == status.HTTP_200_OK, resp.text
    body = resp.json()
    assert (body['imported'], body['failed']) == (2, 0), body['errors']
    assert body['created_locations'] == ['Workshop']
    assert body['created_categories'] == ['Power Tools', 'Soldering']
    assets = _assets(db_session, eq_org)
    drill = _meta(assets['Drill 1'])
    assert drill['purchase_date'] == '2024-03-10'
    assert drill['warranty_until'] == '2026-03-10'
    assert drill['equipment_status'] == 'AVAILABLE'
    assert assets['Drill 1'].purchase_price == Decimal('1289')
    assert _meta(assets['Iron 1'])['equipment_status'] == ('MAINTENANCE')
    assert _categories(db_session, eq_org) == {
        'Power Tools': 'equipment',
        'Soldering': 'equipment',
    }


def test_the_snipe_it_list_export(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_org: Organization,
    eq_category: Category,
    db_session: Session,
) -> None:
    """ "Laptops" beside the seeded "Laptop" is its own category, named in the result."""
    resp = _import(client, eq_auth_headers, _SNIPE_LIST)

    body = resp.json()
    assert (body['imported'], body['failed']) == (1, 0), body['errors']
    assert body['created_locations'] == ['Office']
    assert body['created_categories'] == ['Laptops']
    laptop = _assets(db_session, eq_org)['Laptop 7']
    assert _meta(laptop)['purchase_date'] == '2023-04-12'
    assert laptop.purchase_price == Decimal('4200.50')
    assert laptop.category_id != eq_category.id


def test_the_shelf_export(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_org: Organization,
    db_session: Session,
) -> None:
    resp = _import(client, eq_auth_headers, _SHELF)

    body = resp.json()
    assert (body['imported'], body['failed']) == (3, 0), body['errors']
    assert body['created_locations'] == ['Studio']
    assert body['created_categories'] == ['Photo']
    assets = _assets(db_session, eq_org)
    assert {
        name: _meta(asset)['equipment_status'] for name, asset in assets.items()
    } == {'Camera': 'AVAILABLE', 'Tripod': 'DEPLOYED', 'Lamp': 'DEPLOYED'}
    assert assets['Camera'].purchase_price == Decimal('1289')
    assert _meta(assets['Camera'])['warranty_until'] == '2025-01-05'
    assert _meta(assets['Camera'])['asset_tag'] == 'c1'
    assert _meta(assets['Camera'])['notes'] == 'Body only'


def test_asset_tag_and_notes_columns_come_before_asset_id_and_description(
    client: TestClient,
    eq_auth_headers: dict[str, str],
) -> None:
    sheet = _sheet(
        ['Asset ID', 'Description', 'Asset Tag', 'Notes', 'Name'],
        ['id', 'text', 'tag', 'note', 'Saw'],
    )

    analyzed = client.post(
        '/api/v1/equipment/import/analyze',
        headers=eq_auth_headers,
        files={'file': ('export.csv', sheet, 'text/csv')},
    )

    suggested = analyzed.json()['suggested_mapping']
    assert (suggested['asset_tag'], suggested['notes']) == ('Asset Tag', 'Notes')


def test_the_refused_rows_come_back_as_a_file_that_imports_once_corrected(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_org: Organization,
    db_session: Session,
) -> None:
    sheet = _sheet(
        ['Name', 'Location', 'Cost'],
        ['Saw', 'Workshop', '10'],
        ['Press', 'Workshop', 'a lot'],
        ['', 'Workshop', ''],
    )

    body = _import(client, eq_auth_headers, sheet).json()

    assert (body['imported'], body['failed']) == (1, 2), body
    answer = body['refused_file']
    assert answer['filename'] == 'export-refused.csv'
    content = base64.b64decode(answer['content_base64'])
    frame = read_rows(content, answer['filename'])
    assert list(frame.columns) == ['Name', 'Location', 'Cost', 'Reason refused']
    assert list(frame['Cost'].fillna('')) == ['a lot', '']

    corrected = _sheet(['Name', 'Location', 'Cost'], ['Press', 'Workshop', '20'])
    fixed = _import(client, eq_auth_headers, corrected).json()
    assert (fixed['imported'], fixed['failed']) == (1, 0), fixed
    assert fixed['refused_file'] is None
    assert set(_assets(db_session, eq_org)) == {'Saw', 'Press'}


def test_a_place_the_sheet_founds_is_an_equipment_place(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_storage_location: StorageLocation,
    db_session: Session,
) -> None:
    sheet = _sheet(
        ['Name', 'Location'],
        ['One', 'Workshop > Bench'],
        ['Two', 'Server Room A > Rack 1'],
    )

    body = _import(client, eq_auth_headers, sheet).json()

    assert (body['imported'], body['failed']) == (2, 0), body['errors']
    listed = client.get(
        '/api/v1/locations',
        headers=eq_auth_headers,
        params={'context_tag': 'equipment', 'limit': 100},
    )
    assert listed.status_code == status.HTTP_200_OK, listed.text
    names = {place['name'] for place in listed.json()['items']}
    assert {'Workshop', 'Bench', 'Rack 1'} <= names


def test_months_of_warranty_end_that_long_after_the_purchase(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_org: Organization,
    db_session: Session,
) -> None:
    """A month with no such day ends on its last one; with no purchase date
    there is nothing to count from, and the row says so."""
    sheet = _sheet(
        ['Name', 'Location', 'Purchased', 'Warranty'],
        ['Bought', 'Workshop', '2024-01-31', '1'],
        ['Spelled', 'Workshop', '2024-03-10', '24 months'],
        ['Undated', 'Cellar', '', '24'],
    )

    body = _import(client, eq_auth_headers, sheet).json()

    assert (body['imported'], body['failed']) == (2, 1), body['errors']
    assert body['errors'][0]['row'] == 3
    assert 'purchase date' in body['errors'][0]['error']
    assert '"Warranty"' in body['errors'][0]['error']
    assets = _assets(db_session, eq_org)
    assert _meta(assets['Bought'])['warranty_until'] == '2024-02-29'
    assert _meta(assets['Spelled'])['warranty_until'] == '2026-03-10'
    # The refused row founded nothing.
    assert body['created_locations'] == ['Workshop']
    assert 'Cellar' not in _places(db_session, eq_org)


def test_a_path_is_founded_inside_the_part_that_exists(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    db_session: Session,
) -> None:
    sheet = _sheet(
        ['Name', 'Location'],
        ['One', 'Server Room A > Rack 1 > Shelf'],
        ['Two', 'Server Room A > Rack 1'],
    )

    body = _import(client, eq_auth_headers, sheet).json()

    assert (body['imported'], body['failed']) == (2, 0), body['errors']
    assert body['created_locations'] == [
        'Server Room A › Rack 1',
        'Server Room A › Rack 1 › Shelf',
    ]
    assets = _assets(db_session, eq_org)
    rack = db_session.get(StorageLocation, assets['Two'].storage_location_id)
    assert rack is not None
    assert rack.parent_id == eq_storage_location.id
    shelf = db_session.get(StorageLocation, assets['One'].storage_location_id)
    assert shelf is not None
    assert shelf.parent_id == rack.id


def test_with_founding_off_the_row_is_refused_by_name(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    db_session: Session,
) -> None:
    sheet = _sheet(
        ['Name', 'Location', 'Category'],
        ['Nowhere', 'Attic', ''],
        ['Untyped', 'Server Room A', 'Gadgets'],
    )

    body = _import(
        client,
        eq_auth_headers,
        sheet,
        create_missing_locations='false',
        create_missing_categories='false',
    ).json()

    assert (body['imported'], body['failed']) == (0, 2), body
    assert 'Attic' in body['errors'][0]['error']
    assert 'Gadgets' in body['errors'][1]['error']
    assert _places(db_session, eq_org) == {'Server Room A'}
    assert _categories(db_session, eq_org) == {}


def test_a_name_an_archived_place_holds_fails_its_row_alone(
    client: TestClient,
    eq_auth_headers: dict[str, str],
    eq_storage_location: StorageLocation,
    db_session: Session,
) -> None:
    eq_storage_location.settings = {'archived': True}
    db_session.commit()
    sheet = _sheet(
        ['Name', 'Location'],
        ['Blocked', 'Server Room A'],
        ['Fine', 'Workshop'],
    )

    resp = _import(client, eq_auth_headers, sheet)

    assert resp.status_code == status.HTTP_200_OK, resp.text
    body = resp.json()
    assert (body['imported'], body['failed']) == (1, 1), body
    assert 'Server Room A' in body['errors'][0]['error']


@pytest.mark.parametrize(
    ('switch', 'permission'),
    [
        ('create_missing_locations', 'locations:write'),
        ('create_missing_categories', 'categories:write'),
    ],
)
def test_founding_needs_the_permission_the_front_door_asks_for(
    client: TestClient,
    h: ModuleTestHelper,
    eq_org: Organization,
    db_session: Session,
    switch: str,
    permission: str,
) -> None:
    user = h.create_user(
        eq_org, email=f'rw-{uuid.uuid4().hex[:6]}@example.com', role='user'
    )
    role = Role(
        name='Registrar',
        organization_id=eq_org.id,
        permissions=[
            SystemPermission.ITEMS_READ.value,
            SystemPermission.ITEMS_WRITE.value,
            'equipment:read',
            'equipment:write',
        ],
    )
    db_session.add(role)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    other = (
        'create_missing_categories'
        if switch == 'create_missing_locations'
        else 'create_missing_locations'
    )

    resp = _import(
        client,
        h.get_auth_headers(user),
        _SNIPE_LIST,
        **{switch: 'true', other: 'false'},
    )

    assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text
    assert permission in resp.text
    assert _places(db_session, eq_org) == set()
