"""The ratchet on core services importing the ``core_api`` facade.

The facade exists for modules. A service going through it loops back
(``services → core_api → services``) and hides the dependency between two
services behind a middleman, so the places that still do are listed and the
list only shrinks. A new place is refused, and so is an entry whose place
was paid off but left on the list — otherwise the next place would spend
its room unseen.
"""

from pathlib import Path

import pytest

from app.core.architecture_lint._baselines import (
    _load_services_public_api_import_baseline,
)
from app.core.architecture_lint._constants import SERVICES_ROOT, _rel
from app.core.architecture_lint._quality_checks_services_facade import (
    _check_services_facade_imports,
)


def _services(tmp_path: Path, files: dict[str, str]) -> Path:
    """An app root whose ``services/`` holds *files*, written as given."""
    for relative, body in files.items():
        path = tmp_path / 'services' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
    return tmp_path / 'services'


def _errors(findings: list[str]) -> list[str]:
    return [f for f in findings if f.startswith('::error')]


class TestAPlaceNobodyListed:
    @pytest.mark.parametrize(
        ('body', 'what'),
        [
            (
                'from app.core.public_api import core_api\n',
                'from app.core.public_api import core_api',
            ),
            (
                'import app.core.public_api\n',
                'import app.core.public_api',
            ),
            (
                'from app.core.public_api.stock import list_quants_async\n',
                'from app.core.public_api.stock import list_quants_async',
            ),
            (
                'from app.core import public_api\n',
                'from app.core import public_api',
            ),
            (
                'from app.core import public_api as facade\n',
                'from app.core import public_api',
            ),
            (
                'from ..core.public_api import core_api\n',
                'from ..core.public_api import core_api',
            ),
            (
                'async def post_async():\n'
                '    from app.core.public_api import core_api\n',
                'from app.core.public_api import core_api',
            ),
            (
                'async def post_async():\n    from app.core import public_api\n',
                'from app.core import public_api',
            ),
            (
                'async def post_async():\n    from ..core.public_api import core_api\n',
                'from ..core.public_api import core_api',
            ),
        ],
    )
    def test_is_refused_wherever_it_sits(self, tmp_path, body, what):
        """Module level and inside a function alike: also in a function, the
        spelling the import cycle demands today, is still a facade import."""
        root = _services(tmp_path, {'_ops.py': body})

        errors = _errors(_check_services_facade_imports(root))

        assert len(errors) == 1
        assert 'imports ' + what in errors[0]

    def test_a_relative_import_resolves_against_its_own_package(self, tmp_path):
        """One dot more per package below ``app/services``: ``...core`` from
        ``items/`` is the same door as ``..core`` from the root."""
        root = _services(
            tmp_path,
            {
                'items/_ops.py': (
                    'async def post_async():\n'
                    '    from ...core.public_api import core_api\n'
                )
            },
        )

        errors = _errors(_check_services_facade_imports(root))

        assert len(errors) == 1
        assert 'from ...core.public_api import core_api' in errors[0]

    def test_a_method_names_its_class_in_the_key(self, tmp_path):
        root = _services(
            tmp_path,
            {
                '_ops.py': (
                    'class Ops:\n'
                    '    async def post_async(self):\n'
                    '        from app.core.public_api import core_api\n'
                )
            },
        )

        errors = _errors(_check_services_facade_imports(root))

        assert len(errors) == 1
        assert '_ops.py' in errors[0]
        assert '::Ops::post_async imports' in errors[0]

    def test_two_imports_in_one_function_are_one_place(self, tmp_path):
        """The function is on the list to be rewritten as a whole."""
        root = _services(
            tmp_path,
            {
                '_ops.py': (
                    'async def post_async():\n'
                    '    from app.core.public_api import core_api\n'
                    '    from app.core.public_api import core_api\n'
                )
            },
        )

        errors = _errors(_check_services_facade_imports(root))

        assert len(errors) == 1

    def test_the_test_suite_under_services_is_not_the_production_rule(self, tmp_path):
        """A test may use the facade; the loop the rule forbids is production
        code calling a service of its own layer through the middleman."""
        root = _services(
            tmp_path,
            {
                'items/tests/integration/test_flow.py': (
                    'from app.core.public_api import core_api\n'
                ),
                'items/test_helper.py': ('from app.core.public_api import core_api\n'),
            },
        )

        assert _check_services_facade_imports(root) == []

    def test_other_core_doors_stay_open(self, tmp_path):
        """``db_facade`` and contracts are not the facade this rule is about."""
        root = _services(
            tmp_path,
            {
                '_ops.py': (
                    'from app.core import db_facade\n'
                    'from app.core.contracts import events\n'
                )
            },
        )

        assert _check_services_facade_imports(root) == []

    def test_relative_imports_elsewhere_are_not_the_facade(self, tmp_path):
        """The resolution reads the real target: a sibling package, another
        core door and a name from the file's own package stay open."""
        root = _services(
            tmp_path,
            {
                'items/_ops.py': (
                    'from ..schemas import items\n'
                    'from ..core import db_facade\n'
                    'from . import public_api\n'
                    'from .public_api import core_api\n'
                )
            },
        )

        assert _check_services_facade_imports(root) == []


class TestAListedPlace:
    def test_is_a_notice(self, tmp_path):
        root = _services(
            tmp_path,
            {
                '_ops.py': (
                    'async def post_async():\n'
                    '    from app.core.public_api import core_api\n'
                )
            },
        )
        listed = [f'{_rel(root / "_ops.py")}::post_async']

        findings = _check_services_facade_imports(root, listed)

        assert _errors(findings) == []
        assert len(findings) == 1
        assert findings[0].startswith('::notice')

    def test_that_was_paid_off_must_leave_the_list(self, tmp_path):
        """Its room would otherwise be spent by the next place, and no diff
        shows it."""
        root = _services(tmp_path, {'_ops.py': 'async def post_async():\n    pass\n'})
        key = f'{_rel(root / "_ops.py")}::post_async'

        errors = _errors(_check_services_facade_imports(root, [key]))

        assert len(errors) == 1
        assert key in errors[0]
        assert 'Delete the entry' in errors[0]


def test_the_list_describes_the_services_as_they_are():
    """No place imports the facade unlisted, and no listed place is gone."""
    findings = _check_services_facade_imports(
        SERVICES_ROOT, _load_services_public_api_import_baseline()
    )

    assert _errors(findings) == []
