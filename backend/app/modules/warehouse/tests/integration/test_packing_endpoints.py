"""The packing doors: packages over HTTP, the packing slip and the label.

The rules themselves are pinned on the service, beside this file
(``test_a_dispatch_is_packed_from_what_was_picked.py``); what is pinned here
is what only the HTTP layer decides — the envelope a refusal travels in, the
read-only member's reach, another organization's 404, and that the slip and
the label are a PDF and a PNG carrying the package's code.
"""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus

pytestmark = pytest.mark.integration


@pytest.fixture
def picked_dispatch(
    db_session: Session,
    doc_org: Organization,
    doc_user: User,
    doc_partner: Partner,
) -> Document:
    """A confirmed dispatch of two lines: 4 of 4 bolts and 2 of 3 nuts picked."""
    doc = Document(
        organization_id=doc_org.id,
        type='OUT',
        number='OUT/2026/0042',
        status=DocumentStatus.CONFIRMED.value,
        partner_id=doc_partner.id,
        partner_snapshot={'name': doc_partner.name},
        created_by=doc_user.id,
    )
    for number, (name, expected, done) in enumerate(
        [('Bolt M8', '4', '4'), ('Nut M8', '3', '2')], start=1
    ):
        doc.lines.append(
            DocumentLine(
                name=name,
                quantity=Decimal(expected),
                expected_quantity=Decimal(expected),
                done_quantity=Decimal(done),
                line_number=number,
            )
        )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


def _url(doc: Document, tail: str = '') -> str:
    return f'/api/v1/warehouse/documents/{doc.id}/packages{tail}'


class TestThePackingDoors:
    def test_a_dispatch_is_packed_weighed_and_unpacked_over_http(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        doc = picked_dispatch
        bolts, nuts = (line.id for line in doc.lines)

        empty = client.get(_url(doc), headers=doc_auth_headers)
        assert empty.status_code == 200, empty.text
        assert empty.json()['packages'] == []
        assert empty.json()['editable'] is True

        created = client.post(_url(doc), headers=doc_auth_headers, json={})
        assert created.status_code == 201, created.text
        package_id = created.json()['packages'][0]['id']

        filled = client.put(
            _url(doc, f'/{package_id}/lines/{bolts}'),
            headers=doc_auth_headers,
            json={'quantity': '4'},
        )
        assert filled.status_code == 200, filled.text
        assert Decimal(filled.json()['packages'][0]['lines'][0]['quantity']) == 4

        weighed = client.patch(
            _url(doc, f'/{package_id}'),
            headers=doc_auth_headers,
            json={'weight_kg': '1.5'},
        )
        assert weighed.status_code == 200, weighed.text
        assert Decimal(weighed.json()['packages'][0]['weight_kg']) == Decimal('1.5')

        rest = client.post(_url(doc, '/pack-all'), headers=doc_auth_headers)
        assert rest.status_code == 201, rest.text
        second = rest.json()['packages'][1]
        assert second['code'] == 'OUT/2026/0042-P2'
        assert [
            (ln['document_line_id'], Decimal(ln['quantity'])) for ln in second['lines']
        ] == [(str(nuts), 2)]

        deleted = client.delete(_url(doc, f'/{package_id}'), headers=doc_auth_headers)
        assert deleted.status_code == 200, deleted.text
        # The nuts' box moves down to 1: numbers stay without gaps.
        assert [p['code'] for p in deleted.json()['packages']] == ['OUT/2026/0042-P1']

    def test_over_packing_answers_400_in_the_readers_language(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        doc = picked_dispatch
        nuts = doc.lines[1].id
        package_id = client.post(_url(doc), headers=doc_auth_headers, json={}).json()[
            'packages'
        ][0]['id']

        refused = client.put(
            _url(doc, f'/{package_id}/lines/{nuts}'),
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
            json={'quantity': '3'},
        )

        assert refused.status_code == 400, refused.text
        assert refused.json()['detail']['message'] == (
            'Nut M8: zebrano i nie zapakowano jeszcze tylko 2. Paczka mieści to, '
            'co zebrano, i nic, co jest już w innej paczce.'
        )

    def test_a_scan_packs_the_scanned_product_and_a_stranger_code_is_named(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        doc = picked_dispatch
        bolt = ProductTemplate(
            organization_id=doc.organization_id, name='Bolt M8', barcode='BC-BOLT-M8'
        )
        db_session.add(bolt)
        db_session.flush()
        doc.lines[0].product_template_id = bolt.id
        db_session.commit()
        package_id = client.post(_url(doc), headers=doc_auth_headers, json={}).json()[
            'packages'
        ][0]['id']

        scanned = client.post(
            _url(doc, f'/{package_id}/scan'),
            headers=doc_auth_headers,
            json={'code': 'BC-BOLT-M8'},
        )
        assert scanned.status_code == 200, scanned.text
        assert [
            (ln['product_name'], Decimal(ln['quantity']))
            for ln in scanned.json()['packages'][0]['lines']
        ] == [('Bolt M8', 1)]

        refused = client.post(
            _url(doc, f'/{package_id}/scan'),
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
            json={'code': 'NO-SUCH-CODE'},
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()['detail']['message'].startswith(
            'Żaden produkt nie ma kodu NO-SUCH-CODE.'
        )

    def test_a_negative_quantity_is_refused_by_the_schema(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        doc = picked_dispatch
        package_id = client.post(_url(doc), headers=doc_auth_headers, json={}).json()[
            'packages'
        ][0]['id']

        refused = client.put(
            _url(doc, f'/{package_id}/lines/{doc.lines[0].id}'),
            headers=doc_auth_headers,
            json={'quantity': '-1'},
        )

        assert refused.status_code == 422

    def test_a_read_only_member_reads_but_does_not_pack(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        picked_dispatch: Document,
    ) -> None:
        viewer = h.create_user(doc_org, email='viewer@example.com', role='viewer')
        headers = h.get_auth_headers(viewer)

        assert client.get(_url(picked_dispatch), headers=headers).status_code == 200
        refused = client.post(_url(picked_dispatch, '/pack-all'), headers=headers)
        assert refused.status_code == 403

    def test_another_organization_gets_404(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        picked_dispatch: Document,
    ) -> None:
        other = h.create_org('Elsewhere', ['core', 'warehouse'])
        stranger = h.create_user(other, email='stranger@example.com')
        headers = h.get_auth_headers(stranger)

        assert client.get(_url(picked_dispatch), headers=headers).status_code == 404
        refused = client.post(_url(picked_dispatch, '/pack-all'), headers=headers)
        assert refused.status_code == 404
        assert refused.json()['detail']['code'] == 'DOCUMENT_NOT_FOUND'


class TestThePackingSlipAndTheLabel:
    def _pack_in_two(
        self, client: TestClient, headers: dict[str, str], doc: Document
    ) -> list[dict[str, str]]:
        first = client.post(_url(doc), headers=headers, json={'weight_kg': '2'})
        package_id = first.json()['packages'][0]['id']
        client.put(
            _url(doc, f'/{package_id}/lines/{doc.lines[0].id}'),
            headers=headers,
            json={'quantity': '4'},
        )
        packed: list[dict[str, str]] = client.post(
            _url(doc, '/pack-all'), headers=headers
        ).json()['packages']
        return packed

    def test_the_document_slip_has_a_sheet_per_package_with_its_code(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        self._pack_in_two(client, doc_auth_headers, picked_dispatch)

        slip = client.get(
            f'/api/v1/warehouse/documents/{picked_dispatch.id}/packing-slip',
            headers=doc_auth_headers,
        )

        assert slip.status_code == 200, slip.text[:300]
        assert slip.headers['content-type'] == 'application/pdf'
        pages = PdfReader(io.BytesIO(slip.content)).pages
        text = [page.extract_text() for page in pages]
        assert len(pages) == 2
        assert 'OUT/2026/0042-P1' in text[0]
        assert 'Package 1 of 2' in text[0]
        assert 'Bolt M8' in text[0]
        assert 'OUT/2026/0042-P2' in text[1]
        assert 'Nut M8' in text[1]

    def test_one_packages_slip_still_says_which_of_how_many(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        packages = self._pack_in_two(client, doc_auth_headers, picked_dispatch)

        slip = client.get(
            _url(picked_dispatch, f'/{packages[1]["id"]}/packing-slip'),
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
            params={'lang': 'pl'},
        )

        assert slip.status_code == 200, slip.text[:300]
        pages = PdfReader(io.BytesIO(slip.content)).pages
        assert len(pages) == 1
        text = pages[0].extract_text()
        assert 'List pakowy' in text
        assert 'Paczka 2 z 2' in text
        assert 'OUT/2026/0042-P2' in text

    def test_a_dispatch_with_no_packages_has_no_slip(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        slip = client.get(
            f'/api/v1/warehouse/documents/{picked_dispatch.id}/packing-slip',
            headers=doc_auth_headers,
        )

        assert slip.status_code == 400
        assert 'no packages' in slip.json()['detail']['message']

    def test_the_organizations_own_slip_template_wins(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        """The slip prints through the template mechanism like every printout."""
        self._pack_in_two(client, doc_auth_headers, picked_dispatch)
        created = client.post(
            '/api/v1/warehouse/templates',
            headers=doc_auth_headers,
            json={
                'module': 'warehouse',
                'name': 'Our slip',
                'document_type': 'PACKING_SLIP',
                'is_default': True,
                'body_html': (
                    '<p>{% for package in packages %}BOX {{ package.code }} '
                    '{% endfor %}</p>'
                ),
            },
        )
        assert created.status_code == 201, created.text

        slip = client.get(
            f'/api/v1/warehouse/documents/{picked_dispatch.id}/packing-slip',
            headers=doc_auth_headers,
        )

        text = PdfReader(io.BytesIO(slip.content)).pages[0].extract_text()
        assert 'BOX OUT/2026/0042-P1' in text
        assert 'BOX OUT/2026/0042-P2' in text

    def test_the_label_is_a_png_from_the_printing_module(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        packages = self._pack_in_two(client, doc_auth_headers, picked_dispatch)

        label = client.get(
            _url(picked_dispatch, f'/{packages[0]["id"]}/label'),
            headers=doc_auth_headers,
            params={'width': 60, 'height': 30},
        )

        assert label.status_code == 200, label.text[:300]
        assert label.headers['content-type'] == 'image/png'
        assert label.content.startswith(b'\x89PNG')
        assert 'OUT-2026-0042-P1' in label.headers['content-disposition']

    def test_after_a_middle_package_goes_the_slip_and_label_count_agree(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Three boxes, the second deleted: the third is now "2 of 2", not "3 of 2"."""
        from app.core import label_rendering

        doc, headers = picked_dispatch, doc_auth_headers
        for _ in range(3):
            client.post(_url(doc), headers=headers, json={})
        packages = client.get(_url(doc), headers=headers).json()['packages']
        client.put(
            _url(doc, f'/{packages[2]["id"]}/lines/{doc.lines[0].id}'),
            headers=headers,
            json={'quantity': '4'},
        )
        deleted = client.delete(_url(doc, f'/{packages[1]["id"]}'), headers=headers)
        assert deleted.status_code == 200, deleted.text

        slip = client.get(
            f'/api/v1/warehouse/documents/{doc.id}/packing-slip', headers=headers
        )
        text = [p.extract_text() for p in PdfReader(io.BytesIO(slip.content)).pages]
        assert len(text) == 2
        assert 'Package 2 of 2' in text[1]
        assert 'OUT/2026/0042-P2' in text[1]
        assert 'Bolt M8' in text[1]

        drawn: list[str] = []
        render = label_rendering.render_label_png

        def spy(label: Any, **kwargs: Any) -> bytes:
            drawn.append(label.description)
            return render(label, **kwargs)

        monkeypatch.setattr(label_rendering, 'render_label_png', spy)
        label = client.get(
            _url(doc, f'/{packages[2]["id"]}/label'),
            headers=headers,
            params={'width': 60, 'height': 30},
        )
        assert label.status_code == 200, label.text[:300]
        assert 'OUT-2026-0042-P2' in label.headers['content-disposition']
        assert drawn == ['Acme Supplies · 2/2']

    def test_the_label_goes_to_the_print_queue_as_the_download_draws_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        from app.modules.printing.schemas import PROTOCOL_VERSION

        agent = client.post(
            '/api/v1/printing/agent/register',
            headers=doc_auth_headers,
            json={
                'name': 'packing bench',
                'printer_type': 'zebra',
                'protocol_version': PROTOCOL_VERSION,
            },
        )
        assert agent.status_code == 200, agent.text
        packages = self._pack_in_two(client, doc_auth_headers, picked_dispatch)
        package = _url(picked_dispatch, f'/{packages[1]["id"]}/label')

        queued = client.post(
            f'{package}/print',
            headers=doc_auth_headers,
            json={'width_mm': 60, 'height_mm': 30},
        )

        assert queued.status_code == 201, queued.text
        job_id = queued.json()['job_id']
        jobs = client.get('/api/v1/printing/jobs', headers=doc_auth_headers).json()[
            'items'
        ]
        assert [(j['id'], j['short_codes'], j['count']) for j in jobs] == [
            (job_id, ['OUT/2026/0042-P2'], 1)
        ]
        assert (jobs[0]['width_mm'], jobs[0]['height_mm']) == (60, 30)
        # The printer gets the very label the download gives: the package's
        # code, whom it is for and which box, and a QR opening the dispatch.
        printed = client.get(
            f'/api/v1/printing/agent/jobs/{job_id}/image', headers=doc_auth_headers
        )
        downloaded = client.get(
            package, headers=doc_auth_headers, params={'width': 60, 'height': 30}
        )
        assert printed.status_code == 200, printed.text[:300]
        assert printed.content == downloaded.content

    def test_a_packer_prints_the_package_and_only_the_warehouse_reads_the_job(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        """A package card picks its printer from the same list as a shelf card.

        A packer holds the warehouse's grants and may hold no read of
        products or shelves; the job carries whom the package is for, so the
        queue shows it to the warehouse's readers and not to theirs.
        """
        from app.modules.printing.schemas import PROTOCOL_VERSION

        client.post(
            '/api/v1/printing/agent/register',
            headers=doc_auth_headers,
            json={
                'name': 'packing bench',
                'printer_type': 'zebra',
                'protocol_version': PROTOCOL_VERSION,
            },
        )
        packages = self._pack_in_two(client, doc_auth_headers, picked_dispatch)
        packer = h.create_user(doc_org, email='packer@example.com', role='user')
        h.grant_permissions(packer, ['warehouse:read', 'warehouse:write'])
        stock = h.create_user(doc_org, email='stock@example.com', role='user')
        h.grant_permissions(stock, ['items:read', 'locations:read'])
        headers = h.get_auth_headers(packer)

        printers = client.get('/api/v1/printing/agents', headers=headers)
        queued = client.post(
            _url(picked_dispatch, f'/{packages[0]["id"]}/label/print'),
            headers=headers,
            json={},
        )
        packers_queue = client.get('/api/v1/printing/jobs', headers=headers)
        stock_queue = client.get(
            '/api/v1/printing/jobs', headers=h.get_auth_headers(stock)
        )

        assert printers.status_code == 200, printers.text
        assert queued.status_code == 201, queued.text
        assert [job['id'] for job in packers_queue.json()['items']] == [
            queued.json()['job_id']
        ]
        assert stock_queue.json()['items'] == []

    def test_with_no_printer_the_label_is_refused_in_words(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        packages = self._pack_in_two(client, doc_auth_headers, picked_dispatch)

        refused = client.post(
            _url(picked_dispatch, f'/{packages[0]["id"]}/label/print'),
            headers=doc_auth_headers,
            json={},
        )

        assert refused.status_code == 400, refused.text
        assert refused.json()['detail']['code'] == 'PRINT_NO_AGENT'

    def test_a_missing_package_has_no_label(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        picked_dispatch: Document,
    ) -> None:
        missing = client.get(
            _url(picked_dispatch, '/00000000-0000-0000-0000-000000000000/label'),
            headers=doc_auth_headers,
        )

        assert missing.status_code == 404
        assert missing.json()['detail']['code'] == 'PACKAGE_NOT_FOUND'
