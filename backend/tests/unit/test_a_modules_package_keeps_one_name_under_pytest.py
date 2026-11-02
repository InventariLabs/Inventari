"""A module's package is imported once, under the name the application gave it.

``--import-mode=importlib`` names a package after the ``__init__.py`` files
above it. ``app/`` had none, so pytest called ``app/modules/<name>`` by the name
``modules.<name>`` and, finding no such entry in ``sys.modules``, executed the
package's ``__init__.py`` a second time at the first test's setup. A module
that imports its own ``models.py`` relatively (the scaffold does) then declared
its table twice and every test of the package errored with ``Table ... is
already defined``. The in-tree modules never met it only because they import
their models by absolute name.
"""

from pathlib import Path

import pytest
from _pytest.pathlib import resolve_pkg_root_and_module_name

import app.modules

pytestmark = pytest.mark.unit


def test_pytest_resolves_a_module_package_to_its_application_name():
    package = Path(app.modules.__file__).parent / 'example_widgets' / '__init__.py'

    _, name = resolve_pkg_root_and_module_name(package)

    assert name == 'app.modules.example_widgets'
