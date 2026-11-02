"""Unit tests for app.core.llm.purpose_registry.

The purpose registry is the module-extensibility surface for AI
features: every module that wants to consume an LLM registers a
``AiPurposeSpec`` at module-load time, and the registry resolver
(:func:`app.core.llm.registry.get_client_for_purpose`) asks the
registry which spec matches a purpose key.

Critical contract: the registry keys are GLOBALLY unique. Two modules
must not register the same key — even across reloads, to keep failure
modes loud rather than silently-shadowing-each-other. The test
``test_register_duplicate_raises`` pins this.
"""

from __future__ import annotations

import pytest

from app.core.llm.enums import LlmCapability


@pytest.fixture
def fresh_registry(monkeypatch):
    """Reset the registry between tests so registrations from one
    test do not leak into the next. The registry uses a module-level
    dict; monkeypatch.setattr restores it."""
    from app.core.llm import purpose_registry

    monkeypatch.setattr(purpose_registry, '_PURPOSES', {})


class TestRegisterAiPurpose:
    def test_register_succeeds(self, fresh_registry):
        from app.core.llm.purpose_registry import (
            AiPurposeSpec,
            all_purposes,
            register_ai_purpose,
        )

        spec = AiPurposeSpec(
            key='vision.extract',
            capability=LlmCapability.VISION,
            label_key='vision:ai.purposeLabel',
            description_key='vision:ai.purposeDesc',
            owner_module='vision',
        )
        register_ai_purpose(spec)
        keys = {p.key for p in all_purposes()}
        assert 'vision.extract' in keys

    def test_register_duplicate_raises(self, fresh_registry):
        """Same key registered twice (by accident, or by importing
        two modules that ship overlapping defaults) must fail loudly.
        Silent overwrite is a footgun: feature flags start landing
        in the wrong module's binding slot."""
        from app.core.llm.purpose_registry import (
            AiPurposeSpec,
            register_ai_purpose,
        )

        register_ai_purpose(
            AiPurposeSpec(
                key='vision.extract',
                capability=LlmCapability.VISION,
                label_key='x',
                description_key='y',
                owner_module='vision',
            )
        )
        with pytest.raises(RuntimeError) as exc_info:
            register_ai_purpose(
                AiPurposeSpec(
                    key='vision.extract',
                    capability=LlmCapability.VISION,
                    label_key='x2',
                    description_key='y2',
                    owner_module='recipes',  # different module, same key
                )
            )
        # Error must name BOTH conflicting parties for fast debugging.
        msg = str(exc_info.value)
        assert 'vision.extract' in msg
        assert 'vision' in msg  # first owner
        assert 'recipes' in msg  # would-be second owner

    def test_register_distinct_keys_succeeds(self, fresh_registry):
        from app.core.llm.purpose_registry import (
            AiPurposeSpec,
            all_purposes,
            register_ai_purpose,
        )

        register_ai_purpose(
            AiPurposeSpec(
                key='vision.extract',
                capability=LlmCapability.VISION,
                label_key='x',
                description_key='y',
                owner_module='vision',
            )
        )
        # Different key — fine.
        register_ai_purpose(
            AiPurposeSpec(
                key='recipes.text_parse',
                capability=LlmCapability.TEXT,
                label_key='x',
                description_key='y',
                owner_module='recipes',
            )
        )
        purposes = all_purposes()
        purpose_keys = {p.key for p in purposes}
        assert 'vision.extract' in purpose_keys
        assert 'recipes.text_parse' in purpose_keys

    def test_register_same_spec_is_idempotent(self, fresh_registry):
        """pytest workers and test reordering can re-import a module
        twice. Re-registration with the SAME spec must be silent — only
        a true conflict (different module, same key) raises."""
        from app.core.llm.purpose_registry import (
            AiPurposeSpec,
            register_ai_purpose,
        )

        spec = AiPurposeSpec(
            key='vision.extract',
            capability=LlmCapability.VISION,
            label_key='x',
            description_key='y',
            owner_module='vision',
        )
        register_ai_purpose(spec)
        # Re-import — must not raise.
        register_ai_purpose(spec)


class TestAllPurposes:
    def test_returns_all_registered(self, fresh_registry):
        from app.core.llm.purpose_registry import (
            AiPurposeSpec,
            all_purposes,
            register_ai_purpose,
        )

        # Empty registry
        assert all_purposes() == []

        spec_a = AiPurposeSpec(
            key='a',
            capability=LlmCapability.VISION,
            label_key='l',
            description_key='d',
            owner_module='m1',
        )
        spec_b = AiPurposeSpec(
            key='b',
            capability=LlmCapability.TEXT,
            label_key='l',
            description_key='d',
            owner_module='m2',
        )
        register_ai_purpose(spec_a)
        register_ai_purpose(spec_b)

        result = all_purposes()
        keys = {p.key for p in result}
        assert keys == {'a', 'b'}

    def test_returns_list_not_view(self, fresh_registry):
        """Must be a fresh list — mutating it must not affect the
        registry's internal state."""
        from app.core.llm.purpose_registry import (
            AiPurposeSpec,
            all_purposes,
            register_ai_purpose,
        )

        register_ai_purpose(
            AiPurposeSpec(
                key='x',
                capability=LlmCapability.TEXT,
                label_key='l',
                description_key='d',
                owner_module='m',
            )
        )
        snapshot = all_purposes()
        snapshot.clear()
        # Internal registry still has the entry.
        assert len(all_purposes()) == 1


class TestGetPurpose:
    def test_returns_spec(self, fresh_registry):
        from app.core.llm.purpose_registry import (
            AiPurposeSpec,
            get_purpose,
            register_ai_purpose,
        )

        spec = AiPurposeSpec(
            key='vision.extract',
            capability=LlmCapability.VISION,
            label_key='l',
            description_key='d',
            owner_module='vision',
        )
        register_ai_purpose(spec)
        assert get_purpose('vision.extract') is spec

    def test_returns_none_for_missing_key(self, fresh_registry):
        from app.core.llm.purpose_registry import get_purpose

        assert get_purpose('does.not.exist') is None


class TestAiPurposeSpecFrozen:
    """The spec is frozen: a registered purpose must not be
    silently mutable by callers — that would let a tenant's
    binding attach to a tampered spec."""

    def test_dataclass_is_frozen(self):
        from app.core.llm.purpose_registry import AiPurposeSpec

        with pytest.raises((AttributeError, Exception)):
            spec = AiPurposeSpec(
                key='x',
                capability=LlmCapability.TEXT,
                label_key='l',
                description_key='d',
                owner_module='m',
            )
            spec.key = 'y'  # type: ignore[misc]
