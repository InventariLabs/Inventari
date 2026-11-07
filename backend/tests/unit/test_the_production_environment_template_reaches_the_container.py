"""Every variable `.env.production.example` documents reaches the container.

The backend service in `docker-compose.prod.yml` has no `env_file:`, so
compose hands it only the names its `environment:` block interpolates — a name
the block does not carry is a setting that documents itself and does nothing.
That is how `LLM_MODEL` shipped: an operator who set it got the code's default
and no signal, and the comment now inside the block says so.

The example is the field list a self-hoster copies, so this reads both files:
a variable may not be added to one without the other. What a variable then
does with its value is the application's business; that it arrives is the
contract checked here. A variable that is deliberately *not* the operator's to
set is not a line in the example at all — `DEBUG` left for exactly that reason.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: The checkout. `docker-compose.yml` mounts it at `/repo` and names it in
#: `INVENTARI_REPO_ROOT`; on the host it is three levels above this file.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

#: `KEY=` at the start of a line: the example's own entries, not its comments.
_ENTRY = re.compile(r'^([A-Z_]+)=')


def _documented_variables() -> list[str]:
    text = (_REPO_ROOT / '.env.production.example').read_text(encoding='utf-8')
    found: list[str] = []
    for line in text.splitlines():
        match = _ENTRY.match(line)
        if match:
            found.append(match.group(1))
    return found


def _interpolated(name: str, compose: str) -> bool:
    # `${NAME}`, `${NAME:-…}`, `${NAME?…}`, `${NAME-…}` — anything compose
    # would substitute, and nothing that merely starts with the name.
    return re.search(r'\$\{' + re.escape(name) + r'[}\s:?-]', compose) is not None


def test_the_template_is_readable_from_here() -> None:
    # A template this test cannot see would make the check below pass over
    # nothing, so the absence is a failure rather than a skip.
    assert (_REPO_ROOT / '.env.production.example').is_file()
    assert (_REPO_ROOT / 'docker-compose.prod.yml').is_file()


def test_the_module_signing_keys_are_documented_for_the_operator() -> None:
    """A signed install refuses without them, and the refusal is the only place
    an operator would otherwise learn the name. The development example has
    carried the variable since the signing gate was written; a production
    template that omits it is a checklist that stops one line short."""
    assert 'MODULE_SIGNING_PUBLIC_KEYS' in _documented_variables()


def test_the_default_language_is_documented_for_the_operator() -> None:
    """An instance run for readers of one language wants its new accounts, and
    its answers to a request that names no language, in that language.
    `manage.py user create-admin` without `--lang` promises the account "the
    instance default", which on this stack was English whatever `.env` said:
    the development example carried the variable with a note that no compose
    file forwarded it, and the production template did not name it at all."""
    assert 'DEFAULT_LANGUAGE' in _documented_variables()


def test_every_documented_variable_is_interpolated_by_the_production_stack() -> None:
    compose = (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')
    documented = _documented_variables()

    assert documented, (
        'no KEY= line in .env.production.example — the check below would be '
        'measuring an empty list'
    )
    missing = [name for name in documented if not _interpolated(name, compose)]

    assert not missing, (
        f'{missing} documented in .env.production.example and never interpolated '
        'by docker-compose.prod.yml, which gives the backend no `env_file:` — the '
        'container never sees them. Name them in the environment block, or drop '
        'them from the example and say where they are set instead.'
    )
