#!/usr/bin/env python3
"""Gate: comments and docstrings describe the code as it is, not how it got here.

A comment that says "the row used to print eight hex characters" hands the
next reader a defect that no longer exists. What that reader needs is the
constraint the code keeps today; the story of the change -- the defect, its
cause, the fix -- is what the commit message carries, and ``git blame`` leads
there. AGENTS.md, "Comments and docstrings", states the rule; this is the part
that keeps it from eroding.

What is counted: lines of *comments and docstrings* that match a phrase from
``PHRASES`` -- ``used to``, ``previously``, ``formerly``, ``until now``, "the old
code" and their kin. Python is read with ``tokenize`` (comments) and ``ast``
(docstrings); TypeScript with a small scanner that skips string, template and
regular-expression literals. A string literal or an identifier that happens to
contain a phrase is never counted. A bare "no longer" is not a phrase: "a
document that no longer exists" describes the present, and the wording is too
often right to be worth a gate.

The count per file is held against ``history-comments-baseline.json``:

* a file whose count rises above its entry fails, and a file with no entry
  starts at 0, so a new file cannot carry one;
* a file whose count falls passes, with a note to lower the entry --
  ``--write-baseline`` rewrites every entry from the tree, and is the only way
  an entry is ever written.

Scope: ``backend/app``, ``backend/tests``, ``frontend/src`` and
``frontend/tests``, tracked files only. ``--tree backend`` or ``--tree
frontend`` checks one side (``make lint`` and ``make check-frontend`` each run
their own); the baseline holds both.

Standard library only: it runs on the host, where ``make lint`` lives.

    python3 backend/scripts/check_history_comments.py [--tree backend|frontend] [--write-baseline]
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name('history-comments-baseline.json')

TREES: dict[str, tuple[str, ...]] = {
    'backend': ('backend/app', 'backend/tests'),
    'frontend': ('frontend/src', 'frontend/tests'),
}
_EXTENSIONS = {
    'backend': ('.py',),
    'frontend': ('.ts', '.tsx', '.mts', '.js', '.jsx', '.mjs'),
}
_GENERATED = ('frontend/src/types/api-generated.ts', 'frontend/src/types/api-routes.ts')

# "used to" is a narration only as the verb of a subject ("the rule used to
# turn ..."); after a form of "be", a modal or an adverb it is the participle
# ("is used to build the key") and describes the present.
_NOT_BEFORE_USED_TO = (
    'is are be was were been being get gets got not also only then can could may '
    'might will would should must always just here there simply solely merely '
    'again often mostly mainly typically usually'
).split()
_USED_TO = ''.join(rf'(?<!\b{word} )' for word in _NOT_BEFORE_USED_TO) + r'\bused to\b'

PHRASES = re.compile(
    '|'.join(
        (
            _USED_TO,
            r'\bpreviously\b',
            r'\bwas once\b',
            r'\bformerly\b',
            r'\buntil now\b',
            r'\bbefore this (?:change|fix)\b',
            r'\b(?:old|earlier|previous) (?:code|version|behaviou?r|screen|form|query|path)\b',
            r'\bit once\b',
            r'\bthis was the bug\b',
            r'\bregressed\b',
        )
    ),
    re.IGNORECASE,
)


def python_comment_lines(source: str) -> dict[int, str]:
    """Line number -> text, for every comment line and docstring line."""
    lines: dict[int, str] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                lines[token.start[0]] = token.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return lines
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            end = first.end_lineno or first.lineno
            raw = source.splitlines()[first.lineno - 1 : end]
            for offset, text in enumerate(raw):
                lines[first.lineno + offset] = text
    return lines


# After one of these a "/" opens a regular expression rather than dividing.
_REGEX_PRECEDERS = set('(,=:[!&|?{};+-*%<>~^')
_REGEX_KEYWORDS = ('return', 'typeof', 'case', 'in', 'of', 'delete', 'void', 'throw')


class _TypeScriptScanner:
    """Walks TypeScript source once, collecting comment lines.

    A hand scanner rather than a regular expression: a ``//`` inside a string,
    a template or a regular expression is not a comment, and a comment
    containing a quote must not open a string.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self.n = len(source)
        self.i = 0
        self.line = 1
        self.last = ''  # last significant character: tells a regex from a division
        self.last_word = ''
        self.depth = 0  # brace depth
        self.templates: list[int] = []  # brace depth of each open ``${``
        self.comments: dict[int, str] = {}

    def run(self) -> dict[int, str]:
        while self.i < self.n:
            self._step()
        return self.comments

    def _add(self, text: str) -> None:
        for offset, part in enumerate(text.split('\n')):
            at = self.line + offset
            self.comments[at] = self.comments.get(at, '') + part

    def _literal_done(self, end: int) -> None:
        self.i = end
        self.last = '"'
        self.last_word = ''

    def _step(self) -> None:
        c = self.source[self.i]
        nxt = self.source[self.i + 1 : self.i + 2]
        if c == '\n':
            self.line += 1
            self.i += 1
        elif c in ' \t\r':
            self.i += 1
        elif c == '/' and nxt == '/':
            self._line_comment()
        elif c == '/' and nxt == '*':
            self._block_comment()
        elif c in '"\'':
            self._string(c)
        elif c == '`' or (
            c == '}' and self.templates and self.templates[-1] == self.depth
        ):
            self._template(c)
        elif c == '/' and self._regex_allowed():
            self._regex()
        elif c.isalnum() or c in '_$':
            self._word()
        else:
            self.depth += (c == '{') - (c == '}')
            self.last = c
            self.last_word = ''
            self.i += 1

    def _line_comment(self) -> None:
        end = self.source.find('\n', self.i)
        end = self.n if end == -1 else end
        self._add(self.source[self.i : end])
        self.i = end

    def _block_comment(self) -> None:
        end = self.source.find('*/', self.i + 2)
        end = self.n if end == -1 else end + 2
        self._add(self.source[self.i : end])
        self.line += self.source.count('\n', self.i, end)
        self.i = end

    def _string(self, quote: str) -> None:
        j = self.i + 1
        while j < self.n and self.source[j] not in (quote, '\n'):
            j += 2 if self.source[j] == '\\' else 1
        self._literal_done(j + 1)

    def _template(self, opener: str) -> None:
        if opener == '}':
            self.templates.pop()
        j = self.i + 1
        while j < self.n and self.source[j] != '`':
            if self.source[j] == '\\':
                j += 2
                continue
            if self.source[j : j + 2] == '${':
                self.templates.append(self.depth)
                self.i = j + 2
                self.last = '{'
                self.last_word = ''
                return
            if self.source[j] == '\n':
                self.line += 1
            j += 1
        self._literal_done(j + 1)

    def _regex_allowed(self) -> bool:
        return (
            self.last in _REGEX_PRECEDERS
            or self.last == ''
            or self.last_word in _REGEX_KEYWORDS
        )

    def _regex(self) -> None:
        j = self.i + 1
        in_class = False
        while j < self.n and self.source[j] != '\n':
            char = self.source[j]
            if char == '\\':
                j += 2
                continue
            if char == '[':
                in_class = True
            elif char == ']':
                in_class = False
            elif char == '/' and not in_class:
                break
            j += 1
        self._literal_done(j + 1)

    def _word(self) -> None:
        j = self.i
        while j < self.n and (self.source[j].isalnum() or self.source[j] in '_$'):
            j += 1
        self.last_word = self.source[self.i : j]
        self.last = 'a'
        self.i = j


def typescript_comment_lines(source: str) -> dict[int, str]:
    """Line number -> text, for every ``//`` and ``/* */`` comment line."""
    return _TypeScriptScanner(source).run()


def count_history_lines(path: str, source: str) -> int:
    if path.endswith('.py'):
        lines = python_comment_lines(source)
    else:
        lines = typescript_comment_lines(source)
    return sum(1 for text in lines.values() if PHRASES.search(text))


def tracked_files(trees: list[str]) -> list[str]:
    roots = [root for tree in trees for root in TREES[tree]]
    out = subprocess.run(
        ['git', 'ls-files', '-z', '--', *roots],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    extensions = tuple(ext for tree in trees for ext in _EXTENSIONS[tree])
    return sorted(
        name
        for name in out.split('\0')
        if name.endswith(extensions)
        and name not in _GENERATED
        and (_ROOT / name).is_file()
    )


def measure(trees: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in tracked_files(trees):
        source = (_ROOT / name).read_text(encoding='utf-8', errors='replace')
        found = count_history_lines(name, source)
        if found:
            counts[name] = found
    return counts


def read_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    return dict(json.loads(BASELINE.read_text(encoding='utf-8')).get('files', {}))


def write_baseline() -> int:
    counts = measure(list(TREES))
    body = {
        'about': (
            'Lines of comments and docstrings that narrate what the code used to do, '
            'per file. A ratchet: written only by '
            '`python3 backend/scripts/check_history_comments.py --write-baseline`, '
            'and a file with no entry starts at 0.'
        ),
        'files': dict(sorted(counts.items())),
    }
    BASELINE.write_text(json.dumps(body, indent=1) + '\n', encoding='utf-8')
    return sum(counts.values())


def check(trees: list[str]) -> tuple[list[str], list[str]]:
    """Return (failures, notices) for the chosen trees."""
    baseline = read_baseline()
    counts = measure(trees)
    prefixes = tuple(root + '/' for tree in trees for root in TREES[tree])
    failures: list[str] = []
    notices: list[str] = []
    for name, now in sorted(counts.items()):
        allowed = baseline.get(name, 0)
        if now > allowed:
            failures.append(
                f'{name}: {now} comment line(s) narrate what the code used to do '
                f'(allowed: {allowed}). Say what the code does now and why it has to; '
                f'the story of the change goes in the commit message (AGENTS.md, '
                f'"Comments and docstrings").'
            )
    for name, allowed in sorted(baseline.items()):
        if name.startswith(prefixes) and counts.get(name, 0) < allowed:
            notices.append(f'{name}: {counts.get(name, 0)} now, {allowed} recorded.')
    return failures, notices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--tree', choices=sorted(TREES), action='append')
    parser.add_argument('--write-baseline', action='store_true')
    args = parser.parse_args(argv)
    if args.write_baseline:
        total = write_baseline()
        print(f'history-comments baseline written: {total} line(s).')
        return 0
    failures, notices = check(args.tree or list(TREES))
    for message in failures:
        print(f'::error title=History-narrating comment::{message}', file=sys.stderr)
    if notices:
        print(
            f'{len(notices)} file(s) are below their baseline; lower it with '
            f'`python3 backend/scripts/check_history_comments.py --write-baseline`.'
        )
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
