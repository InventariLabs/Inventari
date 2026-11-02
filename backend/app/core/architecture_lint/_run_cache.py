"""Let the checks of one lint run share what a collector found.

A baseline's stale-entry check asks the same collectors the checks above it
asked, over the same trees, a few seconds later. Inside ``main`` a collector's
answer is kept and handed to the next caller; outside a run — a test pointing
a collector at a temporary tree it edits between calls — every call reads the
files again. A collector's result is read, never changed, by every caller.

The same holds for a parsed file: two dozen collectors parse the same few
hundred sources, so inside a run ``ast.parse`` hands back the tree it built
for a source the first time and no check rewrites a tree it was given, and
walking a whole module lists its nodes the first time.
"""

from __future__ import annotations

import ast
import contextlib
import contextvars
import functools
from collections.abc import Callable, Iterator
from typing import Any
from unittest import mock

_RUN: contextvars.ContextVar[dict[Any, Any] | None] = contextvars.ContextVar(
    'architecture_lint_run', default=None
)


def _hashable(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return tuple(_hashable(item) for item in value)
    return value


def once_per_run[**P, R](collector: Callable[P, R]) -> Callable[P, R]:
    """Keep *collector*'s result for the arguments it was called with, for one run."""

    @functools.wraps(collector)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        run = _RUN.get()
        if run is None:
            return collector(*args, **kwargs)
        key = (
            collector.__qualname__,
            _hashable(args),
            tuple(sorted(kwargs.items())),
        )
        if key not in run:
            run[key] = collector(*args, **kwargs)
        result: R = run[key]
        return result

    return wrapper


@contextlib.contextmanager
def shared_run() -> Iterator[None]:
    token = _RUN.set({})
    parse = ast.parse
    parsed: dict[tuple[str, str], ast.Module] = {}

    walk = ast.walk
    walked: dict[int, tuple[ast.Module, list[ast.AST]]] = {}

    def parse_once(
        source: str, filename: str = '<unknown>', *args: Any, **kwargs: Any
    ) -> ast.Module:
        if args or kwargs:
            # A caller outside the lint (vulture's scan) with options of its own.
            foreign: ast.Module = parse(source, filename, *args, **kwargs)
            return foreign
        key = (filename, source)
        if key not in parsed:
            parsed[key] = parse(source, filename)
        return parsed[key]

    def walk_once(node: ast.AST) -> Iterator[ast.AST]:
        if not isinstance(node, ast.Module):
            return walk(node)
        if id(node) not in walked:
            # The entry holds the tree, so its id names it for the whole run.
            walked[id(node)] = (node, list(walk(node)))
        return iter(walked[id(node)][1])

    try:
        with (
            mock.patch.object(ast, 'parse', parse_once),
            mock.patch.object(ast, 'walk', walk_once),
        ):
            yield
    finally:
        _RUN.reset(token)
