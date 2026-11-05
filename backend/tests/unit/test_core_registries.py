"""What Core does when the module that owns a capability is not installed.

Three registries invert a Core → module dependency: label rendering (owned by
printing), template ranking (recipes) and API-key resolution (api_keys). Each
one documents a different answer for the unregistered case — raise, degrade,
or no-op — and that answer is the whole contract Core relies on when a
deployment ships without the module.

The registries are process-global, so every test here restores whatever the
imported modules registered at startup.
"""

import uuid

import pytest

from app.core import api_key_auth, label_rendering, template_ranking


class TestLabelRendererRegistry:
    """Absence must fail loudly: a label image cannot be improvised."""

    @pytest.fixture(autouse=True)
    def _empty_registry(self):
        saved = (label_rendering._single, label_rendering._batch)
        label_rendering.clear_label_renderers()
        yield
        if saved[0] is not None and saved[1] is not None:
            label_rendering.register_label_renderers(single=saved[0], batch=saved[1])
        else:
            label_rendering.clear_label_renderers()

    def test_single_render_raises_when_unregistered(self):
        with pytest.raises(label_rendering.LabelRendererUnavailableError):
            label_rendering.render_label_png(object())

    def test_batch_render_raises_when_unregistered(self):
        # Returning empty bytes instead would reach the client as a corrupt
        # image, which is why the callers map this to a 503.
        with pytest.raises(label_rendering.LabelRendererUnavailableError):
            label_rendering.render_label_batch_png([])

    def test_delegates_to_the_registered_renderers(self):
        calls: list[str] = []

        label_rendering.register_label_renderers(
            single=lambda label, **kw: calls.append('single') or b'one',
            batch=lambda labels, **kw: calls.append('batch') or b'sheet',
        )

        assert label_rendering.render_label_png(object()) == b'one'
        assert label_rendering.render_label_batch_png([]) == b'sheet'
        assert calls == ['single', 'batch']


class TestTemplateRankerRegistry:
    """Absence degrades: the caller falls back to alphabetical listing."""

    @pytest.fixture(autouse=True)
    def _empty_registry(self):
        saved = template_ranking._ranker
        template_ranking.clear_template_ranker()
        yield
        if saved is not None:
            template_ranking.register_template_ranker(saved)
        else:
            template_ranking.clear_template_ranker()

    @pytest.mark.asyncio
    async def test_returns_none_when_unregistered(self):
        assert (
            await template_ranking.rank_templates_by_usage(None, uuid.uuid4()) is None
        )

    @pytest.mark.asyncio
    async def test_delegates_to_the_registered_ranker(self):
        org_id = uuid.uuid4()
        seen: list[tuple] = []

        async def ranker(db, org, limit):
            seen.append((db, org, limit))
            return ['template']

        template_ranking.register_template_ranker(ranker)

        assert await template_ranking.rank_templates_by_usage(None, org_id, 5) == [
            'template'
        ]
        assert seen == [(None, org_id, 5)]


class TestApiKeyResolverRegistry:
    """Absence is a no-op: with no api_keys module, no key authenticates."""

    @pytest.fixture(autouse=True)
    def _empty_registry(self):
        saved = api_key_auth._resolver
        api_key_auth.clear_api_key_resolver()
        yield
        if saved is not None:
            api_key_auth.register_api_key_resolver(saved)
        else:
            api_key_auth.clear_api_key_resolver()

    @pytest.mark.asyncio
    async def test_resolves_to_none_when_unregistered(self):
        assert await api_key_auth.resolve_api_key(None, 'inv_whatever') is None

    @pytest.mark.asyncio
    async def test_delegates_to_the_registered_resolver(self):
        user_id = uuid.uuid4()
        identity = api_key_auth.ApiKeyIdentity(
            user_id=user_id, key_prefix='inv_live_b3be8b'
        )

        async def resolver(db, raw_key):
            return identity if raw_key == 'inv_good' else None

        api_key_auth.register_api_key_resolver(resolver)

        assert await api_key_auth.resolve_api_key(None, 'inv_good') == identity
        # The prefix is part of what a key hands back: the journal names the
        # key, not only the account it belongs to.
        assert (await api_key_auth.resolve_api_key(None, 'inv_good')).key_prefix == (
            'inv_live_b3be8b'
        )
        assert await api_key_auth.resolve_api_key(None, 'inv_bad') is None
