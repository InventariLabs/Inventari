"""The printed receipt totals quantities inside a unit, not across them.

The unit test pins the template and its context. This one takes the paper
the app really produces: a receipt read back out of the database — lines
and units loaded the way the PDF endpoint loads them — through the
organization's pl_pz layout and WeasyPrint.

The totals row used to add the columns up whatever units the lines were
kept in: 123 pieces and 2,5 kilograms printed as "125,5", a number about
nothing. It prints one total per unit now, and the single sum for a
document kept in one unit.
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.warehouse.models import Document, DocumentLine

_LINES = tuple[Uom | None, str, str]


@pytest.mark.integration
class TestAReceiptTotalsInsideAUnit:
    @staticmethod
    def _receipt(
        org: Organization,
        user: User,
        partner: Partner,
        target: StorageLocation,
        *lines: _LINES,
    ) -> Document:
        doc = Document(
            organization_id=org.id,
            type='IN',
            number='IN/2026/001',
            status='CONFIRMED',
            partner_id=partner.id,
            target_location_id=target.id,
            created_by=user.id,
        )
        for number, (uom, expected, done) in enumerate(lines, start=1):
            doc.lines.append(
                DocumentLine(
                    name=f'Line {number}',
                    quantity=Decimal(expected),
                    expected_quantity=Decimal(expected),
                    done_quantity=Decimal(done),
                    uom_id=uom.id if uom is not None else None,
                    line_number=number,
                )
            )
        return doc

    @staticmethod
    def _paper_text(pdf: bytes) -> str:
        """The page as a reader sees it, layout kept.

        The default pypdf walk drops the totals row's fragments; the layout
        mode keeps them on their columns, which is where the totals live.
        The number and its unit print joined by a non-breaking space; the
        assertions read it as a plain one.
        """
        reader = PdfReader(BytesIO(pdf))
        text = '\n'.join(
            page.extract_text(extraction_mode='layout') for page in reader.pages
        )
        return text.replace('\xa0', ' ')

    def _print(
        self,
        client: TestClient,
        db_session: Session,
        headers: dict[str, str],
        doc: Document,
    ) -> str:
        db_session.add(doc)
        db_session.commit()
        profile = client.put(
            '/api/v1/warehouse/profile',
            headers=headers,
            json={'print_template': 'pl_pz'},
        )
        assert profile.status_code == 200, profile.text

        pdf = client.get(f'/api/v1/warehouse/documents/{doc.id}/pdf', headers=headers)
        assert pdf.status_code == 200, pdf.text
        assert pdf.content[:4] == b'%PDF'
        return self._paper_text(pdf.content)

    def test_the_paper_totals_each_unit_apart(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_uom_pcs: Uom,
        doc_uom_kg: Uom,
    ) -> None:
        """The case the fix is for — prints "125,5" without it."""
        text = self._print(
            client,
            db_session,
            doc_auth_headers,
            self._receipt(
                doc_org,
                doc_user,
                doc_partner,
                doc_target_location,
                (doc_uom_pcs, '123', '123'),
                (doc_uom_kg, '2.5', '0'),
            ),
        )

        assert '125,5' not in text, 'pieces and kilograms were added up'
        # Beside the line rows, only the totals row prints a number and its
        # unit together — the totals under Zamówiono and Przyjęto.
        assert '2,5 kg' in text
        assert '0 kg' in text

    def test_the_paper_keeps_one_sum_for_one_unit(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_uom_pcs: Uom,
    ) -> None:
        """A guard, not a red-before test: the single sum printed before the
        fix too, and must keep printing.
        """
        text = self._print(
            client,
            db_session,
            doc_auth_headers,
            self._receipt(
                doc_org,
                doc_user,
                doc_partner,
                doc_target_location,
                (doc_uom_pcs, '100', '25'),
                (doc_uom_pcs, '25', '0'),
            ),
        )

        assert '125' in text, 'the single sum is gone'
