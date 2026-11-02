"""Unit tests for template_matcher — no DB, no network required."""

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.recipes.template_matcher import match_templates


def _make_db(templates: list[tuple[uuid.UUID, str]]) -> MagicMock:
    """Return a mock Session whose _fetch_templates returns *templates*."""
    return MagicMock()


ORG_ID = uuid.uuid4()

T1 = uuid.uuid4()
T2 = uuid.uuid4()
T3 = uuid.uuid4()

TEMPLATES = [
    (T1, 'Wołowina mielona kl. I'),
    (T2, 'Cebula biała'),
    (T3, 'Olej rzepakowy'),
]


class _TemplateStub:
    """Minimal duck-typed stand-in for ProductTemplateDTO."""

    def __init__(self, tid: uuid.UUID, name: str) -> None:
        self.id = tid
        self.name = name


class TestMatchTemplates:
    def _patch_fetch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        templates: list[tuple[Any, str]] | None = None,
    ) -> None:
        if templates is None:
            templates = TEMPLATES

        async def fake_fetch(
            self: Any, db: Any, org_id: Any, *, limit: int = 200
        ) -> list[Any]:
            return [_TemplateStub(tid, name) for tid, name in templates]

        monkeypatch.setattr(
            'app.core.public_api.product_templates.CoreProductTemplatesAPI.'
            'list_for_org_with_recipe_usage_async',
            fake_fetch,
        )

    def _patch_llm(self, monkeypatch: pytest.MonkeyPatch, response: Any) -> AsyncMock:
        """Patch the registry-backed LLM helper to return a fixed response.

        Migrated from ``_call_llm_sync`` (legacy) to ``call_llm_async``
        (registry-backed).
        """
        mock = AsyncMock(return_value=response)
        monkeypatch.setattr('app.modules.recipes.template_matcher.call_llm_async', mock)
        return mock

    def _patch_llm_error(
        self, monkeypatch: pytest.MonkeyPatch, exc: Exception
    ) -> AsyncMock:
        mock = AsyncMock(side_effect=exc)
        monkeypatch.setattr('app.modules.recipes.template_matcher.call_llm_async', mock)
        return mock

    @pytest.mark.asyncio
    async def test_successful_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_fetch(monkeypatch)
        llm_response = json.dumps(
            {
                'matches': [
                    {'index': 0, 'template_id': str(T1)},
                    {'index': 1, 'template_id': str(T2)},
                    {'index': 2, 'template_id': str(T3)},
                ]
            }
        )
        self._patch_llm(monkeypatch, llm_response)
        db = MagicMock()
        results = await match_templates(db, ORG_ID, ['wołowina', 'cebula', 'olej'])
        assert len(results) == 3
        assert results[0].template_id == T1
        assert results[1].template_id == T2
        assert results[2].template_id == T3

    @pytest.mark.asyncio
    async def test_match_survives_a_fenced_reply_with_commentary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_fetch(monkeypatch)
        payload = json.dumps(
            {
                'matches': [
                    {'index': 0, 'template_id': str(T1)},
                    {'index': 1, 'template_id': str(T2)},
                    {'index': 2, 'template_id': None},
                ]
            }
        )
        llm_response = (
            'Matching the ingredients to your catalogue:\n'
            f'```json\n{payload}\n```\n'
            'The third one has no obvious match.'
        )
        self._patch_llm(monkeypatch, llm_response)
        db = MagicMock()
        results = await match_templates(db, ORG_ID, ['wołowina', 'cebula', 'sól'])
        assert results[0].template_id == T1
        assert results[1].template_id == T2
        assert results[2].template_id is None

    @pytest.mark.asyncio
    async def test_partial_match_null_for_unmatched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_fetch(monkeypatch)
        llm_response = json.dumps(
            {
                'matches': [
                    {'index': 0, 'template_id': str(T1)},
                    {'index': 1, 'template_id': None},
                    {'index': 2, 'template_id': None},
                ]
            }
        )
        self._patch_llm(monkeypatch, llm_response)
        db = MagicMock()
        results = await match_templates(
            db, ORG_ID, ['wołowina', 'czosnek', 'szczypta soli']
        )
        assert results[0].template_id == T1
        assert results[1].template_id is None
        assert results[2].template_id is None

    @pytest.mark.asyncio
    async def test_empty_templates_returns_all_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(
            self: Any, db: Any, org_id: Any, *, limit: int = 200
        ) -> list[Any]:
            return []

        monkeypatch.setattr(
            'app.core.public_api.product_templates.CoreProductTemplatesAPI.'
            'list_for_org_with_recipe_usage_async',
            fake_fetch,
        )
        db = MagicMock()
        results = await match_templates(db, ORG_ID, ['wołowina', 'cebula'])
        assert all(r.template_id is None for r in results)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_empty_group_names_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_fetch(monkeypatch)
        db = MagicMock()
        results = await match_templates(db, ORG_ID, [])
        assert results == []

    @pytest.mark.asyncio
    async def test_llm_error_returns_all_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_fetch(monkeypatch)
        self._patch_llm_error(monkeypatch, RuntimeError('LLM unavailable'))
        db = MagicMock()
        results = await match_templates(db, ORG_ID, ['wołowina', 'cebula'])
        assert all(r.template_id is None for r in results)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_llm_invalid_json_returns_all_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_fetch(monkeypatch)
        self._patch_llm(monkeypatch, 'not json')
        db = MagicMock()
        results = await match_templates(db, ORG_ID, ['wołowina'])
        assert results[0].template_id is None

    @pytest.mark.asyncio
    async def test_llm_returns_fake_uuid_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_fetch(monkeypatch)
        fake_uuid = str(uuid.uuid4())  # not in TEMPLATES
        self._patch_llm(
            monkeypatch,
            json.dumps({'matches': [{'index': 0, 'template_id': fake_uuid}]}),
        )
        db = MagicMock()
        results = await match_templates(db, ORG_ID, ['wołowina'])
        # UUID not in valid_ids → rejected → None
        assert results[0].template_id is None

    @pytest.mark.asyncio
    async def test_result_order_matches_input(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_fetch(monkeypatch)
        # LLM returns in reverse order
        llm_response = json.dumps(
            {
                'matches': [
                    {'index': 0, 'template_id': str(T3)},
                    {'index': 1, 'template_id': str(T2)},
                    {'index': 2, 'template_id': str(T1)},
                ]
            }
        )
        self._patch_llm(monkeypatch, llm_response)
        db = MagicMock()
        results = await match_templates(db, ORG_ID, ['olej', 'cebula', 'wołowina'])
        assert results[0].template_id == T3
        assert results[1].template_id == T2
        assert results[2].template_id == T1

    @pytest.mark.asyncio
    async def test_markdown_fence_stripped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_fetch(monkeypatch)
        llm_response = (
            '```json\n'
            + json.dumps({'matches': [{'index': 0, 'template_id': str(T1)}]})
            + '\n```'
        )
        self._patch_llm(monkeypatch, llm_response)
        db = MagicMock()
        results = await match_templates(db, ORG_ID, ['wołowina'])
        assert results[0].template_id == T1
