"""Unit tests for ``build_document_event_payload`` (dedup 4.4).

Four document lifecycle events (CONFIRMED, COMPLETED, CANCELLED and the
rework-cancel) built the same payload inline. Subscribers read these keys, so
the extraction has to preserve the shape exactly — including key order, which
is what a byte-comparing consumer would notice.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

from app.modules.warehouse._document_workflow_helpers import (
    build_document_event_payload,
)

ORG_ID = UUID('11111111-1111-1111-1111-111111111111')
DOC_ID = UUID('22222222-2222-2222-2222-222222222222')
PO_LINE_ID = UUID('33333333-3333-3333-3333-333333333333')


def _doc(*lines: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        id=DOC_ID,
        type='IN',
        lines=list(lines),
        source_location=None,
        source_location_id=None,
        target_location=None,
        target_location_id=None,
    )


def _line(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        source_po_line_id=kwargs.get('source_po_line_id'),
        expected_quantity=kwargs.get('expected_quantity'),
        done_quantity=kwargs.get('done_quantity'),
        product_template_id=None,
        item=None,
        product_template=None,
        uom=None,
        sku=None,
        serial_number=None,
        batch_number=None,
        source_location_id=None,
        source_location=None,
        executed_location_id=None,
        executed_location=None,
        target_location_id=None,
    )


#: What the line says about the goods when it names none: every key present.
NO_DETAIL = {
    'product_id': None,
    'product_code': None,
    'lot_id': None,
    'lot_number': None,
    'source_location_id': None,
    'source_location_code': None,
    'target_location_id': None,
    'target_location_code': None,
    'unit': None,
}


class TestBuildDocumentEventPayload:
    async def test_default_shape_matches_the_confirmed_cancelled_events(self) -> None:
        payload = await build_document_event_payload(
            None, _doc(_line(source_po_line_id=PO_LINE_ID, expected_quantity=3)), ORG_ID
        )
        assert payload == {
            'organization_id': str(ORG_ID),
            'document_id': str(DOC_ID),
            'document_type': 'IN',
            'lines': [
                {
                    'source_po_line_id': str(PO_LINE_ID),
                    'done_quantity': 0.0,
                    'expected_quantity': 3.0,
                    **NO_DETAIL,
                }
            ],
        }

    async def test_done_quantity_is_carried_by_every_event(
        self,
    ) -> None:
        payload = await build_document_event_payload(
            None,
            _doc(
                _line(
                    source_po_line_id=PO_LINE_ID, expected_quantity=3, done_quantity=2
                )
            ),
            ORG_ID,
        )
        assert payload['lines'] == [
            {
                'source_po_line_id': str(PO_LINE_ID),
                'done_quantity': 2.0,
                'expected_quantity': 3.0,
                **NO_DETAIL,
            }
        ]

    async def test_line_key_order_is_preserved(self) -> None:
        """The COMPLETED event emitted done_quantity *between* the other two.

        Building the dict in one literal with a trailing conditional would
        have moved it to the end — invisible to an equality assertion, visible
        to anything comparing serialised JSON.
        """
        payload = await build_document_event_payload(
            None,
            _doc(_line(expected_quantity=1, done_quantity=1)),
            ORG_ID,
        )
        assert list(payload['lines'][0]) == [
            'source_po_line_id',
            'done_quantity',
            'expected_quantity',
            *NO_DETAIL,
        ]

    async def test_missing_po_line_becomes_none_not_the_string_none(self) -> None:
        payload = await build_document_event_payload(
            None, _doc(_line(expected_quantity=1)), ORG_ID
        )
        assert payload['lines'][0]['source_po_line_id'] is None

    async def test_null_quantities_coerce_to_zero(self) -> None:
        payload = await build_document_event_payload(None, _doc(_line()), ORG_ID)
        assert payload['lines'][0]['expected_quantity'] == 0.0
        assert payload['lines'][0]['done_quantity'] == 0.0

    async def test_document_without_lines_yields_an_empty_list(self) -> None:
        assert (await build_document_event_payload(None, _doc(), ORG_ID))['lines'] == []
