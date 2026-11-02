"""The backend test guide lists the markers pytest registers — all of them.

`pytest.ini` runs with ``--strict-markers``, so a marker it does not register
fails the run, and one it registers but the guide leaves out is a marker a
contributor never hears of. The guide listed three of the five
(``async_db`` and ``module`` were missing) — the kind of list that is copied
from the code once and never compared again. This holds the guide's
"Test Markers" section to the ``markers`` entry of ``pytest.ini``.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]


def _registered() -> set[str]:
    config = configparser.ConfigParser()
    config.read(_BACKEND / 'pytest.ini')
    lines = config['pytest']['markers'].strip().splitlines()
    return {line.split(':', 1)[0].strip() for line in lines if line.strip()}


def _in_the_guide() -> set[str]:
    guide = (_BACKEND / 'tests' / 'README.md').read_text(encoding='utf-8')
    section = guide.split('## Test Markers', 1)[1].split('\n## ', 1)[0]
    return set(re.findall(r'@pytest\.mark\.(\w+)', section))


def test_the_guide_lists_exactly_the_registered_markers() -> None:
    registered = _registered()
    assert registered, 'pytest.ini registers no markers — the reader is wrong'
    named = _in_the_guide()
    assert named == registered, (
        f'tests/README.md "Test Markers" names {sorted(named)}; '
        f'pytest.ini registers {sorted(registered)}'
    )
