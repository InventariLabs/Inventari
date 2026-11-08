"""``# module_writes:`` lifts the escape hatch's write ban for the module's own tables.

The marker was read as a substring of the file: any occurrence — in a
docstring, naming a Core model, naming nothing — lifted the ban on
``db.add(`` and ``db.delete(`` for the whole file, and nothing checked that
the tables it named were the module's. It now has to be a comment line of
its own, and every name on it has to be a model class (or table name) the
module declares itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.architecture_lint._violations import _check_escape_hatch

_MODELS = """
from app.core.module_sdk import CoreModelBase


class Note(CoreModelBase):
    __tablename__ = 'thing_notes'
"""

_HATCH = """# architecture: allow_direct_db_access
# reason: eager-load the notes with their items for the list view.
{marker}


async def save(db, note):
    db.add(note)
"""


def _module_file(tmp_path: Path, marker: str) -> tuple[Path, str, Path]:
    root = tmp_path / 'modules'
    module = root / 'thing'
    module.mkdir(parents=True)
    (module / 'models.py').write_text(_MODELS, encoding='utf-8')
    source = _HATCH.format(marker=marker)
    service = module / 'service.py'
    service.write_text(source, encoding='utf-8')
    return service, source, root


@pytest.mark.unit
@pytest.mark.parametrize(
    'marker',
    [
        '# module_writes: Note',
        '# module_writes: Note (module-local table)',
        '# module_writes: thing_notes',
    ],
)
def test_a_marker_naming_the_modules_own_table_lifts_the_ban(tmp_path, marker):
    service, source, root = _module_file(tmp_path, marker)

    assert _check_escape_hatch(service, source, root) is not None


@pytest.mark.unit
@pytest.mark.parametrize(
    'marker',
    [
        '# module_writes: Item',
        '# module_writes: Note, Item',
        '# module_writes:',
    ],
    ids=['a-core-model', 'one-foreign-name', 'no-name'],
)
def test_a_marker_naming_anything_else_is_refused(tmp_path, capsys, marker):
    service, source, root = _module_file(tmp_path, marker)

    with pytest.raises(SystemExit):
        _check_escape_hatch(service, source, root)

    assert 'does not own' in capsys.readouterr().out


@pytest.mark.unit
def test_the_marker_inside_a_string_is_not_a_marker(tmp_path, capsys):
    service, source, root = _module_file(
        tmp_path, "NOTE = 'the old # module_writes: Note line'"
    )

    with pytest.raises(SystemExit):
        _check_escape_hatch(service, source, root)

    assert 'write in read-only file' in capsys.readouterr().out
