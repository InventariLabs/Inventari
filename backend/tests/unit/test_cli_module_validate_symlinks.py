"""`module validate` must name what it did not read.

``Path.rglob`` does not descend into symlinked directories, so a module
carrying one held files the safety scan never saw — and the validator
answered "clean" over a tree nobody read, which is the report a
certification review is run on. The validator still does not follow the
symlink: following it reads whatever the link names, inside or outside
the module, and that decision belongs to the reviewer. What it must not
do is stay silent — each skipped path is named in the report, and a
tree without symlinks stays quiet. The exit code stays zero: the
report is the certification reviewer's input, while the installer's own
post-copy scan keeps ruling on what actually ships.
"""

import json

import pytest
from typer.testing import CliRunner

from manage import app

runner = CliRunner()


def _module(base, name: str, module_type: str = 'community'):
    mod = base / name
    mod.mkdir(parents=True)
    (mod / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': '1.0.0',
                'module_type': module_type,
                'capabilities': [],
            }
        ),
        encoding='utf-8',
    )
    (mod / 'i18n').mkdir()
    (mod / 'i18n' / 'en.json').write_text('{}', encoding='utf-8')
    return mod


@pytest.mark.unit
class TestModuleValidateNamesSkippedSymlinks:
    def test_a_symlinked_directory_is_named_in_the_report(self, tmp_path):
        """The payload sits outside the tree the scan reads; the report
        must say so instead of answering "clean"."""
        outside = tmp_path / 'outside'
        outside.mkdir()
        (outside / 'deep.py').write_text('import subprocess\n', encoding='utf-8')

        mod = _module(tmp_path, 'probe_mod')
        (mod / 'vendor').symlink_to(outside)

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path)]
        )

        assert result.exit_code == 0, result.output
        assert 'not read' in result.output
        assert 'vendor' in result.output

    def test_a_tree_without_symlinks_stays_quiet(self, tmp_path):
        mod = _module(tmp_path, 'plain_mod')
        (mod / 'sub').mkdir()
        (mod / 'sub' / 'impl.py').write_text('VALUE = 1\n', encoding='utf-8')

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path)]
        )

        assert result.exit_code == 0
        assert 'not read' not in result.output
