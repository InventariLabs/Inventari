"""Every field a category declares is nameable by the reader.

A category's field definition is the one record the rename refusal reads the
field's name from (`category_system_field_label_locked`). A seeded definition
without a ``label`` — the visibility flag for ``category_id`` was one — made
that refusal print the technical key to a reader who had never seen it.
"""

from app.modules.equipment._module_declarations import build_equipment_metadata


def test_every_declared_category_field_has_a_label() -> None:
    nameless = [
        (category.code, field['key'])
        for category in build_equipment_metadata().categories
        for field in category.field_definitions
        if not field.get('label')
    ]

    assert nameless == []
