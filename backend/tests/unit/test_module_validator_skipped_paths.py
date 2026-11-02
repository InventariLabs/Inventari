"""The skipped-path report names exactly what the safety scan cannot see.

``skipped_paths`` used to answer one question too broadly (every symlinked
directory, even one whose content the walk reads at its real path) and one
too narrowly (a dangling link, which ``is_dir`` hides, went unnamed). These
tests pin the three shapes: a link resolved inside the tree is content the
scan already read and is not a hole; a link resolved outside it is unread
content and must be named; a link whose target does not exist is unread
too, and naming it as dangling is the only way the report can say so.
"""

import pytest

from app.cli.module_validator import skipped_paths


@pytest.fixture()
def module_dir(tmp_path):
    root = tmp_path / 'my-module'
    (root / 'backend').mkdir(parents=True)
    (root / 'manifest.json').write_text('{}', encoding='utf-8')
    return root


def test_a_link_resolved_inside_the_tree_is_not_reported_as_skipped(module_dir):
    real = module_dir / 'backend' / 'shared'
    real.mkdir()
    (real / 'helper.py').write_text('X = 1\n', encoding='utf-8')
    link = module_dir / 'alias'
    link.symlink_to(real, target_is_directory=True)

    assert skipped_paths(module_dir) == []


def test_a_link_resolved_outside_the_tree_is_named(module_dir, tmp_path):
    outside = tmp_path / 'elsewhere'
    outside.mkdir()
    (outside / 'secret.py').write_text('X = 1\n', encoding='utf-8')
    link = module_dir / 'vendor'
    link.symlink_to(outside, target_is_directory=True)

    assert skipped_paths(module_dir) == [f'vendor -> {outside}']


def test_a_dangling_link_is_named_as_dangling(module_dir):
    link = module_dir / 'ghost'
    link.symlink_to(module_dir / 'never-existed', target_is_directory=True)

    report = skipped_paths(module_dir)
    assert len(report) == 1
    assert report[0].startswith('ghost -> ')
    assert 'dangling' in report[0]


def test_a_plain_tree_is_never_reported(module_dir):
    deep = module_dir / 'backend' / 'deep'
    deep.mkdir(parents=True)
    (deep / 'code.py').write_text('X = 1\n', encoding='utf-8')

    assert skipped_paths(module_dir) == []
