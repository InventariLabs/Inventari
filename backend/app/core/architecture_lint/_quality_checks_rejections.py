"""Raw-ValueError-sentence scan shared by the rejection gate and its ledger
generator.

The gate (``tests/unit/test_service_rejection_messages_i18n.py``) refuses a
plain ``ValueError`` sentence in any non-test module unless its literal sits
in the ledger (``app/core/value_error_sentences_baseline.txt`` — inside ``CORE_DIR``,
so the baseline ratchet sees it: growing the ledger is an act, never a
one-line edit riding a green build). The generator rewrites the ledger's
entries from the tree; both read the scan from this one module so they
cannot drift.

The ledger is debt, not permission. Its header documents the reachability
split; the groups below are the machine-readable side of the same
classification.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

from ._constants import _is_test_file, _rel_parts

#: The ledger file. Inside ``CORE_DIR`` so the baseline ratchet
#: (``--write-baseline-sizes`` / ``TestRealTreeIsRatcheted``) sees it: an
#: appended line grows the count and fails the build until the ratchet is
#: consciously lowered.
REJECTION_LEDGER_FILE = (
    Path(__file__).resolve().parents[1] / 'value_error_sentences_baseline.txt'
)

#: Ledger of the refusals the ValueError rule never looks at: service-denial
#: exceptions and HTTP exceptions that carry a sentence instead of a key.
#: Same format, same ratchet (it sits in ``CORE_DIR``), same debt-not-permission
#: contract as the ValueError ledger.
REFUSAL_LEDGER_FILE = (
    Path(__file__).resolve().parents[1] / 'refusal_sentences_baseline.txt'
)

#: Roots of the refusal family. A raise is a refusal when the class it raises
#: IS one of these or descends from one through ``app/``'s own class
#: definitions — the provenance rule ``is_reader_facing_value_error`` applies
#: at runtime, so the set needs no registry that can drift. Plain
#: ``ValueError`` is not a root of its own raises: it has its own rule and
#: ledger above; only its *subclasses* count here.
REFUSAL_ROOTS: frozenset[str] = frozenset(
    {'ValueError', 'HTTPException', 'AppException', 'PermissionError'}
)

#: Classes excluded BY NAME, each with the reason — the exclusion is the
#: visible thing, never the inclusion. Subclasses of an excluded class are
#: excluded with it.
REFUSAL_EXCLUDED: dict[str, str] = {
    'ServiceRejectionError': (
        'carries a translation key by contract; the key is the message, and'
        ' the handler resolves it per reader'
    ),
    'UndecryptableSecretError': (
        'its message tells an operator which key or salt rotated and is written'
        ' for the log and the secrets CLI; the class is not reader-facing at'
        ' runtime (``reader_facing = False``), so an uncaught one is answered'
        ' with the generic translated sentence'
    ),
    'ModuleSecretBindingError': (
        'names the module that asked for a secret it does not own and is written'
        ' for the log and the secrets CLI; the class is not reader-facing at'
        ' runtime (``reader_facing = False``)'
    ),
    'OperatorError': (
        'its message is written for whoever runs a command or starts the'
        ' process (boot, ``manage.py``, manifest and seed-profile validation);'
        ' no request reaches it and the class is not reader-facing at runtime'
        ' (``reader_facing = False``)'
    ),
    'LlmContractError': (
        'its message quotes what a model sent and is written for the log; the'
        ' class is not reader-facing at runtime (``reader_facing = False``),'
        ' so an uncaught one is answered with the generic translated sentence'
    ),
}


def refusal_class_names(trees: list[tuple[str, ast.AST]]) -> frozenset[str]:
    """Names of every class a raise can use to refuse a reader.

    Builds the ``name -> bases`` graph from the class definitions in *trees*
    and keeps the ones that reach :data:`REFUSAL_ROOTS`, minus
    :data:`REFUSAL_EXCLUDED` and its descendants. Matching is by bare name,
    the way :func:`_raised_name` reads a raise site.
    """
    bases: dict[str, set[str]] = {}
    for _, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names = bases.setdefault(node.name, set())
                for base in node.bases:
                    target = base.value if isinstance(base, ast.Subscript) else base
                    if isinstance(target, ast.Name):
                        names.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        names.add(target.attr)

    def reaches(name: str, goals: frozenset[str], seen: frozenset[str]) -> bool:
        if name in goals:
            return True
        if name in seen:
            return False
        return any(reaches(b, goals, seen | {name}) for b in bases.get(name, ()))

    excluded = frozenset(REFUSAL_EXCLUDED)
    found = {
        name
        for name in bases
        if name != 'ValueError'
        and reaches(name, REFUSAL_ROOTS, frozenset())
        and not reaches(name, excluded, frozenset())
    }
    return frozenset(found | (REFUSAL_ROOTS - {'ValueError'}))


#: Reachability groups, most specific prefix first. Each entry is assigned
#: to the first group whose prefix matches its repo-relative path. The
#: split is per reachable mechanism, not per directory vibe — the reviewer
#: measured a sentence in ``app/core/contracts`` reaching a client (through
#: the 422 validator envelope), so "core" alone is not a group.
REJECTION_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        'client-400',
        (
            'raised inside request handling; the global 400 handler maps it to'
            ' a client toast. Pending keyed migration (ServiceRejectionError),'
            ' the way maker/production_service was migrated'
        ),
        ('app/modules/', 'app/services/', 'app/api/'),
    ),
    (
        'client-422',
        (
            'Pydantic validator refusals: they reach the client through the'
            ' 422 RequestValidationError envelope, which is a different path'
            ' than the 400 envelope this gate guards — raw English here is'
            ' real, tracked debt of the 422 class'
        ),
        ('app/schemas/', 'app/models/', 'app/core/contracts/'),
    ),
    (
        'client-guards',
        (
            'core guards that fire during requests (imports, uploads, SSRF'
            ' checks, settings saves): they can reach the 400 envelope the'
            ' same way group one does, and head for the same keyed migration'
        ),
        (
            'app/core/ssrf_guard.py',
            'app/core/file_import.py',
            'app/core/import_sheet.py',
            'app/core/upload_validation.py',
            'app/core/product_profiles.py',
            'app/core/product_template_metadata.py',
            'app/core/db_utils.py',
            'app/core/file_storage/',
            'app/core/settings_validator.py',
            'app/core/scoped_session.py',
            'app/core/token_blacklist.py',
            'app/core/llm/',
            'app/core/public_api/',
        ),
    ),
    (
        'internal-invariant',
        (
            "a guard on a caller's mistake or on a model's malformed answer:"
            ' no request supplies the value, so no reader is meant to see the'
            ' sentence. Kept as a plain ``ValueError`` on purpose — the 400'
            ' handler logs a plain one with its traceback, which is what a'
            ' defect wearing a 400 should leave. Assigned per entry, never by'
            ' path'
        ),
        (),
    ),
)


#: First line of the generated block. Everything above it is prose owned by
#: people; the generator replaces everything from here down, which is what
#: keeps a rewrite idempotent — collecting *all* leading comments as prose
#: swallowed the previous block and appended a second one beside it.
COUNTS_BEGIN = '# BEGIN COUNTS (generated — do not edit by hand)'
COUNTS_END = '# END COUNTS (generated)'


def escape_literal(text: str) -> str:
    """Make any scanned literal a single ledger line without losing it.

    Backslash first, then the newlines; everything else (quotes, dashes,
    non-ASCII) stays readable as-is.
    """
    return text.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r')


def unescape_literal(text: str) -> str:
    inverse: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == 'n':
                inverse.append('\n')
                i += 2
                continue
            if nxt == 'r':
                inverse.append('\r')
                i += 2
                continue
            if nxt == '\\':
                inverse.append('\\')
                i += 2
                continue
        inverse.append(ch)
        i += 1
    return ''.join(inverse)


def is_key_or_code(literal: str) -> bool:
    """True for i18n keys (snake_case) and machine codes (ALL_CAPS).

    Any other literal at a raise site is a user-facing sentence written in
    English at the raise site — exactly the pattern the gate exists to stop.
    """
    if not literal:
        return True
    if not any(c.isalnum() for c in literal):
        return True  # join separators (", ") and the like — not messages
    if literal.lower() != literal and literal.upper() != literal:
        return False  # mixed case — a sentence fragment
    return all(c.isalnum() or c == '_' for c in literal)


def is_plain_value_error(exc: ast.expr) -> bool:
    """True when the raised exception is literally ``ValueError``.

    The global 400 handler maps ``ValueError`` itself (keyed rejections are
    the sanctioned alternative); subclasses carry their own routers or
    handlers and are out of this rule's scope.
    """
    target = exc.func if isinstance(exc, ast.Call) else exc
    return isinstance(target, ast.Name) and target.id == 'ValueError'


def sentence_constants(exc: ast.expr) -> list[str]:
    """Sentence-shaped string literals inside one ``raise`` expression.

    Covers plain constants and the constant parts of f-strings, so
    ``raise ValueError(f'... {x} ...')`` is covered too.
    """
    return [
        child.value
        for child in ast.walk(exc)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and not is_key_or_code(child.value)
    ]


def _app_trees(app_root: Path) -> list[tuple[str, ast.AST]]:
    """Parse every non-test ``app/`` module once, as (repo-relative, tree)."""
    pairs: list[tuple[str, ast.AST]] = []
    for py_file in sorted(app_root.rglob('*.py')):
        if _is_test_file(py_file, app_root) or '__pycache__' in _rel_parts(
            py_file, app_root
        ):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = py_file.relative_to(app_root.parent).as_posix()
        pairs.append((rel, tree))
    return pairs


def raw_value_error_sentence_entries(app_root: Path) -> set[str]:
    """Every ``relpath::literal`` the gate's rule flags in *app_root*.

    Literals are RAW (newlines as real newlines) — the same form the gate's
    ledger loader produces after unescaping. One scan, two readers: the
    gate subtracts the ledger from this set (fresh findings fail), the
    generator writes this set into the ledger, escaping only at write time
    so a ledger stays one line per entry.
    """
    entries: set[str] = set()
    for rel, tree in _app_trees(app_root):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            if not is_plain_value_error(node.exc):
                continue
            for literal in sentence_constants(node.exc):
                entries.add(f'{rel}::{literal}')
    return entries


def _raised_name(exc: ast.expr) -> str | None:
    target = exc.func if isinstance(exc, ast.Call) else exc
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def raw_refusal_sentence_entries(app_root: Path) -> set[str]:
    """Every ``relpath::literal`` a refusal exception carries as a sentence.

    The ValueError scan sees only ``raise ValueError('...')``. A service that
    refuses with ``PeriodClosedError('...')`` or a router with
    ``HTTPException(detail='...')`` reaches the reader just the same, and
    neither was ever asked whether the refusal carries a translation key.
    Machine codes (``'PERIOD_CLOSED'``) and snake_case keys pass; anything with
    a space or mixed case is a sentence. Keyword names such as ``code=`` do not
    appear in the AST as constants, so only values are inspected.
    """
    entries: set[str] = set()
    trees = _app_trees(app_root)
    refusal_names = refusal_class_names(trees)
    for rel, tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            if _raised_name(node.exc) not in refusal_names:
                continue
            exc = node.exc
            if isinstance(exc, ast.Call):
                # ``headers=`` carries protocol tokens (Bearer, WWW-Authenticate),
                # not a message.
                exc = ast.Call(
                    func=exc.func,
                    args=exc.args,
                    keywords=[k for k in exc.keywords if k.arg != 'headers'],
                )
            for literal in sentence_constants(exc):
                entries.add(f'{rel}::{literal}')
    return entries


def keyed_dynamic_value_error_entries(app_root: Path) -> set[str]:
    """``relpath::keyed:<what>`` for raises the catalogue already translates.

    ``raise ValueError(get_error_message('key', lang))`` (and the ``*.translated``
    shape) is a refusal whose message lives in the i18n catalogue, but its
    argument is a call, not a literal — invisible to the raw-sentence scan,
    which is why the ledger's count used to read as a floor, not a total.
    The entry names the key when the key is written as a literal, and the
    helper's name when it is not, so a reader can find the site either way.
    These entries are classification, not debt: they never belong in the
    ledger, and no gate asks them to.

    Known limit, named rather than hidden: a message built *around* a keyed
    fragment (``get_error_message('k', lang) + ' extra'``) is neither a raw
    sentence nor a pure keyed call — neither scan sees it.
    """
    entries: set[str] = set()
    for rel, tree in _app_trees(app_root):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            if not (isinstance(node.exc, ast.Call) and is_plain_value_error(node.exc)):
                continue
            if not node.exc.args:
                continue
            first = node.exc.args[0]
            if not isinstance(first, ast.Call):
                continue
            func = first.func
            is_get_error = isinstance(func, ast.Name) and (func.id in _KEYED_CALL_NAMES)
            is_translated = isinstance(func, ast.Attribute) and (
                func.attr in _KEYED_CALL_NAMES
            )
            if not (is_get_error or is_translated):
                continue
            if isinstance(func, ast.Name):
                helper = func.id
            elif isinstance(func, ast.Attribute):
                helper = func.attr
            else:
                continue
            key = ''
            if first.args and isinstance(first.args[0], ast.Constant):
                value = first.args[0].value
                if isinstance(value, str):
                    key = value
            entries.add(f'{rel}::keyed:{key or helper}')
    return entries


def rejection_group(rel_path: str) -> str:
    """The reachability group a ledger entry's file belongs to."""
    for name, _reason, prefixes in REJECTION_GROUPS:
        if any(rel_path.startswith(prefix) for prefix in prefixes):
            return name
    return 'unclassified'


#: Per-entry overrides, consulted before the path rule. The rule leans per
#: path, and the lean is wrong at a few named places: a raise inside a
#: Pydantic validator (``@model_validator`` / ``@field_validator``) in an
#: ``app/api/`` module refuses through the 422 RequestValidationError
#: envelope, not the 400 handler its directory's group describes. Keyed by
#: the full ``relpath::literal`` entry so an override cannot silently
#: re-file a file's other sentences.
REJECTION_GROUP_OVERRIDES: dict[str, str] = {
    'app/api/organizations.py::Provide exactly one of role or role_id': 'client-422',
    'app/api/stock_lots.py::reason must not be blank': 'client-422',
    # Not a validator, whatever the directory leans: the Numeric type's bind
    # guard fires on ORM writes that skip the schemas, like the bulk import —
    # the 400 handler answers that one.
    'app/models/item.py::expected a finite number, got ': 'client-guards',
    # Pydantic validators in module schemas: they refuse through the 422
    # envelope, whatever the module directory leans. Raw English that stays
    # until the validators raise keyed rejections the way the 422 handler
    # already knows how to translate.
    **{
        f'{path}::{literal}': 'client-422'
        for path, literals in {
            'app/modules/equipment/_schemas_equipment.py': (
                'name must not contain null bytes',
            ),
            'app/modules/purchase_orders/schemas.py': (
                'Provide product_template_id or name',
            ),
            'app/modules/recipes/_schemas_admin.py': (
                '. Use #RGB or #RRGGBB format.',
                'Invalid hex color ',
            ),
            'app/modules/recipes/_schemas_picking.py': (
                'servings must be <= ',
                'servings must be >= 1',
            ),
            'app/modules/recipes/_schemas_recipe.py': (
                'Unknown allergen keys: ',
                'image_source_url must be an http(s) URL',
                'image_url must be a valid URL or relative path',
                'name must not contain null bytes',
                'source_url must be an http(s) URL',
            ),
            'app/modules/warehouse/_schemas_profile.py': (
                'tax_handling must be NONE, SIMPLE_RATE, or PER_LINE_RATE',
                'type_labels keys must be IN, OUT, INT, INTERNAL_IN,'
                ' INTERNAL_OUT, ADJUSTMENT, CORRECTION, or SCRAP; got ',
            ),
            'app/modules/warehouse/putaway_schemas.py': (
                'At least one of product_template_id, category_id, context_tag,'
                ' storage_type_code must be set.',
                'Provide location_ids (ordered) or target_location_id.',
                'location_ids must not repeat a location.',
            ),
            'app/modules/warehouse/schemas.py': (
                'Correction reason is required',
                'Invalid type. Allowed: ',
                'Provide item_id, product_template_id, or at least a name',
                'Return reason is required',
                'Use POST /warehouse/corrections to create correction documents',
                'must not contain null bytes',
                'notes must not contain null bytes',
            ),
            'app/modules/webhooks/schemas.py': (
                '. Valid values: ',
                'Unknown event type(s): ',
            ),
        }.items()
        for literal in literals
    },
    # Guards on a caller's mistake or a model's malformed answer; no request
    # supplies the value (see the ``internal-invariant`` group).
    **{
        f'{path}::{literal}': 'internal-invariant'
        for path, literals in {
            # The module registry is declared in code; a cycle is a manifest bug.
            'app/api/modules.py': ('Circular dependency detected: ',),
            # The organization id comes from the signed-in user, never typed.
            'app/services/analytics/_common.py': (
                ' has no currency configured',
                'Organization ',
            ),
            'app/services/module_service.py': (' not found', 'Organization '),
            # Caller-supplied constants, checked as programming errors.
            'app/services/crypto_service.py': ('module name must not contain a colon',),
            # The module name is a constant in the router ('nutrition'); the
            # router answers any ValueError with the generic model-failure text.
            'app/modules/vision/service.py': (
                'No label fields are registered by module "',
            ),
        }.items()
        for literal in literals
    },
}


def rejection_group_for_entry(entry: str) -> str:
    """The reachability group a ledger entry belongs to.

    The per-entry override is consulted before the path rule, so an entry
    whose reachable mechanism differs from its directory's leaning is
    filed by the mechanism.
    """
    overridden = REJECTION_GROUP_OVERRIDES.get(entry)
    if overridden is not None:
        return overridden
    return rejection_group(entry.split('::', 1)[0])


def counts_by_group(entries: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {name: 0 for name, _r, _p in REJECTION_GROUPS}
    counts['unclassified'] = 0
    for entry in entries:
        counts[rejection_group_for_entry(entry)] += 1
    return counts


def ledger_entries(ledger_file: Path) -> set[str]:
    """The ``relpath::literal`` pairs a ledger permits, literals unescaped.

    Only the newline is stripped from a raw line: f-string fragments often
    begin or end with a space (``' not found'``), and stripping would make
    the line stop matching the scanned literal. Comments — the contract
    prose and the generated counts block — are not entries.

    The gate reads the ledger through here and the generator writes it
    through :func:`write_rejection_ledger`, so the two halves of the format
    cannot drift apart.
    """
    if not ledger_file.exists():
        return set()
    entries: set[str] = set()
    for line in ledger_file.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        rel, sep, escaped = line.partition('::')
        if not sep:
            raise AssertionError(f'ledger line without "::" separator: {line!r}')
        entries.add(f'{rel}::{unescape_literal(escaped)}')
    return entries


#: Groups a client can read through. A NEW raw sentence in one of these is
#: not debt the ledger may take on — it is the exact class the keyed
#: migration exists for, and the ledger's own header names the rule. Existing
#: entries stay (the debt already on the books is what the ledger counts);
#: it is only the *first* entry of a sentence that the generator refuses.
CLIENT_FACING_GROUPS: frozenset[str] = frozenset(
    {'client-400', 'client-422', 'client-guards'}
)

#: Calls whose return value is already a catalogue message. A ``raise
#: ValueError(get_error_message('key', lang))`` carries no sentence literal,
#: so the raw scan cannot see it — counted separately so the ledger's
#: numbers stop reading as a lower bound of the refusal surface.
_KEYED_CALL_NAMES = ('get_error_message', 'get_plural_error_message', 'translated')


class LedgerRewrite(NamedTuple):
    """What one regeneration did, in the terms a reader needs to check it."""

    counts: dict[str, int]
    added: list[str]
    removed: list[str]
    #: New client-facing sentences the regeneration REFUSED to ledger. When
    #: this is non-empty the ledger on disk is left exactly as it was and the
    #: caller is expected to fail the build: these sites must raise
    #: ``ServiceRejectionError('<key>')`` instead.
    refused: list[str]


def write_refusal_ledger(app_root: Path, ledger_file: Path) -> LedgerRewrite:
    """Regenerate the refusal ledger; a NEW sentence is refused, not ledgered.

    Unlike the ValueError ledger there are no reachability groups: every
    exception :func:`refusal_class_names` yields is raised to be read.
    """
    entries = raw_refusal_sentence_entries(app_root)
    previous = ledger_entries(ledger_file)
    # An empty ledger is the first generation: it takes the debt as it stands.
    refused = sorted(entries - previous) if previous else []
    counts = {'refusals': len(entries)}
    if refused:
        return LedgerRewrite(counts=counts, added=[], removed=[], refused=refused)

    prose: list[str] = []
    if ledger_file.exists():
        for line in ledger_file.read_text(encoding='utf-8').splitlines():
            if line == COUNTS_BEGIN or not line.startswith('#'):
                break
            prose.append(line)
    lines = [*prose, COUNTS_BEGIN, f'# Refusals: {len(entries)}.', COUNTS_END]
    lines.extend(
        sorted(
            f'{rel}::{escape_literal(literal)}'
            for rel, _, literal in (e.partition('::') for e in entries)
        )
    )
    ledger_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return LedgerRewrite(
        counts=counts,
        added=sorted(entries - previous),
        removed=sorted(previous - entries),
        refused=[],
    )


def write_rejection_ledger(app_root: Path, ledger_file: Path) -> LedgerRewrite:
    """Regenerate the ledger's entries; the hand-written prose stays.

    Everything up to the counts marker is prose owned by people (the
    contract and the group definitions); everything from that marker on is
    regenerated — the counts line, then one entry per line. Reading the old
    file first is what lets the command say which debt it took on and which
    it retired; a regeneration that only printed totals asked its reader to
    trust a number.
    """
    entries = raw_value_error_sentence_entries(app_root)
    previous = ledger_entries(ledger_file)
    counts = counts_by_group(entries)
    counts['keyed-dynamic'] = len(keyed_dynamic_value_error_entries(app_root))

    # A NEW client-facing sentence may not enter the ledger, switch or no
    # switch: the ledger's own header says the class is headed for a key,
    # and a regeneration that wrote it would turn the debt counter into the
    # very door the debt walks in through (measured: f3f4f9dad, two putaway
    # validator sentences, 424 -> 426, one evening, no switch abused). The
    # ledger on disk is left untouched and the caller fails the build.
    refused = sorted(
        entry
        for entry in entries - previous
        if rejection_group_for_entry(entry) in CLIENT_FACING_GROUPS
    )
    if refused:
        return LedgerRewrite(counts=counts, added=[], removed=[], refused=refused)

    prose: list[str] = []
    if ledger_file.exists():
        for line in ledger_file.read_text(encoding='utf-8').splitlines():
            if line == COUNTS_BEGIN or not line.startswith('#'):
                break
            prose.append(line)

    lines = list(prose)
    lines.append(COUNTS_BEGIN)
    lines.append(
        '# Counts by reachability group: '
        + ', '.join(f'{name} {count}' for name, count in counts.items())
        + '.'
    )
    lines.append(COUNTS_END)

    def _split(entry: str) -> tuple[str, str]:
        rel, _, literal = entry.partition('::')
        return rel, literal

    lines.extend(
        sorted(
            f'{rel}::{escape_literal(literal)}' for rel, literal in map(_split, entries)
        )
    )
    ledger_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return LedgerRewrite(
        counts=counts,
        added=sorted(entries - previous),
        removed=sorted(previous - entries),
        refused=[],
    )
