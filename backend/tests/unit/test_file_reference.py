"""A file-backed column keeps a key; the address is built when it is read.

The contract these pin is the one ``docs/subsystems/FILE_STORAGE.md`` hands a
module author: store what ``save_for_org_async`` returns, never the address a
backend built, and build the address on the way out. A client may post back
the address it was given, so both directions are total and idempotent.
"""

from __future__ import annotations

import pytest

from app.core.file_reference import cover_extension, served_url, stored_reference

pytestmark = pytest.mark.unit

_KEY = 'f47ac10b-58cc-4372-a567-0e02b2c3d479/items/0b7c1f2e-1111-4222-8333-944455556666/cover.png'
_SERVED = f'/uploads/{_KEY}'
_FOREIGN = 'https://images.openfoodfacts.org/images/products/123/front.jpg'


class TestServedUrl:
    def test_a_key_becomes_the_apps_own_route(self) -> None:
        assert served_url(_KEY) == _SERVED

    def test_an_address_is_returned_unchanged(self) -> None:
        # Applying the builder twice must not double the prefix: a reader that
        # got a served URL and passes it on again is the normal case.
        assert served_url(_SERVED) == _SERVED

    def test_a_foreign_address_is_not_rewritten(self) -> None:
        # A picture on somebody else's server is not ours to serve.
        assert served_url(_FOREIGN) == _FOREIGN

    @pytest.mark.parametrize('value', [None, ''])
    def test_an_absent_reference_stays_absent(self, value) -> None:
        assert served_url(value) == value


class TestStoredReference:
    def test_a_served_address_comes_back_as_its_key(self) -> None:
        # The edit form posts the value it was shown; the row keeps the key.
        assert stored_reference(_SERVED) == _KEY

    def test_a_key_is_kept_as_it_is(self) -> None:
        assert stored_reference(_KEY) == _KEY

    def test_a_foreign_address_is_kept_as_it_is(self) -> None:
        assert stored_reference(_FOREIGN) == _FOREIGN

    def test_an_absent_reference_stays_absent(self) -> None:
        assert stored_reference(None) is None

    def test_the_two_directions_round_trip(self) -> None:
        assert stored_reference(served_url(_KEY)) == _KEY
        assert served_url(stored_reference(_SERVED)) == _SERVED


class TestCoverExtension:
    """A delete reads only the extension; the key is rebuilt from the entity.

    The column is writable through the forms, so a delete that took the whole
    reference would let one row name another row's picture.
    """

    @pytest.mark.parametrize('value', [_KEY, _SERVED])
    def test_a_cover_reference_answers_its_extension(self, value) -> None:
        assert cover_extension(value) == 'png'

    def test_a_foreign_address_answers_nothing(self) -> None:
        # Somebody else's server owns that file; the row only forgets it.
        assert cover_extension(_FOREIGN) is None

    @pytest.mark.parametrize(
        'value',
        [
            None,
            '',
            'no-extension',
            'f47ac10b-58cc-4372-a567-0e02b2c3d479/items/x/cover.exe',
            'f47ac10b-58cc-4372-a567-0e02b2c3d479/items/x/cover.png/../../secret.exe',
        ],
    )
    def test_a_value_that_does_not_end_in_a_cover_extension_answers_nothing(
        self, value
    ) -> None:
        assert cover_extension(value) is None

    def test_the_answer_is_a_bare_extension_never_a_path(self) -> None:
        # The caller rebuilds the key from the entity it is serving, so a
        # path smuggled in front of the tail is discarded with the rest.
        assert cover_extension('a/b/../../cover.jpg') == 'jpg'
