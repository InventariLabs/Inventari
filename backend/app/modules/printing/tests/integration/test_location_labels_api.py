"""A shelf label with bars: the code large, in Code 128, a QR beside it if asked.

Many cheap USB scanners read only 1D codes, so a QR-only sticker does not
scan at all on them. A location's label for a business is drawn like a
product's — the bars read back off the PNG here, not taken from the function
that chose them — with the code where a product's name would be, so a person
reads the place off the sticker without scanning.
"""

import io

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.printing.schemas import PROTOCOL_VERSION
from app.modules.printing.services.product_label_service import barcode_modules
from app.modules.printing.tests.bars import read_bars

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
_BASE = '/api/v1/printing'


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Warehouse', ['core', 'items', 'locations', 'printing'])


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='shelves@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


def _shelf(
    h: ModuleTestHelper,
    db_session: Session,
    org: Organization,
    user: User,
    name: str,
    code: str | None,
) -> StorageLocation:
    kind = h.create_storage_type(f'Rack {name}', f'RACK_{name}', organization_id=org.id)
    shelf = h.create_storage_location(org, kind, user, name=name)
    shelf.short_code = code
    db_session.commit()
    return shelf


def _beside_the_square(png: bytes) -> bytes:
    """The label without its QR square, which sits at the left end and is no
    wider than the label is tall."""
    img = Image.open(io.BytesIO(png))
    out = io.BytesIO()
    img.crop((img.height, 0, img.width, img.height)).save(out, 'PNG')
    return out.getvalue()


@pytest.mark.integration
class TestLocationLabelDownload:
    def test_the_bars_carry_the_shelf_code(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        user: User,
        headers: dict[str, str],
    ) -> None:
        shelf = _shelf(h, db_session, org, user, 'Level 1', 'A-02-01')

        resp = client.post(
            f'{_BASE}/location-labels/png',
            headers=headers,
            json={'location_ids': [str(shelf.id)]},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.content.startswith(_PNG_MAGIC)
        assert resp.headers['x-labels-without-code'] == '0'
        assert read_bars(resp.content) == barcode_modules('A-02-01')

    def test_many_shelves_wrap_into_rows_of_full_size_labels(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        user: User,
        headers: dict[str, str],
    ) -> None:
        """The dialog shows this file. As one strip, 29 labels were 17419 px
        wide, which the dialog's width turned into a grey line of bars; the
        rows keep each label at its size and a preview a person can read."""
        shelves = [
            _shelf(h, db_session, org, user, f'S{n}', f'A-{n:02d}') for n in range(7)
        ]

        response = client.post(
            f'{_BASE}/location-labels/png',
            json={'location_ids': [str(shelf.id) for shelf in shelves]},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        sheet = Image.open(io.BytesIO(response.content))
        label_width, label_height = 591, 283
        assert sheet.width == 3 * label_width + 2 * 10
        assert sheet.height == 3 * label_height

    def test_a_qr_goes_beside_the_bars_when_asked(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        user: User,
        headers: dict[str, str],
    ) -> None:
        shelf = _shelf(h, db_session, org, user, 'Level 1', 'A-02-01')

        plain = client.post(
            f'{_BASE}/location-labels/png',
            headers=headers,
            json={'location_ids': [str(shelf.id)], 'width_mm': 70},
        )
        with_qr = client.post(
            f'{_BASE}/location-labels/png',
            headers=headers,
            json={'location_ids': [str(shelf.id)], 'width_mm': 70, 'qr': True},
        )

        assert with_qr.status_code == status.HTTP_200_OK, with_qr.text
        assert with_qr.content != plain.content
        assert read_bars(_beside_the_square(with_qr.content)) == barcode_modules(
            'A-02-01'
        )
        # The left end is the QR square: ink down most of the label's height.
        img = Image.open(io.BytesIO(with_qr.content)).convert('L')
        column = img.crop((img.width // 10, 0, img.width // 10 + 1, img.height))
        inked = sum(1 for value in column.tobytes() if value < 128)
        assert inked > img.height // 5

    def test_a_location_without_a_code_is_left_out_and_counted(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        user: User,
        headers: dict[str, str],
    ) -> None:
        shelf = _shelf(h, db_session, org, user, 'Level 1', 'A-02-01')
        bare = _shelf(h, db_session, org, user, 'Level 2', None)

        resp = client.post(
            f'{_BASE}/location-labels/png',
            headers=headers,
            json={'location_ids': [str(shelf.id), str(bare.id)]},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.headers['x-labels-without-code'] == '1'

    def test_another_organizations_location_does_not_print(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        headers: dict[str, str],
    ) -> None:
        other = h.create_org('Elsewhere', ['core', 'items', 'locations', 'printing'])
        stranger = h.create_user(other, email='stranger@example.com')
        theirs = _shelf(h, db_session, other, stranger, 'Level 1', 'A-02-01')

        resp = client.post(
            f'{_BASE}/location-labels/png',
            headers=headers,
            json={'location_ids': [str(theirs.id)]},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestLocationLabelJob:
    def test_a_queued_shelf_label_prints_its_bars(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        user: User,
        headers: dict[str, str],
    ) -> None:
        shelf = _shelf(h, db_session, org, user, 'Level 1', 'A-02-01')
        agent = client.post(
            f'{_BASE}/agent/register',
            headers=headers,
            json={
                'name': 'office',
                'printer_type': 'zebra',
                'agent_version': '1.0.0',
                'protocol_version': PROTOCOL_VERSION,
            },
        )
        assert agent.status_code == status.HTTP_200_OK, agent.text

        queued = client.post(
            f'{_BASE}/jobs',
            headers=headers,
            json={'location_ids': [str(shelf.id)], 'bars': True},
        )

        assert queued.status_code == status.HTTP_201_CREATED, queued.text
        assert queued.json()['short_codes'] == ['A-02-01']
        image = client.get(
            f'{_BASE}/agent/jobs/{queued.json()["id"]}/image', headers=headers
        )
        assert image.status_code == status.HTTP_200_OK
        assert read_bars(image.content) == barcode_modules('A-02-01')

    def test_without_bars_a_location_keeps_its_qr_label(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        user: User,
        headers: dict[str, str],
    ) -> None:
        """A household's sticker is the QR it always was."""
        shelf = _shelf(h, db_session, org, user, 'Pantry shelf', 'LOC-7KQ2')
        client.post(
            f'{_BASE}/agent/register',
            headers=headers,
            json={
                'name': 'office',
                'printer_type': 'zebra',
                'agent_version': '1.0.0',
                'protocol_version': PROTOCOL_VERSION,
            },
        )

        queued = client.post(
            f'{_BASE}/jobs', headers=headers, json={'location_ids': [str(shelf.id)]}
        )

        assert queued.status_code == status.HTTP_201_CREATED, queued.text
        from app.modules.printing.models import PrintJob

        job = db_session.get(PrintJob, queued.json()['id'])
        assert job is not None
        assert 'kind' not in job.labels[0]
