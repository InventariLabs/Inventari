"""The one answer to "who or what holds this asset".

An assignment hands an asset to a person or stands it in a place, and every
surface that names the holder — the list column, the timeline card, the
overdue row, the notification sentence, the export cell — reads this answer
instead of assembling its own from the three raw fields. The kind travels
with the name because the screens word the two differently: a rack does not
"possess" a laptop.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.modules.equipment._holder import (
    PERSON,
    PLACE,
    Holder,
    holder_of_assignment,
    holder_of_parts,
)


@pytest.mark.unit
class TestHolderOfParts:
    def test_a_person_is_the_free_text_name(self) -> None:
        assert holder_of_parts(assigned_to_name='Anna Kowalska') == Holder(
            name='Anna Kowalska', kind=PERSON
        )

    def test_the_partner_record_outranks_the_free_text_copy(self) -> None:
        assert holder_of_parts(
            partner_name='Anna Kowalska', assigned_to_name='A. Kowalska'
        ) == Holder(name='Anna Kowalska', kind=PERSON)

    def test_a_place_holds_it_when_no_person_does(self) -> None:
        assert holder_of_parts(checkout_location_name='Server Rack A') == Holder(
            name='Server Rack A', kind=PLACE
        )

    def test_a_whitespace_name_is_no_name_and_falls_to_the_place(self) -> None:
        # The location mode posts an empty string on purpose; a caller that
        # sends spaces instead must not produce a blank holder either.
        assert holder_of_parts(
            assigned_to_name='   ', checkout_location_name='Server Rack A'
        ) == Holder(name='Server Rack A', kind=PLACE)

    def test_a_whitespace_partner_falls_through_to_the_name(self) -> None:
        assert holder_of_parts(partner_name='  ', assigned_to_name='Jan') == Holder(
            name='Jan', kind=PERSON
        )

    def test_the_name_is_trimmed_for_the_reader(self) -> None:
        assert holder_of_parts(assigned_to_name='  Jan  ') == Holder(
            name='Jan', kind=PERSON
        )

    def test_an_empty_assignment_has_no_holder(self) -> None:
        assert holder_of_parts() is None
        assert (
            holder_of_parts(
                partner_name=' ', assigned_to_name='', checkout_location_name='  '
            )
            is None
        )


@pytest.mark.unit
class TestHolderOfAssignment:
    def test_walks_the_relationships(self) -> None:
        assignment = MagicMock()
        assignment.assigned_to_name = ''
        assignment.assignee_partner = None
        assignment.checkout_location = MagicMock(name='checkout_location')
        assignment.checkout_location.name = 'Server Room'
        place_id = uuid4()
        assignment.checkout_location_id = place_id
        # The place's id rides along: while the asset stands there, the list
        # reports that place as its location.
        assert holder_of_assignment(assignment) == Holder(
            name='Server Room', kind=PLACE, place_id=place_id
        )

    def test_the_live_partner_name_wins(self) -> None:
        assignment = MagicMock()
        assignment.assigned_to_name = 'old name'
        assignment.assignee_partner = MagicMock(name='assignee_partner')
        assignment.assignee_partner.name = 'Anna Kowalska'
        assignment.checkout_location = None
        assert holder_of_assignment(assignment) == Holder(
            name='Anna Kowalska', kind=PERSON
        )
