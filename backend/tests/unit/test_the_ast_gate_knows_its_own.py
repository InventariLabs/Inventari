"""The core-seam import grant names directories the checkout ships.

Several names in ``TRUSTED_CORE_MODULES`` have no directory behind them —
``core``, ``items``, ``locations``, ``categories``, ``announcements`` are
virtual features of the core. The safety scan handed its ``app.*`` import
grant to any directory carrying one of those names, so a module dropped
into ``app/modules/`` registered cleanly with a forbidden core import
inside, because it called itself ``announcements``. The grant reads the
intersection with the shipped directories: a name earns the right when
this tree carries code behind it.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from app.core import module_safety_analysis
from app.core.module_safety import (
    REPO_SHIPPED_MODULES,
    TRUSTED_CORE_MODULES,
    TRUSTED_SHIPPED_MODULES,
)


def _module_with_forbidden_import(root: Path, name: str) -> Path:
    """A minimal module directory whose one import is a banned core seam."""
    module = root / name
    module.mkdir(parents=True)
    (module / 'service.py').write_text(
        textwrap.dedent(
            """\
            from app.models.item import Item


            def probe():
                return Item
            """
        )
    )
    return module


def _subjects(findings) -> set[str]:
    return {finding.subject for finding in findings}


class TestTheGrantBelongsToShippedDirectories:
    def test_a_dropped_directory_with_a_trusted_name_is_rejected(
        self, tmp_path: Path
    ) -> None:
        # The twin that used to register cleanly: the name comes from the
        # trusted list, and no shipped directory carries it.
        dropped = _module_with_forbidden_import(tmp_path, 'announcements')

        findings = module_safety_analysis.analyze_module_safety(
            dropped, [], use_cache=False
        )

        assert 'app.models.item' in _subjects(findings)

    def test_a_dropped_directory_with_an_unlisted_name_is_rejected(
        self, tmp_path: Path
    ) -> None:
        # The control: identical bytes under a name no list knows. Both
        # twins must read the same way.
        dropped = _module_with_forbidden_import(tmp_path, 'probe_drop')

        findings = module_safety_analysis.analyze_module_safety(
            dropped, [], use_cache=False
        )

        assert 'app.models.item' in _subjects(findings)

    def test_a_shipped_module_reaches_the_seams_it_always_reached(self) -> None:
        # The positive side, on the real tree: documents is shipped and
        # trusted, and its own code imports app.models and app.database in
        # the open — the scan reports none of it.
        documents = (
            Path(module_safety_analysis.__file__).resolve().parent.parent
            / 'modules'
            / 'warehouse'
        )

        findings = module_safety_analysis.analyze_module_safety(
            documents, [], use_cache=False
        )

        assert not [
            f
            for f in findings
            if f.kind == 'forbidden_import' and f.subject.startswith('app.')
        ], 'the checkout warehouse module keeps its core-seam grant'


class TestTheGrantSetNamesRealDirectories:
    def test_the_names_no_directory_backs_carry_no_grant(self) -> None:
        # Exactly the claims a dropped directory could make for free.
        for ghost in ('core', 'items', 'locations', 'categories', 'announcements'):
            assert ghost in TRUSTED_CORE_MODULES, f'{ghost} is a trusted name'
            assert ghost not in REPO_SHIPPED_MODULES, f'{ghost} ships no directory'
            assert ghost not in TRUSTED_SHIPPED_MODULES

    def test_shipped_trusted_directories_keep_their_grant(self) -> None:
        assert TRUSTED_SHIPPED_MODULES == TRUSTED_CORE_MODULES & REPO_SHIPPED_MODULES
        for name in (
            'api_keys',
            'warehouse',
            'printing',
            'purchase_orders',
            'recipes',
            'shopping_lists',
            'stats',
            'stock_takes',
            'webhooks',
        ):
            assert name in TRUSTED_SHIPPED_MODULES
