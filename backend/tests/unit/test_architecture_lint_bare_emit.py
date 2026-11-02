"""Unit tests for the non-transactional emit ratchet.

The gate has one job: notice a call site that is new. That makes two
things worth pinning — what it counts as a call site, and what it uses as
a key. The key is ``path::function::event`` rather than a line number
because the baselined sites live in files that get edited for unrelated
reasons; a line-number key would report a refactor as a new emit and,
worse, would let a genuinely new one hide behind a shifted line.
"""

from __future__ import annotations

from pathlib import Path

from app.core.architecture_lint._quality_checks_events import (
    _check_bare_emit,
    collect_bare_emits,
)

_BARE = """
from app.core.public_api import core_api


async def create_thing(db, payload):
    await db.commit()
    await core_api.events.emit_async('thing.created', payload)
"""

_TRANSACTIONAL = """
from app.core.public_api import core_api


async def create_thing(db, payload):
    await core_api.events.emit_transactional_async(db, 'thing.created', payload)
    await db.commit()
"""

_SYSTEM_EVENT = """
from app.core.events import SystemEvent, event_bus


async def create_thing(db, payload):
    await event_bus.emit(SystemEvent.ITEM_CREATED, payload)
"""


def _tree(tmp_path: Path, relative: str, source: str) -> Path:
    """Write *source* into an app-shaped tree and return its root."""
    app_root = tmp_path / 'app'
    target = app_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding='utf-8')
    return app_root


class TestWhatCounts:
    def test_a_bare_emit_is_found(self, tmp_path: Path):
        app_root = _tree(tmp_path, 'services/thing_service.py', _BARE)

        found = collect_bare_emits(app_root)

        assert len(found) == 1
        assert next(iter(found)).endswith('::create_thing::thing.created')

    def test_emit_transactional_is_not(self, tmp_path: Path):
        app_root = _tree(tmp_path, 'services/thing_service.py', _TRANSACTIONAL)

        assert collect_bare_emits(app_root) == {}

    def test_an_enum_event_is_named_by_its_member(self, tmp_path: Path):
        app_root = _tree(tmp_path, 'services/thing_service.py', _SYSTEM_EVENT)

        assert next(iter(collect_bare_emits(app_root))).endswith(
            '::create_thing::ITEM_CREATED'
        )

    def test_tests_are_not_call_sites(self, tmp_path: Path):
        app_root = _tree(tmp_path, 'services/tests/test_thing.py', _BARE)

        assert collect_bare_emits(app_root) == {}

    def test_the_bus_and_its_facades_are_not_call_sites(self, tmp_path: Path):
        # They forward what a caller asked for; counting them would put the
        # implementation of the contract in the list of its violations.
        app_root = _tree(tmp_path, 'core/events.py', _BARE)

        assert collect_bare_emits(app_root) == {}

    def test_a_tree_that_is_not_scanned_is_left_alone(self, tmp_path: Path):
        app_root = _tree(tmp_path, 'cli/commands_thing.py', _BARE)

        assert collect_bare_emits(app_root) == {}


class TestTheRatchet:
    def test_a_baselined_site_is_a_notice(self, tmp_path: Path):
        app_root = _tree(tmp_path, 'services/thing_service.py', _BARE)
        key = next(iter(collect_bare_emits(app_root)))

        findings = _check_bare_emit(app_root, {key})

        assert len(findings) == 1
        assert findings[0].startswith('::notice')

    def test_a_new_site_is_an_error(self, tmp_path: Path):
        app_root = _tree(tmp_path, 'services/thing_service.py', _BARE)

        findings = _check_bare_emit(app_root, set())

        assert len(findings) == 1
        assert findings[0].startswith('::error')
        assert 'emit_transactional' in findings[0]

    def test_the_key_survives_the_lines_moving(self, tmp_path: Path):
        """A refactor above the call must not read as a new emit."""
        app_root = _tree(tmp_path, 'services/thing_service.py', _BARE)
        key = next(iter(collect_bare_emits(app_root)))

        moved = _tree(
            tmp_path,
            'services/thing_service.py',
            '# a new comment\n# and another\n' + _BARE,
        )

        assert _check_bare_emit(moved, {key})[0].startswith('::notice')

    def test_a_second_event_in_a_baselined_function_is_still_new(self, tmp_path: Path):
        """The event is part of the key, so the function is not a blanket."""
        app_root = _tree(tmp_path, 'services/thing_service.py', _BARE)
        key = next(iter(collect_bare_emits(app_root)))

        both = _tree(
            tmp_path,
            'services/thing_service.py',
            _BARE + "    await core_api.events.emit_async('thing.deleted', payload)\n",
        )

        findings = _check_bare_emit(both, {key})
        errors = [f for f in findings if f.startswith('::error')]
        assert len(errors) == 1
        assert 'thing.deleted' in errors[0]
