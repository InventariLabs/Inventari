#!/usr/bin/env python3
"""Backlog identifiers do not belong in a public tree.

The backlog is private. An identifier like ``INV-<number>`` in a comment
points a reader of this repository at something they cannot open, and it
stands in for the reason instead of giving it: a comment saying "see
<epic>-<number>" is a comment with no content for everybody outside one
machine.

So the rule is the one AGENTS.md already states — no task id anywhere in
this repository — and this is the part that keeps it true for the tree.
Test files are read like every other file: a module test or a frontend spec
sits in the public tree exactly like production code, and its docstring is
read by the same outsider. Citations of *published* documents are a
different thing and stay: AGENTS.md sections, UI_GUIDELINES sections, ADR
numbers, RFCs. They name something the reader can open.

Each baseline entry names its finding by file, identifier and the line's
own text — never by line number. An edit above a baselined line moves its
address; naming the content keeps the entry on the reference it was
written for, and a line that loses the identifier leaves an entry that
suppresses nothing, which is itself a failure.

The scan runs on the whole public tree (``--public-tree``): every
directory that ships — ``backend``, ``frontend``, ``docs``, ``.github``,
``scripts``, ``docker`` and the rest — and every file at the repository
root. A task id sitting in a README, a migration docstring, a test title or
a build script is read by exactly the outsider it must not reach, so
nothing is exempt by location: tests, migrations, scripts, JSON and TOML are
read like production code. An audit before publication found that the old
roots (``backend/app``, ``frontend/src`` and the documents) left the test
trees, the migrations and the frontend scripts unread, which is where most
of the identifiers had gone to live. The gate and its own suite are read
too: the suite plants identifiers to prove the scan reads files, and it
assembles each of them at run time, so no file is exempt by name.

File names are read too: a test called ``Page.eq9.test.tsx`` or
``test_phase_c.py`` carries the plan step in its name.

Usage: ``check_internal_ids.py --public-tree`` or
``check_internal_ids.py <root> [<root> ...]``. Findings not in
``internal_id_baseline.txt`` fail the run. Every baseline entry names an
owner and an expiry, and an expired entry fails the run too — a suppression
nobody re-reads is how a gap goes quiet for months. An entry whose line no
longer carries the identifier fails the run as well: dead weight that
pretends the list is shrinking while only its key rots. The baseline is
maintained by hand — one line per live finding, and
``internal_id_baseline_sizes.txt`` bumped to match; there is no write flag.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from bisect import bisect_right
from collections.abc import Iterator
from datetime import date
from itertools import accumulate
from pathlib import Path

#: The one prefix the public tree may name. The maintainers' other prefixes
#: are not published here: listing them would tell every reader what the
#: private board is divided into, which is what this gate hides. They are
#: read from a private file, first found of
#:
#:   1. the path in ``INVENTARI_ID_PREFIXES``,
#:   2. ``internal_id_prefixes.local`` next to this script (gitignored).
#:
#: One entry per line, ``#`` comments; an entry is a prefix, optionally
#: followed by the longest number it is read with (``XX 3``). A checkout
#: without either still catches ``INV-<number>``, which is what a clean
#: public clone gets.
_PUBLIC_PREFIXES = ('INV',)
_SHORT_DEFAULT = 4
_LOCAL_PREFIXES = Path(__file__).resolve().parent / 'internal_id_prefixes.local'


def _private_file(variable: str, local: Path) -> Path | None:
    """The file ``variable`` names, else ``local``; None when neither exists."""
    given = os.environ.get(variable)
    candidates = [*([Path(given)] if given else []), local]
    return next((c for c in candidates if c.is_file()), None)


def load_prefixes(path: Path | None = None) -> dict[str, int]:
    """Prefix -> the most digits a task number carries, public prefix included.

    ``path`` reads that one file; without it the first existing candidate is
    used, and none at all leaves the public prefix alone.
    """
    prefixes = dict.fromkeys(_PUBLIC_PREFIXES, _SHORT_DEFAULT)
    source = (
        path
        if path is not None
        else _private_file('INVENTARI_ID_PREFIXES', _LOCAL_PREFIXES)
    )
    if source is None or not source.is_file():
        return prefixes
    for raw in source.read_text(encoding='utf-8').splitlines():
        parts = raw.split('#', 1)[0].split()
        if parts and re.fullmatch(r'[A-Z]{1,8}', parts[0]):
            digits = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            prefixes.setdefault(parts[0], digits or _SHORT_DEFAULT)
    return prefixes


def ticket_pattern(prefixes: dict[str, int]) -> re.Pattern[str]:
    """A task number has one to four digits and no leading zero: ``INV-0042``
    is a label code in a fixture, ``INV-12345`` a made-up barcode, neither a
    ticket. A prefix whose long tails are data (an asset-code format, a
    barcode) is listed with a shorter limit and read only up to it."""
    parts = [
        rf'\b{word}-[1-9]\d{{0,{digits - 1}}}\b'
        for word, digits in sorted(
            prefixes.items(), key=lambda kv: (-len(kv[0]), kv[0])
        )
    ]
    return re.compile('|'.join(parts))


_TICKET = ticket_pattern(load_prefixes())

#: Internal plan vocabulary that points at the same private material, and
#: paths into the private plans directory.
#:
#: Deliberately not here: a bare "Phase 1" / "Phase 2". Half of them describe
#: an algorithm ("phase 1 claims the batch, phase 2 makes the call") and the
#: other half a plan step, and a checker that cannot tell them apart trains
#: people to write around it. The vocabulary below has no innocent reading.
_PLAN_WORDS = re.compile(
    r'\b(?:Wave|WAVE|Fala|FALA)\s+\d'
    r'|\bFaza\s+[\dA-Z]'
    r'|\bOpcja\s+[A-Z]\b'
    r'|\bQA\s+S\d+\b'
    r'|\bPhase\s+\d[a-z]?\s+S\d'
    # a plan step: a phase number followed by "F" and a digit, by "step"
    # and a number, or a dotted step. A bare "Phase 1" stays allowed (see
    # above).
    r'|\bPhase\s+\d+\s+(?:F\d|step\s+\d)'
    r'|\bPhase\s+\d+\.\d'
    # an acceptance criterion of a private task.
    r'|\bAC\s?#\d'
    # private working directories, cited by path.
    r'|(?<![\w/-])docs/(?:superpowers|reviews|plans|ux|business|marketing)/'
    r'|(?<![\w/])tasks/[A-Za-z0-9_.-]+\.md'
    r'|(?<![\w/])lessons\.md'
    # an ignore-file line that names the private directories themselves.
    r'|^\s*/?(?:plans|tasks)/?\s*$'
    # any case: the plan files are named in prose too — a lowercase plan
    # path sat in a .txt header for months because the pattern demanded
    # capitals in the file name.
    r'|(?<![\w/])plans/[A-Za-z0-9_-]+\.md'
    # the private lessons file, cited by path the same way.
    r'|(?<![\w/])tasks/lessons\.md'
)

#: Every alternative of ``_PLAN_WORDS`` contains one of these words. The
#: pattern costs about a second per alternative over the million and a half
#: lines of the tree, and this one search drops all but a few thousand of them
#: before it runs. A new alternative needs its own word here.
_PLAN_NEEDLE = re.compile(
    r'Wave|WAVE|Fala|FALA|Faza|Opcja|QA|Phase|AC|docs/|tasks|plans|lessons\.md'
)

#: Every task number has a dash followed by a digit from one to nine, whatever
#: the prefix. The search is a fraction of the cost of the ticket pattern's
#: dozens of alternatives and drops nearly every line before it runs.
_TICKET_HINT = re.compile(r'-[1-9]')

#: Markdown and plain text sit in the public tree exactly like code: a
#: README line or a baseline-file header is read by the same outsider, and
#: two measured leaks (a task id in AGENTS.md, a private plan path in a
#: .txt header) sat invisible for months because these suffixes were not
#: here. The gate's own baseline is the one .txt that must stay unscanned —
#: its lines ARE identifiers by design, every one of them.
#:
#: ``.yml`` joined the same way every suffix must — on a measured finding,
#: not speculation: a task id sat in a comment in
#: ``.github/workflows/ci.yml`` while the suffix filter skipped the file.
#: Deliberately not here: structured data (.json, .sql, .csv). The measured
#: carriers of prose are .md, .txt and .yml; a data format joins when it
#: carries a finding — the way it stands, the scope is a decision this
#: comment owns rather than an accident of history.
#:
#: Since the pre-publication audit the structured formats are read as well
#: (.json, .toml, .ini, .yaml) together with the scripts and templates
#: (.mjs, .cjs, .js, .sh, .html, .mako, .css, .cfg): the audit found ids in
#: ``pyproject.toml``, a QA-surface JSON and a dozen build scripts, none of
#: which a suffix list written for prose would ever open.
_SUFFIXES = {
    '.py',
    '.ts',
    '.tsx',
    '.md',
    '.txt',
    '.yml',
    '.yaml',
    '.json',
    '.toml',
    '.ini',
    '.cfg',
    '.mjs',
    '.cjs',
    '.js',
    '.sh',
    '.html',
    '.mako',
    '.css',
}

#: Suffixless files the scan reads by name: the ``Makefile`` is prose too,
#: and it carried two ids while a filter that trusts suffixes skipped it.
_SUFFIXLESS_FILES = {
    'Makefile',
    'Caddyfile',
    'Dockerfile',
    '.gitignore',
    '.dockerignore',
    '.gitattributes',
}
#: Local agent entry points that are gitignored and never published.
_UNPUBLISHED_ROOT_FILES = frozenset({'CLAUDE.md', 'GEMINI.md'})
_SKIP = (
    '__pycache__',
    '/node_modules/',
    '/.git/',
    '/.venv/',
    '/dist/',
    '/coverage/',
    '/playwright-report/',
    '/test-results/',
    '/graphify-out/',
    '/.opencode/',
    'internal_id_baseline.txt',
    # generated or vendored, no prose of ours
    'package-lock.json',
    'uv.lock',
    # the coverage run's report: gitignored, one line of ten megabytes that
    # the plan pattern needed seconds to read
    'coverage.json',
)
#: A file name that carries a plan step: ``Page.eq9.test.tsx``,
#: ``test_phase_c.py``, ``clusterBStates.test.tsx``.
_PLAN_FILENAME = re.compile(
    r'(?i:(?:^|[._-])(?:eq\d+|phase[_-]?[a-z0-9])(?=[._-]|$))|cluster[A-Z]'
)
#: The directories (under the repository root) the public tree ships.
_PUBLIC_DIRS = (
    'backend',
    'frontend',
    'docs',
    '.github',
    'scripts',
    'docker',
    'load_tests',
    'print-agent',
    'signatures',
    'modules-workspace',
    '.devcontainer',
)
#: The roots that must exist: the rest are optional in a given checkout, but a
#: container without ``frontend/`` would otherwise scan a third of the tree
#: and report it clean.
_REQUIRED_PUBLIC_DIRS = ('backend', 'frontend', 'docs')
#: Directories under docs/ that are gitignored and never reach publication
#: — the same list check_docs_paths.py skips. They are absent from a fresh
#: clone but present in a working tree, and a gate that changes colour with
#: the operator's untracked files is not a gate.
_DOCS_EXCLUDED_DIRS = frozenset(
    {'business', 'marketing', 'plans', 'reviews', 'superpowers', 'ux'}
)
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parent
_BASELINE = (
    Path(__file__).resolve().parent.parent
    / 'app'
    / 'core'
    / ('internal_id_baseline.txt')
)

#: ``(path, line number, the identifier, the line)`` for each hit.
Hit = tuple[str, int, str, str]


def _display(path: Path) -> str:
    """The path as the baseline spells it, independent of the checkout layout.

    The baseline is a committed file, so its keys cannot depend on where the
    checker ran. ``backend/`` prefixes anything under the backend directory,
    which keeps them equal between a checkout at the repository root and the
    container, where that directory is mounted at ``/app``. The same checkout
    is mounted a second time at ``/repo`` (read-only, whole tree — see
    docker-compose.yml), which the documents-and-tests scan walks too:
    stripping that prefix keeps a container finding keyed the way the host
    wrote it, instead of resurrecting every baselined line as new.
    """
    resolved = path.resolve()
    try:
        return 'backend/' + resolved.relative_to(_BACKEND_ROOT).as_posix()
    except ValueError:
        pass
    text = str(resolved)
    if text.startswith('/repo/'):
        return text[len('/repo/') :]
    try:
        return resolved.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def public_tree_roots(repo_root: Path | None = None) -> list[Path]:
    """Every directory that ships, plus each file at the repository root.

    ``make lint`` and the suite both call this, so the Makefile and the test
    cannot drift apart the way two hand-kept root lists did.
    """
    root = repo_root or Path(os.environ.get('INVENTARI_REPO_ROOT') or _REPO_ROOT)
    missing = [name for name in _REQUIRED_PUBLIC_DIRS if not (root / name).is_dir()]
    if missing:
        raise FileNotFoundError(
            f'public tree root(s) {missing} not found under {root}: a checkout '
            'the gate cannot see must fail the run, not report a smaller tree clean'
        )
    dirs = [root / name for name in _PUBLIC_DIRS if (root / name).is_dir()]
    files = sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.name not in _UNPUBLISHED_ROOT_FILES
    )
    return dirs + files


def _is_scanned(path: Path) -> bool:
    text = str(path)
    if not path.is_file():
        return False
    named = path.name in _SUFFIXLESS_FILES or path.name.startswith('Dockerfile')
    if path.suffix not in _SUFFIXES and not named:
        return False
    if any(part in text for part in _SKIP):
        return False
    parts = path.parts
    return not any(
        parent == 'docs' and child in _DOCS_EXCLUDED_DIRS
        for parent, child in zip(parts, parts[1:], strict=False)
    )


#: The directories ``_SKIP`` names, which a walk need not enter at all: the
#: dependency tree under ``frontend/`` is most of the files a checkout holds.
_SKIP_DIRS = frozenset(
    part.strip('/') for part in _SKIP if part.startswith('/') and part.endswith('/')
) | {'__pycache__'}


def _files_under(root: Path) -> Iterator[Path]:
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = [name for name in subdirectories if name not in _SKIP_DIRS]
        for name in names:
            yield Path(directory) / name


def _candidate_lines(text: str) -> list[tuple[int, str]]:
    """``(line number, line)`` for each line that may hold a finding.

    One search over the whole text finds where the ticket hint and the plan
    needle occur; only the lines around those places go on to the full
    patterns. Searching line by line made a million and a half calls a scan.
    """
    places = [match.start() for match in _TICKET_HINT.finditer(text)]
    places += [match.start() for match in _PLAN_NEEDLE.finditer(text)]
    if not places:
        return []
    lines = text.splitlines(keepends=True)
    ends = list(accumulate(map(len, lines)))
    wanted = sorted({bisect_right(ends, place) for place in places})
    return [(index + 1, lines[index].splitlines()[0]) for index in wanted]


def scan(roots: list[Path]) -> list[Hit]:
    """``(relative path, line number, the identifier, the line)`` for each hit.

    A root may be a directory or a single file — the public documents
    (AGENTS.md, README.md, the guides) are passed as files, and a file
    feeds itself to the loop rather than expanding to nothing. A root
    that does not exist is an error, never an empty scan: a checkout the
    gate cannot see must fail the run, not report a smaller tree clean.
    """
    found: list[Hit] = []
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(f'scan root does not exist: {root}')
        paths = [root] if root.is_file() else sorted(_files_under(root))
        for path in paths:
            if not _is_scanned(path):
                continue
            name_hit = _PLAN_FILENAME.search(path.name)
            if name_hit:
                found.append(
                    (_display(path), 0, name_hit.group(0).strip('._-'), path.name)
                )
            for lineno, line in _candidate_lines(path.read_text(encoding='utf-8')):
                match = _TICKET.search(line) or _PLAN_WORDS.search(line)
                if match:
                    found.append((_display(path), lineno, match.group(0), line.strip()))
    return found


def hit_key(hit: Hit) -> str:
    """``<path>:<identifier>:<line text>`` — a finding's address is its
    content, not its row number."""
    return f'{hit[0]}:{hit[2]}:{hit[3]}'


def new_findings(roots: list[Path], baseline: set[str]) -> list[Hit]:
    """Findings the baseline does not already own."""
    return [hit for hit in scan(roots) if hit_key(hit) not in baseline]


def stale_entries(roots: list[Path], baseline: set[str]) -> list[str]:
    """Baseline entries no live line matches, sorted.

    An entry whose identifier has left the tree suppresses nothing and
    hides nothing: the gate reports it, and the fix is deletion, not
    renewal.
    """
    covered = {hit_key(hit) for hit in scan(roots)}
    return sorted(baseline - covered)


def _parse_entry(
    line: str, lineno: int, source: str, today: date
) -> tuple[str | None, str | None]:
    """``(key, problem)`` for one baseline line; exactly one of them is set."""
    parts = [part.strip() for part in line.split('|')]
    if len(parts) < 4 or not parts[3]:
        return None, (
            f'::error file={source},line={lineno},title=Internal id baseline: '
            f'malformed entry::Expected "<path>:<identifier>:<line text> | '
            f'owner=<who> | expires=<YYYY-MM-DD> | <reason>", got: {line}'
        )
    key, owner, expires = parts[0], parts[1], parts[2]
    if not owner.startswith('owner=') or len(owner) <= len('owner='):
        return None, (
            f'::error file={source},line={lineno},title=Internal id baseline: '
            f"entry names nobody::'{key}' has no owner=<who> — an unowned "
            f'suppression is how this gap got here.'
        )
    if not expires.startswith('expires='):
        return None, (
            f'::error file={source},line={lineno},title=Internal id baseline: '
            f"entry never expires::'{key}' needs expires=<YYYY-MM-DD>."
        )
    try:
        deadline = date.fromisoformat(expires[len('expires=') :])
    except ValueError:
        return None, (
            f'::error file={source},line={lineno},title=Internal id baseline: '
            f"unreadable expiry::'{key}' has expires='{expires[len('expires=') :]}'; "
            f'expected YYYY-MM-DD.'
        )
    if deadline < today:
        return None, (
            f'::error file={source},line={lineno},title=Internal id baseline: '
            f"entry expired::'{key}' expired on {deadline.isoformat()} — "
            f'{owner[len("owner=") :]} was to recheck it.'
        )
    return key, None


def load_baseline(path: Path | None = None) -> tuple[set[str], list[str]]:
    """``(keys, problems)`` read from the suppression list.

    Format, one entry per line::

        <path>:<identifier>:<line text> | owner=<who> | expires=<YYYY-MM-DD> | <reason>

    Owner and expiry are mandatory and both are checked, the way the
    architecture baselines check theirs. An entry that is malformed or past
    its date suppresses nothing and is reported — a gate that cannot read
    its own baseline must not report clean.
    """
    path = path or _BASELINE
    if not path.exists():
        return set(), []
    source = _display(path)
    today = date.today()
    keys: set[str] = set()
    problems: list[str] = []
    for lineno, raw in enumerate(
        path.read_text(encoding='utf-8').splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        key, problem = _parse_entry(line, lineno, source, today)
        if problem:
            problems.append(problem)
        elif key:
            keys.add(key)
    return keys, problems


# --- commit messages -------------------------------------------------------
#
# The history is published with the tree, so a commit message is read by the
# same outsider as a comment. It describes what changed and why, in prose: no
# task or plan identifier, no branch name, nothing that narrates who made the
# change. A GitHub issue reference ("Fixes #12") and a commit hash name public
# things and pass.

#: Words the maintainers keep out of the published history are read from a
#: private file the way the prefixes above are, so the public tree does not
#: list them: ``INVENTARI_PRIVATE_WORDS``, then ``internal_private_words.local``
#: next to this script (gitignored). One regular expression per line, matched
#: in any case; ``#`` starts a comment line. A checkout without the file
#: checks identifiers and branch names only.
_LOCAL_PRIVATE_WORDS = Path(__file__).resolve().parent / 'internal_private_words.local'

#: Milestones of the private board (``m-101``).
_MILESTONE = re.compile(r'\bm-\d+\b', re.IGNORECASE)
#: A work branch, with or without its remote: ``fix/the-thing``,
#: ``origin/feature/x``. The same token is a file path just as often
#: (``docs/api/openapi.json``); ``_is_path`` tells the two apart.
_BRANCH_REF = re.compile(
    r'(?<![\w/.-])(?:origin/)?'
    r'(?:feature|feat|fix|bugfix|hotfix|chore|docs?|refactor|perf|test|spike|release)'
    r'/[\w.-]+(?:/[\w.-]+)*',
    re.IGNORECASE,
)
_FILE_SUFFIX = re.compile(r'\.[A-Za-z]\w{0,5}$')
#: The subject git writes for a merge when nobody wrote one.
_GIT_MERGE_SUBJECT = re.compile(
    r'^merge\s+(?:commit|branch|remote-tracking|pull request)\b', re.IGNORECASE
)
#: ...and the one of them a branch gets every time it catches up with dev.
#: Every branch does that, usually with ``--no-edit``, so the hook writes the
#: prose for it instead of refusing the merge.
_DEV_MERGE_SUBJECT = re.compile(
    r"^Merge (?:remote-tracking )?branch '(?:origin/)?dev'(?: of \S+)?(?: into \S+)?$"
)
PROSE_DEV_MERGE = 'Merge the development line'
_SCISSORS = '# ------------------------ >8 ------------------------'
_GIT_MERGE_FINDING = "git's own merge subject, not prose"
_BRANCH_FINDING = 'a branch name'
#: What reads short of prose without making anything private public. The hook
#: refuses it while a reword is free; after the push a reword rewrites
#: published history, so the push-side check reports it and lets it through.
_WORDING_ONLY = frozenset({_GIT_MERGE_FINDING, _BRANCH_FINDING})

#: ``(what kind of thing, the text that is it)`` for each finding.
MessageFinding = tuple[str, str]


def load_private_words(path: Path | None = None) -> re.Pattern[str] | None:
    """The private word list as one pattern, or None without a file.

    A line that is not a valid expression fails loudly: a list that silently
    dropped an entry would let exactly that word through.
    """
    if path is None:
        path = _private_file('INVENTARI_PRIVATE_WORDS', _LOCAL_PRIVATE_WORDS)
    if path is None or not path.is_file():
        return None
    parts: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        try:
            re.compile(line)
        except re.error as exc:
            raise ValueError(
                f'{path}:{lineno}: not a regular expression: {exc}'
            ) from exc
        parts.append(f'(?:{line})')
    return re.compile('|'.join(parts), re.IGNORECASE) if parts else None


def _is_path(token: str, repo_root: Path) -> bool:
    """A token shaped like a branch that names a file or directory instead."""
    bare = token.removeprefix('origin/').rstrip('.')
    return bool(_FILE_SUFFIX.search(bare)) or (repo_root / bare).exists()


def _message_lines(text: str) -> list[str]:
    """The lines git keeps: no comment lines, nothing below the scissors."""
    kept: list[str] = []
    for line in text.splitlines():
        if line.startswith(_SCISSORS):
            break
        if not line.startswith('#'):
            kept.append(line)
    return kept


def message_findings(
    text: str,
    *,
    ticket: re.Pattern[str] | None = None,
    private_words: re.Pattern[str] | None = None,
    repo_root: Path | None = None,
) -> list[MessageFinding]:
    """What in a commit message may not be published, in reading order."""
    ticket = re.compile((ticket or _TICKET).pattern, re.IGNORECASE)
    root = repo_root or _REPO_ROOT
    lines = [line for line in _message_lines(text) if line.strip()]
    found: list[MessageFinding] = []
    if lines and _GIT_MERGE_SUBJECT.search(lines[0]):
        found.append((_GIT_MERGE_FINDING, lines[0]))
    for line in lines:
        for rx, what in (
            (ticket, 'a task identifier'),
            (_MILESTONE, 'a milestone identifier'),
            (_PLAN_WORDS, 'plan vocabulary'),
            (private_words, 'private vocabulary'),
        ):
            if rx is not None:
                found.extend((what, m.group(0)) for m in rx.finditer(line))
        found.extend(
            (_BRANCH_FINDING, m.group(0))
            for m in _BRANCH_REF.finditer(line)
            if not _is_path(m.group(0), root)
        )
    return found


def _report_message(findings: list[MessageFinding], where: str) -> None:
    for what, token in findings:
        print(f'{where}: {what} («{token}»)')


def check_commit_msg_file(path: Path, private_words: re.Pattern[str] | None) -> int:
    """The ``commit-msg`` hook: refuse a message that is not prose.

    git's default subject for catching a branch up with dev is replaced by
    prose in place; anything else is refused with what to write instead.
    """
    text = path.read_text(encoding='utf-8')
    first, _, rest = text.partition('\n')
    if _DEV_MERGE_SUBJECT.match(first.strip()):
        text = f'{PROSE_DEV_MERGE}\n{rest}'
        path.write_text(text, encoding='utf-8')
    findings = message_findings(text, private_words=private_words)
    if not findings:
        return 0
    _report_message(findings, 'commit message')
    print(
        'A commit message is published with the code: say what changed and why '
        'in prose. The task lives on the board and the branch in git, not in the '
        'message. A merge takes its subject with -m "<what the merge brings>". '
        '"Fixes #<issue>" and commit hashes are fine.'
    )
    return 1


def check_commits(
    rev_range: str, private_words: re.Pattern[str] | None, repo: Path | None = None
) -> int:
    """The messages of the commits ``rev_range`` would publish.

    Fails on what must not become public; wording alone is reported.
    """
    root = repo or _REPO_ROOT
    log = subprocess.run(
        ['git', 'log', '--format=%H%x1f%B%x1e', rev_range],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    bad = worded = 0
    for record in log.split('\x1e'):
        sha, sep, body = record.strip('\n').partition('\x1f')
        if not sep:
            continue
        findings = message_findings(body, private_words=private_words, repo_root=root)
        if findings:
            if all(what in _WORDING_ONLY for what, _ in findings):
                worded += 1
            else:
                bad += 1
            subject = body.splitlines()[0] if body else ''
            _report_message(findings, f'{sha[:9]} {subject[:60]}')
    if worded:
        print(
            f'commit messages: {worded} commit(s) in {rev_range} read short of '
            'prose — reported, not failed: a pushed commit is not reworded'
        )
    if bad:
        print(
            f'commit messages: {bad} commit(s) in {rev_range} would publish '
            'what is private'
        )
        return 1
    print(f'commit messages: nothing private in {rev_range}')
    return 0


def main() -> int:
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == '--commit-msg':
        return check_commit_msg_file(Path(args[1]), load_private_words())
    if len(args) == 2 and args[0] == '--commits':
        return check_commits(args[1], load_private_words())
    if args == ['--public-tree']:
        roots = public_tree_roots()
    else:
        roots = [Path(arg) for arg in args] or [Path('app')]
    baseline, problems = load_baseline()
    new = new_findings(roots, baseline)
    stale = stale_entries(roots, baseline)

    if not new and not problems and not stale:
        # Entries and unique keys are different numbers when several lines
        # share one content key; saying both keeps "the list is shrinking"
        # measurable against either count.
        entries = sum(
            1
            for line in _BASELINE.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')
        )
        detail = (
            f'{entries} entries, {len(baseline)} unique keys'
            if entries != len(baseline)
            else f'{entries} entries'
        )
        print(f'internal-ids: clean ({detail}) — no task ids in the public tree')
        return 0

    for problem in problems:
        print(problem)
    for key in stale:
        print(
            f'::error file={_display(_BASELINE)},title=Internal id baseline: '
            f"entry suppresses nothing::'{key}' — the line no longer carries "
            f'this identifier; delete the entry.'
        )
    for path, lineno, ident, line in new:
        print(
            f'::error file={path},line={lineno},title=Internal identifier in a '
            f"public tree::'{ident}' points at a private backlog. Say the reason "
            f'instead: {line[:90]}'
        )
    if problems:
        print(f'internal-ids: {len(problems)} baseline problem(s)')
    if stale:
        print(f'internal-ids: {len(stale)} stale entr(y/ies)')
    if new:
        print(f'internal-ids: {len(new)} new finding(s)')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
