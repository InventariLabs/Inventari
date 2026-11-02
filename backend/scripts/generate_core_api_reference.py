"""Generate Markdown reference documentation for CoreAPI by introspecting namespace classes.

Usage:
    # From project root (recommended):
    python backend/scripts/generate_core_api_reference.py --output docs/subsystems/CORE_API.md

    # Inside Docker (stdout → host redirect):
    docker compose exec -T backend python scripts/generate_core_api_reference.py > docs/subsystems/CORE_API.md

    # Verify docs are up-to-date (CI gate):
    python backend/scripts/generate_core_api_reference.py --check
"""

from __future__ import annotations

import argparse
import inspect
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: add backend/ to sys.path so app.* imports resolve
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Project root = parent of backend/
_PROJECT_ROOT = _BACKEND_DIR.parent
DEFAULT_OUTPUT = _PROJECT_ROOT / 'docs' / 'subsystems' / 'CORE_API.md'


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def _is_core_api_instance(obj: object) -> bool:
    """Return True if *obj* is an instance of a class named ``Core*API``."""
    return type(obj).__name__.startswith('Core') and type(obj).__name__.endswith('API')


def _collect_namespaces() -> list[tuple[str, type]]:
    """Introspect CoreAPI.__init__ source to find ``self.xxx = CoreXxxAPI()`` assignments.

    Returns ``(attr_name, class_object)`` pairs in declaration order.
    """
    from app.core.public_api import CoreAPI

    src = inspect.getsource(CoreAPI.__init__)

    results: list[tuple[str, type]] = []
    for line in src.splitlines():
        line = line.strip()
        if not line.startswith('self.'):
            continue
        parts = line.split('=', 1)
        if len(parts) != 2:
            continue
        attr_name = parts[0].strip().removeprefix('self.')
        class_name = parts[1].strip().rstrip('()')

        # Resolve the class from the public_api package
        from app.core import public_api as _pkg

        cls = getattr(_pkg, class_name, None)
        if cls is not None and _is_core_api_instance(cls()):
            results.append((attr_name, cls))
    return results


def _format_annotation(annotation: Any) -> str:
    """Render a type annotation to a compact, readable string."""
    if annotation is inspect.Parameter.empty:
        return ''
    if annotation is inspect.Signature.empty:
        return ''

    s = str(annotation)
    # Strip module prefixes for readability (keep last qualname)
    if 'app.' in s:
        parts = s.split('.')
        s = parts[-1]
    # Collapse builtins. prefix
    s = s.replace('builtins.', '')
    # Clean up sqlalchemy session type paths
    s = s.replace('sqlalchemy.orm.session.Session', 'Session')
    s = s.replace('sqlalchemy.ext.asyncio.Session', 'AsyncSession')
    s = s.replace('sqlalchemy.ext.asyncio.ext.AsyncSession', 'AsyncSession')
    return s


def next_param_kind(sig: inspect.Signature, name: str) -> Any:
    """The kind of the parameter after *name*, or ``None`` at the end."""
    names = list(sig.parameters)
    index = names.index(name)
    if index + 1 < len(names):
        return sig.parameters[names[index + 1]].kind
    return None


def _format_signature(func: Any) -> str:
    """Build a compact signature string for display in the Markdown table."""
    sig = inspect.signature(func)
    params: list[str] = []
    star_written = False
    for name, param in sig.parameters.items():
        if name == 'self':
            continue
        # Keep the call shape: `*` before the first keyword-only parameter
        # (unless a *args already stands there), `/` after positional-only ones.
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            star_written = True
        if param.kind is inspect.Parameter.KEYWORD_ONLY and not star_written:
            params.append('*')
            star_written = True
        ann = _format_annotation(param.annotation)
        default = (
            '' if param.default is inspect.Parameter.empty else f'={param.default!r}'
        )
        # Shorten very long repr defaults
        if len(default) > 40:
            default = default[:37] + '...'
        prefix = {
            inspect.Parameter.VAR_POSITIONAL: '*',
            inspect.Parameter.VAR_KEYWORD: '**',
        }.get(param.kind, '')
        if ann:
            params.append(f'{prefix}{name}: {ann}{default}')
        else:
            params.append(f'{prefix}{name}{default}')
        if param.kind is inspect.Parameter.POSITIONAL_ONLY and (
            next_param_kind(sig, name) is not inspect.Parameter.POSITIONAL_ONLY
        ):
            params.append('/')
    ret = _format_annotation(sig.return_annotation)
    ret_str = f' -> {ret}' if ret else ''
    return f'({", ".join(params)}){ret_str}'


def _first_line(docstring: str | None) -> str:
    """Return the first non-empty line of *docstring*, or ``—``."""
    if not docstring:
        return '—'
    for line in docstring.strip().splitlines():
        line = line.strip()
        if line:
            return line
    return '—'


def _determine_rw(name: str, doc: str | None) -> str:
    """Heuristic to classify a method as READ or WRITE based on name and docstring."""
    lower_name = name.lower()
    lower_doc = (doc or '').lower()
    # Explicit signals in docstring, as whole words: ``created_at`` in a
    # read's docstring is not a write.
    if re.search(r'\b(writes?|creates?|deletes?|updates?)\b', lower_doc):
        return 'WRITE'
    # Signals in method name
    write_names = {
        'set',
        'delete',
        'create',
        'update',
        'send',
        'notify',
        'save',
        'generate',
        'assign',
        'unassign',
        'purge',
        'block',
        'unblock',
        'promote',
        'toggle',
        'apply',
        'mark',
        'release',
        'reserve',
        'record',
        'encrypt',
        'transfer',
        'move',
        'post',
        'bind',
        'activate',
    }
    for token in write_names:
        if token in lower_name:
            return 'WRITE'
    if 'log' in lower_name and 'read' not in lower_doc:
        return 'WRITE'
    return 'READ'


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------


def _namespace_descriptions() -> dict[str, str]:
    """Return a mapping of attr_name -> first line of class docstring."""
    from app.core.public_api import CoreAPI

    src = inspect.getsource(CoreAPI.__init__)
    descs: dict[str, str] = {}
    for line in src.splitlines():
        line = line.strip()
        if not line.startswith('self.'):
            continue
        parts = line.split('=', 1)
        if len(parts) != 2:
            continue
        attr = parts[0].strip().removeprefix('self.')
        class_name = parts[1].strip().rstrip('()')

        from app.core import public_api as _pkg

        cls = getattr(_pkg, class_name, None)
        if cls is None:
            continue
        doc = inspect.getdoc(cls)
        if doc:
            first = doc.strip().split('\n')[0].strip()
            descs[attr] = first
        else:
            descs[attr] = class_name
    return descs


def _generate_markdown() -> str:  # noqa: PLR0915 - doc generator with many sections
    """Generate the full Markdown document by introspecting CoreAPI."""
    descs = _namespace_descriptions()
    namespaces = _collect_namespaces()

    lines: list[str] = []
    lines.append('# CoreAPI Reference')
    lines.append('')
    lines.append(
        'The **CoreAPI** (`app.core.public_api.core_api`) is a facade that exposes '
        'stable, module-safe methods for interacting with Core data. Modules must use '
        'CoreAPI instead of importing Core models or services directly.'
    )
    lines.append('')
    lines.append('**Location:** `backend/app/core/public_api/`')
    lines.append('')
    lines.append('---')
    lines.append('')

    # ── Namespace summary table ────────────────────────────────────────
    lines.append(f'## Namespaces ({len(namespaces)})')
    lines.append('')
    lines.append('| Namespace | Class | Description |')
    lines.append('|---|---|---|')
    for attr_name, cls in namespaces:
        desc = descs.get(attr_name, cls.__name__)
        lines.append(f'| `core_api.{attr_name}` | `{cls.__name__}` | {desc} |')
    lines.append('')
    lines.append('---')
    lines.append('')

    # ── Method reference per namespace ──────────────────────────────────
    lines.append('## Method Reference')
    lines.append('')

    total_methods = 0
    total_read = 0
    total_write = 0

    for attr_name, cls in namespaces:
        desc = descs.get(attr_name, cls.__name__)
        lines.append(f'### `core_api.{attr_name}` — `{cls.__name__}`')
        lines.append('')
        lines.append('| Method | Signature | R/W | Description |')
        lines.append('|---|---|---|---|')

        # Collect public methods from the class and all its bases (MRO),
        # deduplicating so the most-derived version wins.
        methods: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for base in reversed(cls.__mro__):
            for name, obj in vars(base).items():
                if name in seen or name.startswith('_'):
                    continue
                # A staticmethod/classmethod in vars() is a descriptor, not a
                # function: unwrap it, or every static method drops out.
                if isinstance(obj, (staticmethod, classmethod)):
                    obj = obj.__func__
                if inspect.isfunction(obj):
                    seen.add(name)
                    methods.append((name, obj))

        # Sort alphabetically for deterministic output
        methods.sort(key=lambda x: x[0])

        for name, func in methods:
            sig_str = _format_signature(func)
            doc = inspect.getdoc(func)
            summary = _first_line(doc)
            # Escape pipe chars inside Markdown table cells
            summary = summary.replace('|', '\\|')
            sig_str = sig_str.replace('|', '\\|')
            rw = _determine_rw(name, doc)
            total_methods += 1
            if rw == 'READ':
                total_read += 1
            else:
                total_write += 1
            lines.append(f'| `{name}` | `{sig_str}` | {rw} | {summary} |')

        lines.append('')
        lines.append('---')
        lines.append('')

    # ── Statistics ──────────────────────────────────────────────────────
    lines.append('## Statistics')
    lines.append('')
    lines.append(f'- **Total methods:** {total_methods}')
    lines.append(f'- **Namespaces:** {len(namespaces)}')
    lines.append(f'- **Documented methods:** {total_methods} (100%)')
    read_pct = round(total_read / total_methods * 100) if total_methods else 0
    write_pct = round(total_write / total_methods * 100) if total_methods else 0
    lines.append(f'- **READ methods:** {total_read} ({read_pct}%)')
    lines.append(f'- **WRITE methods:** {total_write} ({write_pct}%)')
    lines.append('')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Generate CoreAPI Markdown reference from introspection.',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Write Markdown to this file (default: stdout). '
        'Conventional path: docs/subsystems/CORE_API.md',
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Compare generated output against the file and exit 1 if different. '
        f'Default file: {DEFAULT_OUTPUT}',
    )
    args = parser.parse_args()

    generated = _generate_markdown()

    target = args.output or DEFAULT_OUTPUT

    if args.check:
        if not target.exists():
            print(
                f'CHECK FAILED: {target} does not exist — run without --check to generate it.'
            )
            return 1
        existing = target.read_text()
        if existing == generated:
            print(f'CHECK OK: {target} is up to date ({len(generated)} chars).')
            return 0
        # Show compact diff hint
        existing_lines = existing.splitlines()
        generated_lines = generated.splitlines()
        diffs = 0
        for i, (old, new) in enumerate(
            zip(existing_lines, generated_lines, strict=False), start=1
        ):
            if old != new:
                diffs += 1
                if diffs <= 5:
                    print(f'  line {i}: - {old!r}')
                    print(f'  line {i}: + {new!r}')
        if len(existing_lines) != len(generated_lines):
            print(f'  line count: {len(existing_lines)} -> {len(generated_lines)}')
        if diffs > 5:
            print(f'  ... and {diffs - 5} more differences')
        print(
            f'CHECK FAILED: {target} is out of date '
            f'({diffs} line(s) differ). Run without --check to regenerate.'
        )
        return 1

    # Normal mode: write to file or stdout
    if args.output:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated)
        print(f'Generated {len(generated)} chars -> {target}')
    else:
        print(generated)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
