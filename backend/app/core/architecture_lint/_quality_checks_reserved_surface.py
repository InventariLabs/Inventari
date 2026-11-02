"""The dead-code whitelist's one unverifiable section, held to a date.

Almost every entry in ``scripts/vulture_whitelist.py`` says "the caller
exists, the scanner cannot see it" -- a claim a grep settles in seconds. One
section says something else: "there is no caller and there is not meant to be
one yet", the module extension surface a community module might one day
import. That claim cannot be checked by grep, which is exactly why it needs
an owner and a date: a silenced name with no caller and no deadline is how a
dead API stays reported as alive.

The section is marked in the file itself, and every name inside it needs a
trailing ``owner=<who> expires=<YYYY-MM-DD> <reason>``.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

#: The whitelist marks the section by hand; everything between these two
#: lines is held to the rule.
_BEGIN = '# --- begin reserved surface'
_END = '# --- end reserved surface'

_MARKER = re.compile(
    r'#\s*owner=(?P<owner>\S+)\s+expires=(?P<expires>\S+)\s+(?P<reason>.+)$'
)


def _check_reserved_surface(
    whitelist_file: Path, today: date | None = None
) -> list[str]:
    """Every silenced name in the reserved section names a who and a when."""
    if not whitelist_file.exists():
        return []

    today = today or date.today()
    rel = f'backend/scripts/{whitelist_file.name}'
    errors: list[str] = []
    inside = False

    for lineno, raw in enumerate(
        whitelist_file.read_text(encoding='utf-8').splitlines(), start=1
    ):
        line = raw.strip()
        if line.startswith(_BEGIN):
            inside = True
            continue
        if line.startswith(_END):
            inside = False
            continue
        if not inside or not line or line.startswith('#'):
            continue

        name = line.split('#')[0].strip()
        marker = _MARKER.search(line)
        if marker is None:
            errors.append(
                f'::error file={rel},line={lineno},title=Architecture: reserved surface without an owner::'
                f"'{name}' is silenced with no caller to point at. Add "
                f'"# owner=<who> expires=<YYYY-MM-DD> <reason>" — a name kept '
                f'on purpose needs somebody who will say when the purpose ended.'
            )
            continue
        try:
            deadline = date.fromisoformat(marker.group('expires'))
        except ValueError:
            errors.append(
                f'::error file={rel},line={lineno},title=Architecture: reserved surface with unreadable expiry::'
                f"'{name}' has expires='{marker.group('expires')}'; expected YYYY-MM-DD."
            )
            continue
        if deadline < today:
            errors.append(
                f'::error file={rel},line={lineno},title=Architecture: reserved surface expired::'
                f"'{name}' expired on {deadline.isoformat()} — "
                f'{marker.group("owner")} was to decide whether anything still '
                f'needs it. Renew the date or delete the name and let vulture speak.'
            )
    return errors
