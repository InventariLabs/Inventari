#!/usr/bin/env python
"""Export the field names the backend writes into audit snapshots.

The organisation journal reads every snapshot key through the frontend
catalogue (`settings.audit.fields.*`). Nothing compared the two sets, so a
new field entered the journal in English and nobody found out — the same
shape of gap `check:i18n:sync-backend` closes for the keys the module
manifests declare.

This script is the backend half: it reads the writers that *declare* their
keys and writes them to `frontend/scripts/audit-snapshot-keys.json`. The
frontend half (`frontend/scripts/check-audit-fields.mjs`) compares that file
with the five catalogues.

What it reads, and what it deliberately does not
------------------------------------------------
A snapshot key is a string the backend puts into `snapshot=`, `before=` or
`after=` — either as a dict literal at the call site or inside a builder
function (`item_to_snapshot`, `_recipe_shape`, …). Those shapes are read here,
plus the `_AUDITED`-style tuples that name a writer's fields outright.

A third shape writes no literal at all: a writer whose `before`/`after` are
built *from an update payload* (`for f in update_data if hasattr(row, f)`),
so its keys are the update schema's field names and appear nowhere as
literals. Such a writer declares the pair it draws from beside its own code,

    AUDIT_PAYLOAD_SCHEMA = ('ItemUpdate', 'Item')

and this script adds the intersection — the schema's fields the model
actually carries, which is exactly the set `hasattr` lets through: a field
the schema knows but the model does not is stripped by the writer, and a
field only the model knows never arrives in a payload. The declaration sits
in the writer, not in a list here, because the writer is where a reader of
that code asks "which fields can this journal show?". The names resolve the
way Python resolves them — through the declaring file's own imports — so a
name that means two classes in two modules (`Item` is both the model and
the read schema) lands on the one the writer meant.

The configuration funnel is read directly. Every module-owned
configuration write goes through `core.settings_diff.journal_config_change`,
which takes the writer's key universe as its `keys=` argument. When that
set is a literal it is read exactly like a snapshot dict; when it is cut
from a payload (`keys=set(data.model_fields_set)`), the file has to carry
the declaration above — and one whose names resolve to nothing covers
nothing. A funnel writer with dynamic keys and no effective declaration
lands in the artefact's `uncovered-writer-files`, which the frontend half
of the gate refuses: green must not mean "read everything that happened to
declare itself".

What this artefact still cannot see, it says so. A payload writer outside
the funnel (a service building `before`/`after` straight from a payload)
has no mechanical signature, and is covered only by the declaration
convention — whose count the artefact saves as `declarations-read`, so a
writer losing its declaration shows as a fall instead of as no writer.

Refresh: `make sync-audit-fields` (or, from the repo root,
`docker compose exec -T backend python scripts/export_audit_snapshot_keys.py`).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import TypedDict

# The container mounts the repository at /app and the tree beside it nowhere,
# so the artefact goes to stdout by default and the caller decides where it
# lands: `make sync-audit-fields` redirects it into frontend/scripts/.
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
APP_ROOT = BACKEND_ROOT / 'app'

# A keyword whose value is written into the journal. `snapshot=` carries a
# create's or a delete's fields; `before=`/`after=` carry the two sides of an
# update; the funnel's `context=` names the record an entry is about.
SNAPSHOT_KEYWORDS = {'snapshot', 'before', 'after', 'context'}

# A function that *builds* one of those values.
BUILDER_NAME_PARTS = ('snapshot', '_shape')

# A module-level tuple that names a writer's own fields outright.
AUDITED_CONSTANT_PREFIXES = ('_AUDITED', 'AUDITED')

# A module-level constant naming the (update schema, model) pair a
# payload-driven writer draws its snapshot keys from.
PAYLOAD_SCHEMA_DECLARATION = 'AUDIT_PAYLOAD_SCHEMA'

# The table, in ``schemas/_common.py``, of request fields written under a
# column of another name.
COLUMN_TABLE = '_COLUMN_FOR_FIELD'

# The funnel every module-owned configuration write goes through. Its `keys=`
# argument is the writer's key universe, so the call site is where that
# universe is readable — as a literal, or as a declaration in the same file.
CONFIG_FUNNEL = 'journal_config_change'


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ''


def _literal_keys_argument(node: ast.Call) -> list[str] | None:
    """The `keys=` universe when it is written out, `None` when it is not.

    A set/tuple/list of string literals is the writer naming its fields
    outright — as readable as a snapshot dict. Anything else (a call like
    `set(data.model_fields_set)`, a bare name, a missing argument) is the
    universe arriving from a payload, which only the file's declaration
    can speak for.
    """
    for keyword in node.keywords:
        if keyword.arg == 'keys':
            strings = constant_strings(keyword.value)
            if strings and len(strings) == len(getattr(keyword.value, 'elts', [])):
                return _without_reference_labels(strings)
            return None
    return None


def string_keys(node: ast.AST) -> list[str]:
    """The literal string keys of a dict expression, in source order.

    A `X_name` (or `X_code`) written beside its own `X_id` is not a field of
    the record — it is how that id reads, which the reader prints on the id's
    own line (`isReferenceLabel` in `frontend/src/modules/settings/utils/
    auditChanges.ts` drops exactly this shape). Exporting it would ask the
    catalogs to translate a word the journal never shows.
    """
    if not isinstance(node, ast.Dict):
        return []
    return _without_reference_labels(
        [
            key.value
            for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
    )


def _without_reference_labels(present: list[str]) -> list[str]:
    return [
        key
        for key in present
        if not (
            key.endswith(('_name', '_code'))
            and f'{key.rsplit("_", 1)[0]}_id' in present
        )
    ]


def returned_dict_keys(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Every literal key in a dict the function builds, at any depth.

    `item_to_snapshot` assigns its dict to a local and returns the name, so
    reading only `return {…}` would miss the twelve fields of the item
    snapshot — including three that matter most (`id`, `organization_id`,
    `is_deleted`).
    """
    return nested_dict_keys(func)


def nested_dict_keys(node: ast.AST) -> list[str]:
    """Literal keys of every dict inside *node*, one level of nesting included.

    A snapshot is a dict of dicts: `{'name': …, 'before': {'enabled': False}}`
    writes `enabled` into the journal, and reading only the top level is how
    the module toggle's row read `enabled: false → true` after this gate was
    already green. Recursing costs one line and closes that shape.
    """
    found: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Dict):
            found.extend(string_keys(child))
    return found


def constant_strings(node: ast.AST) -> list[str]:
    """The string items of a tuple/list/set expression."""
    if not isinstance(node, ast.Tuple | ast.List | ast.Set):
        return []
    return [
        item.value
        for item in node.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]


def _assign_targets(node: ast.Assign) -> list[str]:
    return [t.id for t in node.targets if isinstance(t, ast.Name)]


def _imports_of(tree: ast.AST, package: str) -> dict[str, str]:
    """The file's from-imports, as local name -> qualified name.

    Absolute imports qualify directly. Relative ones qualify the way Python
    does: one dot means the declaring file's own package, two its parent —
    and a router that imports its model with `from .models.profile import
    DocumentProfile` has to resolve through that, or its declaration names
    a class nothing in the tree defines and covers nothing.
    """
    imports: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module and node.level == 0:
            continue
        if node.level == 0:
            base = node.module or ''
        else:
            parts = package.split('.')
            anchor = parts[: len(parts) - (node.level - 1)]
            if not anchor:
                continue
            base = '.'.join([*anchor, node.module or ''])
        for alias in node.names:
            imports[alias.asname or alias.name] = f'{base}.{alias.name}'
    return imports


def _read_call(node: ast.Call, keys: set[str]) -> bool:
    """One call site's contribution to the artefact.

    Snapshot keywords are harvested into `keys`; a funnel call answers
    whether it cuts its `keys=` from something no literal names (the
    state that makes the declaring file uncovered).
    """
    dynamic_funnel_keys = False
    for keyword in node.keywords:
        if keyword.arg in SNAPSHOT_KEYWORDS:
            keys.update(nested_dict_keys(keyword.value))
    if _call_name(node) == CONFIG_FUNNEL:
        funnel_keys = _literal_keys_argument(node)
        if funnel_keys is None:
            dynamic_funnel_keys = True
        else:
            keys.update(funnel_keys)
    return dynamic_funnel_keys


def collect(
    tree: ast.AST, module: str, package: str
) -> tuple[set[str], list[tuple[str, str]], bool, dict[str, str]]:
    """The literal keys of one file, its payload declarations, its funnel,
    its imports.

    The boolean answers whether this file cuts a funnel writer's `keys=`
    from something no literal names — the state that makes the file
    uncovered unless one of its declarations resolves.
    """
    keys: set[str] = set()
    declarations: list[tuple[str, str]] = []
    dynamic_funnel_keys = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dynamic_funnel_keys = _read_call(node, keys) or dynamic_funnel_keys
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if any(part in node.name for part in BUILDER_NAME_PARTS):
                keys.update(returned_dict_keys(node))
        elif isinstance(node, ast.Assign):
            for name in _assign_targets(node):
                if name.startswith(AUDITED_CONSTANT_PREFIXES):
                    keys.update(constant_strings(node.value))
                elif 'SNAPSHOT' in name.upper():
                    keys.update(nested_dict_keys(node.value))
                elif name == PAYLOAD_SCHEMA_DECLARATION:
                    pair = constant_strings(node.value)
                    if len(pair) == 2:
                        declarations.append((pair[0], pair[1]))

    # A name the file defines itself resolves to its own module.
    imports = _imports_of(tree, package)

    def qualified(local: str) -> str:
        return imports.get(local, f'{module}.{local}')

    resolved = [(qualified(a), qualified(b)) for a, b in declarations]
    return keys, resolved, dynamic_funnel_keys, imports


def annotated_class_fields(tree: ast.AST, module: str) -> dict[str, set[str]]:
    """The annotated class-body fields of every class in one file.

    Pydantic schemas and SQLAlchemy models declare their fields the same way
    — a class-level ``name: Type = …`` — so one reader serves both sides of
    the intersection a payload writer's ``hasattr`` performs. Keys are
    qualified (``app.models.item.Item``), because one name can carry two
    classes in two modules.
    """
    fields: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        found = fields.setdefault(f'{module}.{node.name}', set())
        for statement in node.body:
            if not isinstance(statement, ast.AnnAssign):
                continue
            if not isinstance(statement.target, ast.Name):
                continue
            if statement.target.id.startswith('_'):
                continue
            annotation = (
                ast.unparse(statement.annotation) if statement.annotation else ''
            )
            if 'ClassVar' in annotation:
                continue
            found.add(statement.target.id)
    return fields


# The artefact's key names carry dashes (they are the JSON contract with the
# frontend half of the gate), so the functional TypedDict syntax it is.
CollectedKeys = TypedDict(
    'CollectedKeys',
    {
        'files-read': int,
        'declarations-read': int,
        'uncovered-writer-files': list[str],
        'keys': list[str],
    },
)


def column_for_field(root: Path) -> dict[str, str]:
    """The request fields a payload writer journals under another name.

    A payload is dumped keyed by column (``keyed_by_column`` in
    ``schemas/_common.py``): the API's ``location_id`` is written, and
    journalled, as the ``storage_location_id`` column. The table is read from
    source like everything else here.
    """
    source = root / 'schemas' / '_common.py'
    if not source.exists():
        return {}
    for node in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == COLUMN_TABLE
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    return {}


def collect_keys(root: Path) -> CollectedKeys:
    """The artefact payload for one application tree."""
    keys: set[str] = set()
    class_fields: dict[str, set[str]] = {}
    declarations: list[tuple[str, str]] = []
    funnel_files: list[str] = []
    aliases: dict[str, str] = {}
    files = 0
    for path in sorted(root.rglob('*.py')):
        if 'tests' in path.parts or '__pycache__' in path.parts:
            continue
        # architecture_lint writes gate artefacts, never journal records, and
        # its snapshot builders are named `build_snapshot` — which is exactly
        # what BUILDER_NAME_PARTS looks for. Their returned dicts describe the
        # shape of a JSON file (`namespaces`, `methods`, `params`, `class`),
        # so every key harvested from them arrives here demanding five
        # catalogue entries for a name no reader will ever see. Same reasoning
        # as the `before`/`after` subtraction below: structure, not record.
        if 'architecture_lint' in path.parts:
            continue
        relative = path.relative_to(root)
        parts = list(relative.with_suffix('').parts)
        if parts[-1] == '__init__':
            module = '.'.join(['app'] + parts[:-1])
            package = module
        else:
            module = '.'.join(['app'] + parts)
            package = module.rpartition('.')[0] or module
        tree = ast.parse(path.read_text(encoding='utf-8'))
        tree_keys, file_declarations, dynamic_funnel_keys, file_imports = collect(
            tree, module, package
        )
        keys.update(tree_keys)
        for name, fields in annotated_class_fields(tree, module).items():
            class_fields.setdefault(name, set()).update(fields)
        declarations.extend(file_declarations)
        if dynamic_funnel_keys:
            funnel_files.append((module, file_declarations))
        # Every from-import is also a public name of its own module pointing
        # at the imported one — the shape of a re-export (`schemas.py`
        # re-exporting a class from `_schemas_profile`). Chasing these is
        # how a writer importing from the public path resolves to the same
        # class a direct import would.
        for local, qualified in file_imports.items():
            aliases[f'{module}.{local}'] = qualified
        files += 1

    # A payload writer's keys are the fields its update schema and its model
    # share — the writer's `hasattr` drops the rest. Resolved after the walk,
    # because the declaration and the classes it names live in different
    # files. Resolution follows re-exports: a name that is not a class
    # itself may be a module's public alias for one.
    def resolve(name: str) -> str:
        seen: set[str] = set()
        while name not in class_fields and name in aliases and name not in seen:
            seen.add(name)
            name = aliases[name]
        return name

    # The schema's side is translated to the columns first: a field the API
    # names apart from its column reaches the model under the column's name
    # (the model's synonym for it is how a client's name gets there, not a
    # key the journal shows).
    columns = column_for_field(root)
    for schema_name, model_name in declarations:
        schema_keys = {
            columns.get(field, field)
            for field in class_fields.get(resolve(schema_name), set())
        }
        keys.update(schema_keys & class_fields.get(resolve(model_name), set()))

    # A funnel writer with dynamic keys is covered only by a declaration
    # whose two names both resolve to classes the tree defines — a typo in
    # the pair would otherwise read as cover while the writer's universe
    # went unread.
    uncovered = sorted(
        module
        for module, pairs in funnel_files
        if not any(
            resolve(schema_name) in class_fields and resolve(model_name) in class_fields
            for schema_name, model_name in pairs
        )
    )

    # The two sides are the envelope's own names, not a field of the record.
    # They are excluded here because no catalogue entry could ever be right
    # for them: the reader is being shown the journal's structure, not the
    # record's.
    keys -= {'before', 'after'}

    return {
        'files-read': files,
        'declarations-read': len(declarations),
        'uncovered-writer-files': uncovered,
        'keys': sorted(keys),
    }


def artefact_payload(collected: dict) -> dict:
    """The saved artefact for what ``collect_keys`` read."""
    keys = collected['keys']
    return {
        'generated-by': 'backend/scripts/export_audit_snapshot_keys.py',
        'note': (
            'Field names the backend declares for audit snapshots — literal '
            'snapshot keys, the schema/model intersections its payload-driven '
            'writers declare via AUDIT_PAYLOAD_SCHEMA, and the literal key '
            'sets of the journal_config_change funnel. Refresh with make '
            'sync-audit-fields; do not edit by hand.'
        ),
        # How many files were read is left out: it grows with every new file
        # in app/, which no gate compares, so the saved artefact would go
        # stale on its own. The --out message still prints it.
        # Saved, not only counted: a green gate has to say how many writers
        # it read declarations from, so a writer without a declaration is
        # visible as a fall in this number instead of indistinguishable from
        # no writer at all.
        'declarations-read': collected['declarations-read'],
        # The funnel writers the artefact could not read: the frontend half of
        # the gate refuses this list, so an undeclared payload writer is a red
        # gate rather than a silent gap.
        'uncovered-writer-files': collected['uncovered-writer-files'],
        'key-count': len(keys),
        'keys': keys,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--out',
        type=Path,
        default=None,
        help='write the artefact here instead of to stdout',
    )
    args = parser.parse_args()

    collected = collect_keys(APP_ROOT)
    keys = collected['keys']
    files = collected['files-read']

    payload = artefact_payload(collected)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + '\n'
    if args.out:
        args.out.write_text(text, encoding='utf-8')
        print(f'audit snapshot keys: {len(keys)} from {files} file(s) -> {args.out}')
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
