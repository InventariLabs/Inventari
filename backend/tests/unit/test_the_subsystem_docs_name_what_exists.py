"""The subsystem documents name files, links and lists that still exist.

A pass over the thirteen documents of the remaining subsystems (approvals,
audit, analytics, file storage, the LLM layer, Vision AI, the maker, printing,
roles, scan, webhooks) found the same two kinds of drift more than once: a
path or link that a rename left behind (``documents`` for the warehouse, a
migration that moved to the archive) and a table copied from the code once and
never compared again (the stats endpoints, the provider list). Both are cheap
to hold mechanically:

* every backticked repository path and every relative link resolves, and a
  link's ``#anchor`` is a heading of its target;
* the stats endpoint table is the stats router's route list, and the provider
  table in ``LLM.md`` is the ``LlmProvider`` enum.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_SUBSYSTEM_DOCS = (
    'docs/subsystems/ANALYTICS.md',
    'docs/subsystems/APPROVALS.md',
    'docs/subsystems/AUDIT.md',
    'docs/subsystems/FILE_STORAGE.md',
    'backend/app/core/file_storage/README.md',
    'docs/subsystems/LLM.md',
    'docs/subsystems/VISION_AI.md',
    'docs/subsystems/MAKER.md',
    'docs/subsystems/PRINTING.md',
    'docs/subsystems/ROLES.md',
    'docs/subsystems/SCAN.md',
    'docs/subsystems/WEBHOOKS.md',
    'docs/subsystems/WEBHOOKS_TESTING.md',
    'docs/subsystems/STOCK.md',
    'docs/subsystems/VALUATION.md',
    'docs/subsystems/UOM.md',
    'docs/subsystems/STORAGE_TREE_INTEGRITY.md',
    'docs/subsystems/PAGINATION.md',
    'docs/subsystems/MIGRATION_OWNERSHIP.md',
    'docs/subsystems/CORE_API.md',
    'docs/subsystems/CONTRACTS_STABILITY.md',
    'docs/subsystems/CROSS_MODULE_EXTENSION.md',
    'docs/subsystems/EVENTS.md',
)

_BACKTICKED = re.compile(r'`([^`\n]+)`')
_REPO_PATH = re.compile(r'^(?:backend|frontend|docs)/[A-Za-z0-9_./-]+$')
_BACKEND_PATH = re.compile(r'^app/[A-Za-z0-9_./-]+\.(?:py|md|sh|json)$')
_LINK = re.compile(r'\]\(([^)\s]+)\)')


def _text(relative: str) -> str:
    path = _REPO_ROOT / relative
    if not path.is_file():
        pytest.skip(f'{relative} is not part of this checkout')
    return path.read_text(encoding='utf-8')


def _anchors(markdown: str) -> set[str]:
    """GitHub's heading slugs: lower case, punctuation dropped, spaces to dashes."""
    slugs = set()
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', markdown, flags=re.M):
        plain = re.sub(r'[`*_]', '', heading).strip().lower()
        slugs.add(re.sub(r'\s', '-', re.sub(r'[^\w\s-]', '', plain)))
    return slugs


@pytest.mark.parametrize('doc', _SUBSYSTEM_DOCS)
def test_every_repository_path_a_document_names_exists(doc: str) -> None:
    missing = sorted(
        {
            token.rstrip('/')
            for token in _BACKTICKED.findall(_text(doc))
            if _REPO_PATH.match(token) and not (_REPO_ROOT / token.rstrip('/')).exists()
        }
    )

    assert not missing, f'{doc} names paths that do not exist: {missing}'


@pytest.mark.parametrize('doc', _SUBSYSTEM_DOCS)
def test_every_backend_relative_path_a_document_names_exists(doc: str) -> None:
    """The stock and contract documents write ``app/...`` for ``backend/app/...``."""
    missing = sorted(
        {
            token
            for token in _BACKTICKED.findall(_text(doc))
            if _BACKEND_PATH.match(token)
            and not (_REPO_ROOT / 'backend' / token).exists()
        }
    )

    assert not missing, f'{doc} names backend paths that do not exist: {missing}'


@pytest.mark.parametrize('doc', _SUBSYSTEM_DOCS)
def test_every_relative_link_resolves_and_its_anchor_is_a_heading(doc: str) -> None:
    source = _REPO_ROOT / doc
    broken: list[str] = []
    for target in _LINK.findall(_text(doc)):
        if re.match(r'^(?:[a-z][a-z0-9+.-]*:|#)', target, flags=re.I):
            continue
        file_part, _, anchor = target.partition('#')
        resolved = (source.parent / file_part).resolve()
        if not resolved.exists():
            broken.append(target)
        elif anchor and resolved.suffix == '.md':
            if anchor not in _anchors(resolved.read_text(encoding='utf-8')):
                broken.append(target)

    assert not broken, f'{doc} links to places that are not there: {broken}'


def test_the_stats_endpoint_table_is_the_stats_router() -> None:
    from app.modules.stats.router import router

    in_code = {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, 'methods', ())
        if method != 'HEAD'
    }
    prefix = '/api/v1/stats'
    in_code = {(m, p if p.startswith(prefix) else prefix + p) for m, p in in_code}
    in_doc = {
        (method, path)
        for method, path in re.findall(
            r'^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`',
            _text('docs/subsystems/ANALYTICS.md'),
            flags=re.M,
        )
    }

    assert in_doc == in_code


def test_the_llm_provider_table_is_the_provider_enum() -> None:
    from app.core.llm.enums import LlmProvider, protocol_for

    in_code = {p.value for p in LlmProvider if protocol_for(p.value) is not None}
    in_doc = set(
        re.findall(
            r'^\|[^|]+\|\s*`([a-z_]+)`\s*\|\s*(?:Anthropic|Google|OpenAI-compatible)\s*\|',
            _text('docs/subsystems/LLM.md'),
            flags=re.M,
        )
    )

    assert in_doc == in_code


def test_the_entry_vector_table_names_every_warehouse_registration() -> None:
    """A new ``warehouse_api.register_*`` door is a new entry vector (a table once
    copied from the code and never compared again)."""
    from app.modules.warehouse.warehouse_api import WarehouseAPI

    in_code = {
        name
        for name in vars(WarehouseAPI)
        if name.startswith('register_') and callable(getattr(WarehouseAPI, name))
    }
    text = _text('docs/subsystems/CONTRACTS_STABILITY.md')
    in_doc = set(re.findall(r'`warehouse_api\.(register_[a-z_]+)`', text))

    assert in_code
    assert in_code <= in_doc, (
        f'entry vectors missing from the table: {sorted(in_code - in_doc)}'
    )
