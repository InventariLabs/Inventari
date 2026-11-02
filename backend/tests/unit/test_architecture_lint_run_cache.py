"""Inside one lint run the checks share the trees they parse and walk; outside it they do not."""

from __future__ import annotations

import ast

import pytest

from app.core.architecture_lint._run_cache import once_per_run, shared_run

pytestmark = pytest.mark.unit

SOURCE = 'def f(a):\n    return a + 1\n'


def test_a_source_is_parsed_once_per_run() -> None:
    with shared_run():
        assert ast.parse(SOURCE, filename='a.py') is ast.parse(SOURCE, filename='a.py')
        assert ast.parse(SOURCE, filename='a.py') is not ast.parse(
            SOURCE, filename='b.py'
        )
    assert ast.parse(SOURCE) is not ast.parse(SOURCE)


def test_a_shared_walk_visits_the_nodes_in_the_order_ast_walk_does() -> None:
    plain = [type(node) for node in ast.walk(ast.parse(SOURCE))]
    with shared_run():
        tree = ast.parse(SOURCE)
        assert [type(node) for node in ast.walk(tree)] == plain
        assert [type(node) for node in ast.walk(tree)] == plain
        function = tree.body[0]
        assert next(ast.walk(function)) is function


def test_a_parse_with_options_of_its_own_is_not_shared() -> None:
    with shared_run():
        first = ast.parse(SOURCE, filename='a.py', type_comments=True)
        assert first is not ast.parse(SOURCE, filename='a.py', type_comments=True)


def test_the_original_parse_and_walk_are_back_after_the_run() -> None:
    parse, walk = ast.parse, ast.walk
    with shared_run():
        assert ast.parse is not parse
    assert (ast.parse, ast.walk) == (parse, walk)
    with pytest.raises(RuntimeError), shared_run():
        raise RuntimeError
    assert (ast.parse, ast.walk) == (parse, walk)


def test_a_collector_runs_once_per_run_and_every_time_outside_one() -> None:
    calls: list[int] = []

    @once_per_run
    def collect(root: list[str]) -> int:
        calls.append(1)
        return len(calls)

    collect(['x'])
    collect(['x'])
    assert len(calls) == 2
    with shared_run():
        assert collect(['x']) == collect(['x'])
        collect(['y'])
    assert len(calls) == 4
