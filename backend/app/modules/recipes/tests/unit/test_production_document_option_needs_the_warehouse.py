"""The option to register production as internal issue documents is a
warehouse concept: the schema says so, and the settings form reads it."""

from app.modules.recipes.module import RecipesModule


def test_production_document_option_names_the_warehouse_as_its_home() -> None:
    schema = RecipesModule().get_settings_schema()
    assert schema is not None
    option = schema['properties']['register_production_as_document']
    assert option['requires_modules'] == ['warehouse']
