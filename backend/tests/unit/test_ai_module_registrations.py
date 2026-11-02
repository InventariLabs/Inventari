"""Verify that feature modules register their declared purposes.

Vision and recipes register a purpose each at module-load time. These
tests pin that registration so the resolver
(:func:`app.core.llm.registry.get_client_for_purpose`) has a populated
registry to look up against.

We don't directly call ``vision.module`` or ``recipes.module`` here —
the import statement on first reference runs the module-level
``register_ai_purpose`` call. Subsequent imports are cached by
Python's import system, so the registration runs exactly once per
process.

Why no reset fixture: ``register_ai_purpose`` raises on duplicate.
Keeping registrations process-local matches how the registry is used
in production (modules import once at startup, then lookups forever).
"""


class TestVisionPurpose:
    def test_vision_registers_vision_extract_purpose(self):
        """Module import triggers registration; verify the key is in
        the registry afterwards."""
        import app.modules.vision.module  # noqa: F401  (registration side-effect)
        from app.core.llm.purpose_registry import all_purposes

        keys = {spec.key for spec in all_purposes()}
        assert 'vision.extract' in keys

    def test_vision_extract_spec_attributes(self):
        # If the import side-effect hasn't run yet (this test is run
        # in isolation), trigger it now.
        import app.modules.vision.module  # noqa: F401
        from app.core.llm.enums import LlmCapability
        from app.core.llm.purpose_registry import get_purpose

        spec = get_purpose('vision.extract')
        assert spec is not None
        assert spec.capability == LlmCapability.VISION
        assert spec.owner_module == 'vision'
        # i18n keys have a namespaced convention; pin the surface so
        # a careless refactor surfaces here first.
        assert spec.label_key.startswith('vision:')
        assert spec.description_key.startswith('vision:')


class TestRecipesPurpose:
    def test_recipes_registers_recipes_text_parse_purpose(self):
        import app.modules.recipes.module  # noqa: F401
        from app.core.llm.purpose_registry import all_purposes

        keys = {spec.key for spec in all_purposes()}
        assert 'recipes.text_parse' in keys

    def test_recipes_text_parse_spec_attributes(self):
        import app.modules.recipes.module  # noqa: F401
        from app.core.llm.enums import LlmCapability
        from app.core.llm.purpose_registry import get_purpose

        spec = get_purpose('recipes.text_parse')
        assert spec is not None
        assert spec.capability == LlmCapability.TEXT
        assert spec.owner_module == 'recipes'
        assert spec.label_key.startswith('recipes:')
        assert spec.description_key.startswith('recipes:')
