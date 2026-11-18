"""What a storage label prints under its QR code.

The toggle offering the caption says "show description on label", and the label
prints that description, never the name behind a hardcoded "Place: " prefix — a
word the interface does not use for a level of the hierarchy.
"""

from dataclasses import dataclass

from app.api.storages._reads import storage_label_caption


@dataclass
class _Storage:
    name: str
    description: str | None = None


class TestStorageLabelCaption:
    def test_prints_the_description_when_there_is_one(self):
        storage = _Storage(name='Cold Storage A', description='Second door left')
        assert storage_label_caption(storage, True) == 'Second door left'

    def test_falls_back_to_the_name_when_the_description_is_empty(self):
        assert storage_label_caption(_Storage('Cold Storage A', ''), True) == (
            'Cold Storage A'
        )
        assert storage_label_caption(_Storage('Cold Storage A', None), True) == (
            'Cold Storage A'
        )

    def test_prints_nothing_when_the_toggle_is_off(self):
        storage = _Storage(name='Cold Storage A', description='Second door left')
        assert storage_label_caption(storage, False) is None

    def test_never_prefixes_a_word_for_a_level_of_the_hierarchy(self):
        caption = storage_label_caption(_Storage('Cold Storage A'), True)
        assert caption is not None
        assert 'Place' not in caption
