"""The module scan names what it could not read.

Path.rglob does not descend into a symlinked directory and ast.parse
gives up on a file that is not valid Python — both used to end as a
silent ``continue``, so the gate printed "Architecture lint passed" over
a tree whose parts nobody had read. Certification rests on that scan
being exhaustive, so a gap is reported rather than skipped quietly.
Same recipe as ``module validate``: name the gap, keep the
exit code, leave the judgement to the reviewer.
"""

from app.core.architecture_lint._quality_checks_modules import (
    _check_cross_module_imports,
)


def _module(modules_root, name: str):
    module_dir = modules_root / name
    module_dir.mkdir(parents=True)
    (module_dir / '__init__.py').write_text('', encoding='utf-8')
    return module_dir


def test_a_symlinked_subdirectory_is_named_not_skipped(tmp_path):
    modules_root = tmp_path / 'modules'
    stats = _module(modules_root, 'stats')
    outside = tmp_path / 'outside' / 'inner'
    outside.mkdir(parents=True)
    (outside / 'leak.py').write_text(
        'from app.modules.warehouse import services\n', encoding='utf-8'
    )
    (stats / 'linked').symlink_to(outside)

    findings = _check_cross_module_imports(modules_root)

    unread = [f for f in findings if 'not read' in f]
    assert len(unread) == 1
    assert 'stats/linked' in unread[0]
    assert unread[0].startswith('::warning')


def test_a_file_the_parser_cannot_read_is_named(tmp_path):
    modules_root = tmp_path / 'modules'
    stats = _module(modules_root, 'stats')
    (stats / 'broken.py').write_text('def (:\n', encoding='utf-8')

    findings = _check_cross_module_imports(modules_root)

    unread = [f for f in findings if 'not read' in f]
    assert len(unread) == 1
    assert 'broken.py' in unread[0]
    assert unread[0].startswith('::warning')


def test_a_tree_with_nothing_to_report_stays_quiet(tmp_path):
    modules_root = tmp_path / 'modules'
    stats = _module(modules_root, 'stats')
    (stats / 'service.py').write_text('x = 1\n', encoding='utf-8')

    assert _check_cross_module_imports(modules_root) == []


def test_the_gaps_do_not_turn_the_gate_red(tmp_path):
    """A named gap is a report, not a verdict — the exit code is unchanged."""
    modules_root = tmp_path / 'modules'
    stats = _module(modules_root, 'stats')
    (stats / 'broken.py').write_text('def (:\n', encoding='utf-8')

    findings = _check_cross_module_imports(modules_root)

    assert [f for f in findings if f.startswith('::error')] == []


def test_an_unparsable_file_does_not_take_the_gate_down(tmp_path):
    """It used to raise out of the walk: a traceback instead of a report,
    with every check queued behind it left unrun."""
    from app.core.architecture_lint import find_module_boundary_violations

    modules_root = tmp_path / 'modules'
    stats = _module(modules_root, 'stats')
    (stats / 'broken.py').write_text('def (:\n', encoding='utf-8')
    (stats / 'service.py').write_text(
        'from app.models.item import Item\n', encoding='utf-8'
    )

    violations, _ = find_module_boundary_violations(modules_root, baseline_file=None)

    assert [v.import_path for v in violations] == ['app.models.item']


def test_a_link_this_process_cannot_resolve_is_named_too(tmp_path):
    """The container case: the link points at a host path that is not
    mounted here, so is_dir() is False and the gap would vanish from the
    report in the one environment where the gate actually runs."""
    modules_root = tmp_path / 'modules'
    stats = _module(modules_root, 'stats')
    (stats / 'linked').symlink_to(tmp_path / 'nowhere')

    findings = _check_cross_module_imports(modules_root)

    unread = [f for f in findings if 'not read' in f]
    assert len(unread) == 1
    assert 'broken symlink' in unread[0]
