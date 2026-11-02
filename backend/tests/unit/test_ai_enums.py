"""Unit tests for app.core.llm.enums.

These are the LLM provider and capability enums. Their string values are
LOAD-BEARING — they are persisted in ``ai_connections.provider`` (varchar
in the DB), surfaced in API responses, and used as defaults in the data
migration. Renaming a value is a breaking change requiring a separate
migration.
"""


class TestLlmProvider:
    """Backend-side string values for each provider.

    Frontend mirrors these in
    ``frontend/src/modules/settings/components/ai/providers.ts`` — keep
    both in sync.
    """

    def test_openrouter_is_default_aggregator(self):
        from app.core.llm.enums import LlmProvider

        assert LlmProvider.OPENROUTER.value == 'openrouter'

    def test_custom_covers_all_openai_compatible_apis(self):
        from app.core.llm.enums import LlmProvider

        # LM Studio, Ollama, vLLM, OpenAI itself all
        # collapse onto ``custom`` with a preset base URL.
        assert LlmProvider.OPENAI_COMPATIBLE.value == 'custom'

    def test_google_renamed_from_google_direct(self):
        from app.core.llm.enums import LlmProvider

        assert LlmProvider.GOOGLE.value == 'google'

    def test_provider_enum_values_are_lowercase(self):
        """DB column is varchar; UI selects by string. Lowercase is the
        convention to keep case-sensitivity out of the picture."""
        from app.core.llm.enums import LlmProvider

        for provider in LlmProvider:
            assert provider.value == provider.value.lower()

    def test_provider_string_roundtrip(self):
        """Storing ``LlmProvider.X.value`` then ``LlmProvider(value)``
        must return the same enum member — used by SQLAlchemy hybrid
        property and Alembic type coercion."""
        from app.core.llm.enums import LlmProvider

        for provider in LlmProvider:
            assert LlmProvider(provider.value) is provider


class TestLlmCapability:
    """Tags describing what a connection can do.

    Future capabilities (embedding, TTS, STT) require no schema change
    — connections store ``capabilities`` as ``list[str]`` JSONB.
    """

    def test_vision_tag(self):
        from app.core.llm.enums import LlmCapability

        assert LlmCapability.VISION.value == 'vision'

    def test_text_tag(self):
        from app.core.llm.enums import LlmCapability

        assert LlmCapability.TEXT.value == 'text'

    def test_capability_string_roundtrip(self):
        from app.core.llm.enums import LlmCapability

        for cap in LlmCapability:
            assert LlmCapability(cap.value) is cap


class TestEnumImportSurface:
    """Sanity checks: the package must re-export both enums from
    app.core.llm, so callers can ``from app.core.llm import LlmProvider``
    without diving into the enums submodule.
    """

    def test_dunder_all_does_not_leak_internal_helpers(self):
        """If non-public helpers are added later, don't auto-export them."""
        from app.core.llm import __all__

        assert set(__all__) >= {'LlmProvider', 'LlmCapability'}
        # and nothing else (yet)
        assert len(__all__) == 2
