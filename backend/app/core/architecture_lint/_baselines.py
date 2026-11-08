from __future__ import annotations

from datetime import date
from pathlib import Path

from ._constants import (
    AUDIT_COVERAGE_BASELINE_FILE,
    BARE_EMIT_BASELINE_FILE,
    CORE_API_MODEL_LEAK_BASELINE_FILE,
    COREAPI_SIGNATURE_LEGALITY_BASELINE_FILE,
    COREAPI_WRITE_USER_CONTEXT_BASELINE_FILE,
    ESCAPE_HATCH_ORG_FILTER_BASELINE_FILE,
    ESCAPE_HATCH_QUERY_SCOPE_BASELINE_FILE,
    GET_DB_BASELINE_FILE,
    MANIFEST_PERMISSION_DEFERRALS_FILE,
    MIXED_STATUS_ASSERT_BASELINE_FILE,
    MODULE_IMPORT_SURFACE_BASELINE_FILE,
    MODULE_MIGRATIONS_BASELINE_FILE,
    PUBLIC_API_MISSING_ORG_BASELINE_FILE,
    RAW_HTTP_EXCEPTION_BASELINE_FILE,
    REQUEST_SCOPE_BASELINE_FILE,
    SERVICES_PUBLIC_API_IMPORT_BASELINE_FILE,
    SYNC_ASYNC_TWIN_BASELINE_FILE,
    TEST_SKIP_BASELINE_FILE,
    TOCTOU_RISK_BASELINE_FILE,
    TRANSACTION_OWNER_ALLOWLIST_FILE,
    TRANSACTION_OWNERSHIP_BASELINE_FILE,
    TRANSACTION_ROLLBACK_BASELINE_FILE,
    UNREAD_ORG_PARAMETER_BASELINE_FILE,
)


def _load_baseline(baseline_file: Path | None) -> set[str]:
    if baseline_file is None or not baseline_file.exists():
        return set()

    lines = baseline_file.read_text(encoding='utf-8').splitlines()
    return {
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith('#')
    }


def _write_baseline(
    baseline_file: Path,
    keys: set[str],
    key_format: str = 'relative/path.py::import.path',
) -> None:
    """Write a key list, saying in the file itself what a key looks like.

    The format line is a parameter because not every baseline holds import
    paths, and a header that describes the wrong shape is worse than none:
    the next reader trusts it.
    """
    content = [
        '# Architecture lint baseline',
        f'# Format: {key_format}',
    ]
    content.extend(sorted(keys))
    baseline_file.write_text('\n'.join(content) + '\n', encoding='utf-8')


def _load_bare_emit_baseline() -> set[str]:
    """Emit call sites that were already here when the ratchet went in.

    A plain key list, not a dated-premise list: these are not judgement
    calls anybody made, they are what the tree happened to contain. The
    number only ever goes down, and every entry that leaves is one place
    where the event and the data commit together.
    """
    return _load_baseline(BARE_EMIT_BASELINE_FILE)


def _load_mixed_status_assert_baseline() -> set[str]:
    """Assertions taking a 2xx and a 4xx at once, grandfathered by name.

    Keyed ``path::test_name``, and empty — the only state this list should
    ever be in. It opened with two entries whose tests were being deleted on
    another branch, and emptied the day that branch landed. A new entry is a
    decision to keep an assertion that cannot fail, and the size ratchet
    turns that decision into a one-line diff somebody has to approve.
    """
    return _load_baseline(MIXED_STATUS_ASSERT_BASELINE_FILE)


def _load_request_scope_baseline() -> set[str]:
    """Endpoints that are global by design, written down rather than assumed.

    Superuser views that span tenants, everything that runs before a
    session exists, and the public pages reached by a signed token. A
    plain key list: these are not deferred fixes, they are the answer to
    "which endpoints have no organization", and it should be short.
    """
    return _load_baseline(REQUEST_SCOPE_BASELINE_FILE)


def _load_raw_http_exception_baseline() -> set[str]:
    """Raw ``raise HTTPException`` sites accepted until their conversion.

    Keyed ``path::qualname@N`` — the Nth raw raise inside that function.
    The list only ever gets shorter: each site that moves to a typed
    ``AppException`` removes exactly its line, and a second raw raise added
    to a baselined function is a new, uncovered site.
    """
    return _load_baseline(RAW_HTTP_EXCEPTION_BASELINE_FILE)


def _load_get_db_baseline() -> set[str]:
    return _load_baseline(GET_DB_BASELINE_FILE)


def _load_module_migrations_baseline() -> set[str]:
    """Load the set of module names whose migration gaps are grandfathered."""
    return _load_baseline(MODULE_MIGRATIONS_BASELINE_FILE)


def _load_sync_async_twin_baseline() -> set[str]:
    return _load_baseline(SYNC_ASYNC_TWIN_BASELINE_FILE)


def _load_toctou_risk_baseline(
    today: date | None = None,
) -> tuple[set[str], list[str]]:
    """Select-then-mutate sites accepted for now, each with a dated premise.

    These entries carry the most convincing kind of wrong answer: a written
    justification nobody re-read. One of them said the only real race was
    serialised by an advisory lock which, when the sentence was written,
    hashed its key with Python's per-process ``hash()`` and serialised
    nothing. The entry was green, reviewed, and false. Hence the expiry: a
    premise has to be re-checked, not merely recorded.
    """
    return _load_owned_entries(
        TOCTOU_RISK_BASELINE_FILE,
        noun='TOCTOU baseline entry',
        today=today,
    )


def _parse_surface_block_header(
    raw: str, rel: str, lineno: int, today: date
) -> tuple[str | None, list[str]]:
    """Validate one ``<module> | owner= | expires= | reason`` line.

    Returns the module name and any errors. ``None`` means the block is void:
    its paths cannot be trusted to a module whose header is not a decision.
    """
    parts = [part.strip() for part in raw.split('|')]
    if len(parts) < 4 or not parts[3]:
        return None, [
            f'::error file=app/core/{rel},line={lineno},title=Architecture: '
            f'malformed module surface entry::'
            f'Expected "<module> | owner=<who> | expires=<YYYY-MM-DD> | '
            f'<reason>", got: {raw}'
        ]
    module, owner, expires = parts[0], parts[1], parts[2]
    if not owner.startswith('owner=') or len(owner) <= len('owner='):
        return None, [
            f'::error file=app/core/{rel},line={lineno},title=Architecture: '
            f'module surface entry without owner::'
            f"Entry '{module}' names nobody. Add owner=<who>."
        ]
    if not expires.startswith('expires='):
        return None, [
            f'::error file=app/core/{rel},line={lineno},title=Architecture: '
            f'module surface entry without expiry::'
            f"Entry '{module}' never expires. Add expires=<YYYY-MM-DD>."
        ]
    try:
        deadline = date.fromisoformat(expires[len('expires=') :])
    except ValueError:
        return None, [
            f'::error file=app/core/{rel},line={lineno},title=Architecture: '
            f'module surface entry with unreadable expiry::'
            f"Entry '{module}' has expires='{expires[len('expires=') :]}'; "
            f'expected YYYY-MM-DD.'
        ]
    if deadline < today:
        return None, [
            f'::error file=app/core/{rel},line={lineno},title=Architecture: '
            f'module surface entry expired::'
            f"Entry '{module}' expired on {deadline.isoformat()} — "
            f'{owner[len("owner=") :]} was to recheck the premise it rests on.'
        ]
    return module, []


def _load_module_import_surface_baseline(
    today: date | None = None,
) -> tuple[dict[str, set[str]], list[str]]:
    """App paths each shipped module still imports, per module, with a reason.

    Format, one block per module::

        <module> | owner=<who> | expires=<YYYY-MM-DD> | <reason>
          <app path>
          <app path>

    The unit is the module because the decision is one per module: it was
    written before ``app.core.module_sdk`` existed, so its files reach the
    core helpers they need directly — and another module through that
    module's public API — and the set of paths it reaches is frozen as it
    stands. The block lists every path, so a new import shows up twice — in
    the check and in this file's diff. Owner and expiry are mandatory for the
    same reason they are on every other suppression list: a known gap without
    either goes quiet, and a line that outlives its premise reads as a
    decision nobody is re-checking.
    """
    if not MODULE_IMPORT_SURFACE_BASELINE_FILE.exists():
        return {}, []

    today = today or date.today()
    rel = MODULE_IMPORT_SURFACE_BASELINE_FILE.name
    modules: dict[str, set[str]] = {}
    errors: list[str] = []
    current: str | None = None
    #: A header that failed above voids its block: the paths under it have
    #: already been answered for, and repeating "sits under no module line"
    #: for every one of them buries the one error that matters.
    voided = False

    for lineno, raw in enumerate(
        MODULE_IMPORT_SURFACE_BASELINE_FILE.read_text(encoding='utf-8').splitlines(),
        start=1,
    ):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if raw[:1].isspace():
            # A continuation line: one core path under the module above it.
            if voided:
                continue
            if current is None:
                errors.append(
                    f'::error file=app/core/{rel},line={lineno},title=Architecture: '
                    f'module surface entry without a module::'
                    f"'{line}' sits under no module line. Put it after a "
                    f'`<module> | owner=... | expires=... | <reason>` line.'
                )
                continue
            modules[current].add(line)
            continue

        module, header_errors = _parse_surface_block_header(raw, rel, lineno, today)
        errors.extend(header_errors)
        current = module
        voided = module is None
        if module is not None:
            modules.setdefault(module, set())

    return modules, errors


def _load_audit_coverage_baseline() -> tuple[set[str], list[str]]:
    """Write paths that reach no journal entry, each with a reason and a date.

    Two kinds share the list because the gate cannot tell them apart: a path
    that cannot journal by design (login runs before a session; a working
    note is nobody's record but its author's) and a path that simply lost its
    entry. The reason says which is which, and the expiry makes the decision
    come back.
    """
    return _load_owned_entries(
        AUDIT_COVERAGE_BASELINE_FILE,
        noun='audit coverage baseline entry',
    )


def _load_transaction_ownership_baseline() -> set[str]:
    """Mid-stack commit sites accepted until their conversion wave.

    One key per site, ``path::qualname@N`` — the Nth commit inside that
    function. The four conversions that came with the rule (storage
    delete, storage hierarchy, quant consumption, label scan) are NOT
    here; what is here still owes its commit to its caller.
    """
    return _load_baseline(TRANSACTION_OWNERSHIP_BASELINE_FILE)


def _load_services_public_api_import_baseline() -> set[str]:
    """Service places that still import the core_api facade, listed by place.

    Keyed ``path::Class::function``. What the tree held when the check went
    in, and nothing is ever added: the number goes down one place at a time,
    as each is rewired to import the service it calls directly — the
    one-number state model (ADR-022) pays the state-model share,
    the facades outside the state model are their own debt.
    """
    return _load_baseline(SERVICES_PUBLIC_API_IMPORT_BASELINE_FILE)


def _load_transaction_rollback_baseline() -> set[str]:
    """Mid-stack rollback sites accepted until their conversion wave.

    Same shape as the commit baseline; a rollback erases the caller's
    unit of work just as surely as a commit slices it.
    """
    return _load_baseline(TRANSACTION_ROLLBACK_BASELINE_FILE)


def _load_transaction_owner_allowlist() -> set[str]:
    """Functions that OWN their transaction and may commit/rollback freely.

    Function-level keys, ``path::qualname`` — background jobs, module
    routers holding their own session, seeds, CLI entry points, session
    wrappers, test helpers. A positive grant, deliberately not a
    ``*_baseline.txt``: growing the list of legal owners is not the gate
    covering less.
    """
    return _load_baseline(TRANSACTION_OWNER_ALLOWLIST_FILE)


def _load_core_api_model_leak_baseline() -> set[str]:
    return _load_baseline(CORE_API_MODEL_LEAK_BASELINE_FILE)


def _load_escape_hatch_org_filter_baseline() -> set[str]:
    return _load_baseline(ESCAPE_HATCH_ORG_FILTER_BASELINE_FILE)


def _load_escape_hatch_query_scope_baseline() -> tuple[set[str], list[str]]:
    """Per-query escape-hatch suppressions, each with an owner and an expiry.

    Unlike its file-level sibling this list names a single function, so an
    entry cannot quietly cover a query added next to it later.
    """
    return _load_owned_entries(
        ESCAPE_HATCH_QUERY_SCOPE_BASELINE_FILE,
        noun='escape-hatch query-scope baseline entry',
    )


def _load_public_api_missing_org_baseline() -> set[str]:
    """Methods grandfathered until their org parameter lands."""
    return _load_baseline(PUBLIC_API_MISSING_ORG_BASELINE_FILE)


def _load_unread_org_parameter_baseline() -> set[str]:
    """Functions allowed to take an organization they do not read."""
    return _load_baseline(UNREAD_ORG_PARAMETER_BASELINE_FILE)


def _load_coreapi_signature_legality_baseline() -> set[str]:
    return _load_baseline(COREAPI_SIGNATURE_LEGALITY_BASELINE_FILE)


def _load_coreapi_write_user_context_baseline() -> set[str]:
    """CoreAPI write methods from before the rule that one takes the user."""
    return _load_baseline(COREAPI_WRITE_USER_CONTEXT_BASELINE_FILE)


def _load_owned_entries(
    path: Path,
    *,
    noun: str,
    today: date | None = None,
) -> tuple[set[str], list[str]]:
    """Read a suppression list where every entry names an owner and a date.

    Format, one entry per line::

        <key> | owner=<who> | expires=<YYYY-MM-DD> | <reason>

    A suppression with no owner and no expiry is how a known gap goes quiet
    for months, and a written reason nobody re-reads is worse than no check
    at all: a green gate standing on a premise that stopped being true is
    more convincing than a red one. Both fields are mandatory and both are
    checked here, so the list cannot outlive the decision it was waiting for.

    *noun* names the kind of entry in the error text, because the reader of a
    failing build needs to know which list to open.
    """
    if not path.exists():
        return set(), []

    today = today or date.today()
    keys: set[str] = set()
    errors: list[str] = []
    rel = path.name
    for lineno, raw in enumerate(
        path.read_text(encoding='utf-8').splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = [part.strip() for part in line.split('|')]
        if len(parts) < 4 or not parts[3]:
            errors.append(
                f'::error file=app/core/{rel},line={lineno},title=Architecture: malformed {noun}::'
                f'Expected "<key> | owner=<who> | expires=<YYYY-MM-DD> | <reason>", got: {line}'
            )
            continue
        key, owner, expires = parts[0], parts[1], parts[2]
        if not owner.startswith('owner=') or len(owner) <= len('owner='):
            errors.append(
                f'::error file=app/core/{rel},line={lineno},title=Architecture: {noun} without owner::'
                f"Entry '{key}' names nobody. Add owner=<who> — an unowned suppression is how this gap got here."
            )
            continue
        if not expires.startswith('expires='):
            errors.append(
                f'::error file=app/core/{rel},line={lineno},title=Architecture: {noun} without expiry::'
                f"Entry '{key}' never expires. Add expires=<YYYY-MM-DD>."
            )
            continue
        try:
            deadline = date.fromisoformat(expires[len('expires=') :])
        except ValueError:
            errors.append(
                f'::error file=app/core/{rel},line={lineno},title=Architecture: {noun} with unreadable expiry::'
                f"Entry '{key}' has expires='{expires[len('expires=') :]}'; expected YYYY-MM-DD."
            )
            continue
        if deadline < today:
            errors.append(
                f'::error file=app/core/{rel},line={lineno},title=Architecture: {noun} expired::'
                f"Entry '{key}' expired on {deadline.isoformat()} — {owner[len('owner=') :]} was to "
                f'recheck the premise it rests on.'
            )
            continue
        keys.add(key)
    return keys, errors


def _load_test_skip_baseline(
    today: date | None = None,
) -> tuple[set[str], list[str]]:
    """Tests that skip because of where they run, each with an owner and a date.

    Only the environment belongs here. A skip on missing data is a test that
    passes when the feature is deleted, and the fix for it is an assertion,
    not an entry.
    """
    return _load_owned_entries(
        TEST_SKIP_BASELINE_FILE,
        noun='test skip entry',
        today=today,
    )


def _load_manifest_permission_deferrals(
    today: date | None = None,
) -> tuple[set[str], list[str]]:
    """Manifest permissions declared but enforced nowhere, deferred on purpose.

    The list is empty and meant to stay that way; the file's own header says
    what it costs to enforce a key.
    """
    return _load_owned_entries(
        MANIFEST_PERMISSION_DEFERRALS_FILE,
        noun='permission deferral',
        today=today,
    )
