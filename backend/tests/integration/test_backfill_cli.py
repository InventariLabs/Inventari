"""Integration tests for ``app.cli.backfill_category_emoji``."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.cli.commands_backfill import backfill_category_emoji_impl
from app.models.category import Category
from app.services.category_emoji import (
    LAST_RESORT_EMOJI,
    resolve_category_emoji_with_layer,
)


def _make_category(session, organization_id: uuid.UUID, **kwargs) -> Category:
    cat = Category(
        organization_id=organization_id,
        module_name=None,
        field_definitions=[],
        **kwargs,
    )
    session.add(cat)
    session.flush()
    return cat


def _make_org(session) -> uuid.UUID:
    """Create a throwaway test org so we can scope the backfill queries.

    The function-level backfill iterates ``Category.emoji IS NULL`` across
    the WHOLE table, so tests need to assert relative deltas (what their
    own categories look like) rather than absolute counts.
    """
    from app.models.organization import Organization

    org = Organization(name=f'_test_{uuid.uuid4().hex[:8]}')
    session.add(org)
    session.flush()
    return org.id


def _count_for_org(session, org_id: uuid.UUID) -> int:
    return session.scalar(
        select(Category.id).where(Category.organization_id == org_id)
    ).all() and len(
        session.scalars(
            select(Category).where(Category.organization_id == org_id)
        ).all()
    )


@pytest.mark.integration
class TestResolveWithLayer:
    """The ``_with_layer`` variant must return the same glyph as the
    plain resolver, plus an integer 1..4 identifying the layer that
    produced the result.
    """

    def test_layer_1_user_override(self):
        result, layer = resolve_category_emoji_with_layer(emoji='🐔', name='Eggs')
        assert result == '🐔'
        assert layer == 1

    def test_layer_2_keyword_match(self):
        result, layer = resolve_category_emoji_with_layer(name='Fresh Eggs')
        assert result == '🥚'
        assert layer == 2

    def test_layer_3_vertical_default(self):
        result, layer = resolve_category_emoji_with_layer(
            name='Xylophone', context_tag='equipment'
        )
        assert result == '💻'
        assert layer == 3

    def test_layer_4_last_resort(self):
        result, layer = resolve_category_emoji_with_layer(
            name='Zzzqwertyuiop', context_tag=None
        )
        assert result == LAST_RESORT_EMOJI
        assert layer == 4

    def test_backward_compat_plain_resolver(self):
        """The plain ``resolve_category_emoji`` must still return the same
        glyph (without the layer info) so existing call sites are not
        affected by the new variant.
        """
        from app.services.category_emoji import resolve_category_emoji

        assert resolve_category_emoji(name='Fresh Eggs') == '🥚'
        assert resolve_category_emoji(emoji='🐔', name='Eggs') == '🐔'


@pytest.mark.integration
class TestBackfillCategoryEmojiImpl:
    """The CLI's backfill function. Tests the dry-run vs apply split,
    the layer-2-only filter, and idempotency.

    Each test scopes its work to a unique throwaway organization so the
    function-level scan (``Category.emoji IS NULL``) does not pick up
    the ~40 seeded food + 8 equipment categories. We assert the
    *delta* on the test org, not the absolute count.
    """

    def test_dry_run_does_not_write(self, db_session):
        org_id = _make_org(db_session)
        _make_category(
            db_session, org_id, name='Fresh Eggs', code='eggs', context_tag=None
        )
        _make_category(
            db_session, org_id, name='Zzzqwertyuiop', code=None, context_tag=None
        )
        db_session.commit()

        backfill_category_emoji_impl(db_session, dry_run=True)

        # emoji IS NULL because dry-run, even for the keyword-matched one
        rows = db_session.scalars(
            select(Category).where(Category.organization_id == org_id)
        ).all()
        by_name = {r.name: r.emoji for r in rows}
        assert by_name['Fresh Eggs'] is None
        assert by_name['Zzzqwertyuiop'] is None

    def test_apply_writes_layer2_only(self, db_session):
        org_id = _make_org(db_session)
        _make_category(
            db_session, org_id, name='Fresh Eggs', code=None, context_tag=None
        )
        _make_category(
            db_session, org_id, name='Beef stew', code=None, context_tag=None
        )
        # Vertical default candidate — has context_tag but no keyword match
        _make_category(
            db_session,
            org_id,
            name='Xylophone',
            code=None,
            context_tag='equipment',
        )
        # No match at all — falls through to last resort
        _make_category(
            db_session,
            org_id,
            name='Zzzqwertyuiop',
            code=None,
            context_tag=None,
        )
        db_session.commit()

        backfill_category_emoji_impl(db_session, dry_run=False)

        # Verify the two layer-2 rows were written with the right emoji
        rows = db_session.scalars(
            select(Category).where(Category.organization_id == org_id)
        ).all()
        by_name = {r.name: r.emoji for r in rows}

        assert by_name['Fresh Eggs'] == '🥚'
        assert by_name['Beef stew'] == '🥩'
        # Vertical default + last resort rows are NOT written — the
        # cascade will resolve them on render. Stays dynamic.
        assert by_name['Xylophone'] is None
        assert by_name['Zzzqwertyuiop'] is None

    def test_idempotent_skips_non_null_emoji(self, db_session):
        org_id = _make_org(db_session)
        # Seeded with an explicit user-set emoji (layer 1) — should not
        # be touched, even if the keyword-guess would produce a different
        # result. (We test the filter ``emoji IS NULL``.)
        _make_category(
            db_session, org_id, name='Eggs', code=None, context_tag=None, emoji='🐔'
        )
        # And a layer-2 candidate
        _make_category(
            db_session, org_id, name='Fresh Eggs', code=None, context_tag=None
        )
        db_session.commit()

        backfill_category_emoji_impl(db_session, dry_run=False)

        # The original '🐔' is preserved.
        eggs = db_session.scalars(
            select(Category).where(
                Category.organization_id == org_id, Category.name == 'Eggs'
            )
        ).one()
        assert eggs.emoji == '🐔'

        # And the layer-2 candidate is filled in.
        fresh = db_session.scalars(
            select(Category).where(
                Category.organization_id == org_id, Category.name == 'Fresh Eggs'
            )
        ).one()
        assert fresh.emoji == '🥚'

    def test_skips_empty_name_and_code(self, db_session):
        org_id = _make_org(db_session)
        _make_category(db_session, org_id, name='', code='', context_tag=None)
        db_session.commit()

        backfill_category_emoji_impl(db_session, dry_run=False)

        row = db_session.scalars(
            select(Category).where(
                Category.organization_id == org_id, Category.name == ''
            )
        ).one()
        # Empty input → empty result, no write
        assert row.emoji is None

    def test_keyword_match_via_code(self, db_session):
        org_id = _make_org(db_session)
        # ``name`` empty, ``code`` is "eggs" — Layer 2 should still match
        _make_category(db_session, org_id, name='', code='EGGS', context_tag=None)
        db_session.commit()

        backfill_category_emoji_impl(db_session, dry_run=False)

        row = db_session.scalars(
            select(Category).where(
                Category.organization_id == org_id, Category.code == 'EGGS'
            )
        ).one()
        assert row.emoji == '🥚'

    def test_polish_keyword_match(self, db_session):
        org_id = _make_org(db_session)
        _make_category(
            db_session, org_id, name='Ser żółty', code=None, context_tag=None
        )
        db_session.commit()

        backfill_category_emoji_impl(db_session, dry_run=False)

        row = db_session.scalars(
            select(Category).where(
                Category.organization_id == org_id, Category.name == 'Ser żółty'
            )
        ).one()
        assert row.emoji == '🧀'
