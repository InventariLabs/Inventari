"""A module author writing a pre-post check reads the document types from the
guide, not from the warehouse's source (which is outside the import surface).
The guide has to name every type a check can be asked about, and no code the
warehouse does not know."""

import os
import re
from pathlib import Path

from app.modules.warehouse import document_types as dt

_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
_GUIDE = _ROOT / 'docs' / 'subsystems' / 'CROSS_MODULE_EXTENSION.md'

#: Written already posted, so no confirmation or posting ever asks a check.
_NEVER_ASKED = {dt.ADJUSTMENT}


def _documented_types() -> set[str]:
    guide = _GUIDE.read_text(encoding='utf-8')
    start = guide.index('**What `document.type` can be.**')
    section = guide[start : guide.index('**Rules:**', start)]
    return set(re.findall(r'^\| `([A-Z_]+)` \|', section, re.MULTILINE))


def test_the_guide_lists_each_type_a_check_can_be_asked_about() -> None:
    assert _documented_types() == dt.ALL_TYPES - _NEVER_ASKED
