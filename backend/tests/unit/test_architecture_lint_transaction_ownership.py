"""Unit tests for the transaction-ownership gate.

The gate makes two claims. First, in ``app/services``, ``app/core`` and
``app/modules`` the caller owns the transaction: a ``.commit()`` mid-stack
slices the caller's unit of work in two, a ``.rollback()`` erases it, and
neither belongs there. Second, the receiver's variable name is not the
test of ownership — the operation is. ``sess = db; await sess.commit()``
commits exactly like ``await db.commit()``, and the gate that only watches
for the name ``db`` is blind to it.
"""

from __future__ import annotations

from pathlib import Path

from app.core.architecture_lint._quality_checks_transaction_ownership import (
    _check_transaction_ownership,
    _collect_transaction_sites,
)

_ONE_COMMIT = """
async def update_storage(db, item):
    db.add(item)
    await db.commit()
"""

_TWO_COMMITS = """
async def update_storage(db, item):
    db.add(item)
    await db.commit()
    await db.flush()
    await db.commit()
"""

_ALIAS_RECEIVER = """
async def delete_storage(db, item):
    sess = db
    await sess.commit()
"""

_SELF_RECEIVER = """
class ThingCleaner:
    async def purge(self, item):
        await self._db.commit()
"""

_ONE_ROLLBACK = """
async def rebuild(db):
    await db.rollback()
"""

_ALLOWLISTED = """
async def run_background_job(db):
    await db.commit()
    await db.rollback()
"""

_PROSE_ONLY = '''
async def explain(db):
    """The caller runs db.commit() once, on success."""
    # a comment may name await db.rollback() too
    return "db.commit() and db.rollback() are prose here"
'''


def _tree(tmp_path: Path, source: str, name: str = 'things.py') -> Path:
    app_root = tmp_path / 'app'
    (app_root / 'services').mkdir(parents=True, exist_ok=True)
    (app_root / 'services' / name).write_text(source, encoding='utf-8')
    return app_root


def _check(root: Path, **kwargs) -> tuple[list[str], list[str]]:
    kwargs.setdefault('commit_baseline', set())
    kwargs.setdefault('rollback_baseline', set())
    kwargs.setdefault('owner_allowlist', set())
    return _check_transaction_ownership([root], **kwargs)


class TestWhatIsFlagged:
    def test_a_commit_in_a_service_is_an_error(self, tmp_path: Path):
        errors, _ = _check(_tree(tmp_path, _ONE_COMMIT))

        assert len(errors) == 1
        assert errors[0].startswith('::error')
        assert 'commit() inside update_storage' in errors[0]

    def test_a_rollback_in_a_service_is_an_error(self, tmp_path: Path):
        _, rollbacks = _check(_tree(tmp_path, _ONE_ROLLBACK))

        assert len(rollbacks) == 1
        assert rollbacks[0].startswith('::error')
        assert 'rollback() inside rebuild' in rollbacks[0]

    def test_an_aliased_session_is_flagged(self, tmp_path: Path):
        """The measured blind spot: renaming the receiver must not help.

        ``sess = db; await sess.commit()`` was RC=0 under name matching —
        the session is the same object whichever name holds it.
        """
        errors, _ = _check(_tree(tmp_path, _ALIAS_RECEIVER))

        assert len(errors) == 1
        assert errors[0].startswith('::error')
        assert 'sess.commit()' in errors[0]

    def test_a_self_attribute_session_is_flagged(self, tmp_path: Path):
        """``self._db.commit()`` is a commit; the owner list that only
        spelled bare names never saw it."""
        errors, _ = _check(_tree(tmp_path, _SELF_RECEIVER))

        assert len(errors) == 1
        assert 'self._db.commit()' in errors[0]

    def test_a_second_commit_in_a_baselined_function_is_an_error(self, tmp_path: Path):
        """The baseline covers sites, not functions: a second commit next
        to a baselined one is a new site nothing has accepted."""
        root = _tree(tmp_path, _TWO_COMMITS)

        findings, _ = _check(
            root, commit_baseline={'services/things.py::update_storage@1'}
        )

        new_errors = [f for f in findings if f.startswith('::error')]
        assert len(new_errors) == 1
        assert 'update_storage' in new_errors[0]
        assert 'things.py:6' in new_errors[0]


class TestWhatIsNot:
    def test_an_allowlisted_owner_is_silent(self, tmp_path: Path):
        root = _tree(tmp_path, _ALLOWLISTED)

        errors, rollbacks = _check(
            root,
            owner_allowlist={'services/things.py::run_background_job'},
        )

        assert errors == []
        assert rollbacks == []

    def test_a_baselined_commit_is_a_notice(self, tmp_path: Path):
        root = _tree(tmp_path, _ONE_COMMIT)

        errors, _ = _check(
            root, commit_baseline={'services/things.py::update_storage@1'}
        )

        assert len(errors) == 1
        assert errors[0].startswith('::notice')

    def test_a_baselined_rollback_is_a_notice(self, tmp_path: Path):
        root = _tree(tmp_path, _ONE_ROLLBACK)

        _, rollbacks = _check(root, rollback_baseline={'services/things.py::rebuild@1'})

        assert len(rollbacks) == 1
        assert rollbacks[0].startswith('::notice')

    def test_commit_named_in_prose_is_not_a_transaction(self, tmp_path: Path):
        errors, rollbacks = _check(_tree(tmp_path, _PROSE_ONLY))

        assert errors == []
        assert rollbacks == []

    def test_a_test_file(self, tmp_path: Path):
        app_root = tmp_path / 'app'
        (app_root / 'services' / 'tests').mkdir(parents=True)
        (app_root / 'services' / 'tests' / 'test_things.py').write_text(
            _ONE_COMMIT, encoding='utf-8'
        )

        errors, _ = _check(app_root)

        assert errors == []


class TestTheKey:
    def test_the_key_survives_the_lines_moving(self, tmp_path: Path):
        root = _tree(tmp_path, _ONE_COMMIT)
        (key,) = (s.key for s in _collect_transaction_sites([root]) if s.op == 'commit')

        moved = _tree(
            tmp_path / 'moved', '# a new import\n# and a comment\n' + _ONE_COMMIT
        )

        errors, _ = _check(moved, commit_baseline={key})

        assert errors[0].startswith('::notice')

    def test_two_sites_in_one_function_get_two_keys(self, tmp_path: Path):
        root = _tree(tmp_path, _TWO_COMMITS)

        keys = sorted(
            s.key for s in _collect_transaction_sites([root]) if s.op == 'commit'
        )

        assert keys == [
            'services/things.py::update_storage@1',
            'services/things.py::update_storage@2',
        ]
