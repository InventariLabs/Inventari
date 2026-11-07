from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from app.cli.module_validator import validate_i18n

from ._baselines import (
    _load_audit_coverage_baseline,
    _load_bare_emit_baseline,
    _load_core_api_model_leak_baseline,
    _load_coreapi_signature_legality_baseline,
    _load_escape_hatch_org_filter_baseline,
    _load_escape_hatch_query_scope_baseline,
    _load_manifest_permission_deferrals,
    _load_mixed_status_assert_baseline,
    _load_module_import_surface_baseline,
    _load_module_migrations_baseline,
    _load_public_api_missing_org_baseline,
    _load_raw_http_exception_baseline,
    _load_request_scope_baseline,
    _load_services_public_api_import_baseline,
    _load_sync_async_twin_baseline,
    _load_test_skip_baseline,
    _load_toctou_risk_baseline,
    _load_transaction_owner_allowlist,
    _load_transaction_ownership_baseline,
    _load_transaction_rollback_baseline,
    _load_unread_org_parameter_baseline,
    _write_baseline,
)
from ._constants import (
    API_IMPORTS_BASELINE_FILE,
    API_ROOT,
    APP_ROOT,
    BASELINE_SIZES_FILE,
    CONTRACTS_ROOT,
    CONTRACTS_SNAPSHOT_FILE,
    CORE_API_SNAPSHOT_FILE,
    CORE_DIR,
    DEFAULT_BASELINE_FILE,
    EXTERNAL_MODULES_ROOTS,
    MODULE_SDK_SNAPSHOT_FILE,
    MODULES_ROOT,
    PUBLIC_API_ROOT,
    SERVICES_ROOT,
    TESTS_ROOT,
    VULTURE_WHITELIST_FILE,
    Violation,
    _suggest_fix,
)
from ._contracts_snapshot import check_contracts_snapshot, write_snapshot
from ._core_api_snapshot import check_core_api_snapshot
from ._core_api_snapshot import write_snapshot as write_core_api_snapshot
from ._module_sdk_snapshot import check_module_sdk_snapshot
from ._module_sdk_snapshot import write_snapshot as write_module_sdk_snapshot
from ._quality_checks import (
    _check_coreapi_async_naming,
    _check_coreapi_signature_legality,
    _check_cross_module_imports,
    _check_get_db_in_async_def,
    _check_module_import_surface,
    _check_module_migrations_exist,
    _check_public_api_return_types,
    _check_services_escape_hatch_marker,
    _check_sync_async_file_pairs,
    _check_sync_async_function_pairs,
    _check_sync_async_function_twins,
    _check_toctou_risk,
    collect_toctou_risks,
)
from ._quality_checks_audit_coverage import _check_audit_coverage, collect_audit_gaps
from ._quality_checks_baseline_ratchet import (
    _check_baseline_sizes,
    _check_stale_entries,
    write_baseline_sizes,
)
from ._quality_checks_core_isolation import _check_core_module_imports
from ._quality_checks_events import _check_bare_emit, collect_bare_emits
from ._quality_checks_list_envelopes import _check_list_envelopes
from ._quality_checks_permissions import _check_manifest_permissions_enforced
from ._quality_checks_raw_http_exception import (
    _check_raw_http_exceptions,
    _collect_raw_http_exceptions,
)
from ._quality_checks_rejections import (
    REFUSAL_LEDGER_FILE,
    REJECTION_LEDGER_FILE,
    write_refusal_ledger,
    write_rejection_ledger,
)
from ._quality_checks_request_scope import (
    _check_request_scope,
    collect_unscoped_endpoints,
)
from ._quality_checks_reserved_surface import _check_reserved_surface
from ._quality_checks_secrets import _check_module_secret_binding
from ._quality_checks_services_facade import (
    _check_services_facade_imports,
    collect_facade_imports,
)
from ._quality_checks_tenancy import (
    _check_escape_hatch_org_filter,
    _check_escape_hatch_query_scoping,
    _check_public_api_missing_org,
    _check_public_api_optional_org,
    _check_unread_org_parameter,
    _collect_public_api_missing_org_keys,
)
from ._quality_checks_test_hygiene import _check_mixed_status_assertions
from ._quality_checks_test_skips import _check_test_skips
from ._quality_checks_transaction_ownership import (
    _check_transaction_ownership,
    _collect_transaction_sites,
)
from ._quality_checks_twins import collect_twin_keys
from ._run_cache import shared_run
from ._violations import (
    _check_api_layer_violations,
    _check_contracts_violations,
    _check_public_api_violations,
    _collect_api_import_violations,
    collect_module_import_violations,
    find_api_layer_import_violations,
    find_module_boundary_violations,
)

#: Multi-line guidance printed after a failed lint run. Describes the happy
#: path (CoreAPI quick reference), the read-only escape hatch, and the
#: module-local-writes rule.
ARCHITECTURE_LINT_HELP = """\
Allowed access from modules should go through app.core.public_api \
and app.core.contracts.
Quick reference (happy path):
  from app.core.public_api import core_api
  item = await core_api.items.get_async(db, org_id, item_id)
  items = await core_api.items.list_async(db, org_id)
  storage = await core_api.locations.get_async(db, org_id, storage_id)
  cats = await core_api.categories.list_async(db, org_id)
  quants = await core_api.stock.list_quants_async(db, org_id, template_id)

Full API: from app.core.public_api import core_api  (22 namespaces)

To bypass for read-only analytics, add to your *_service.py file:
  # architecture: allow_direct_db_access
  # reason: <at least 5 words explaining why CoreAPI is insufficient>

Module-local DB writes (to tables defined in your module) are allowed by default.
Only writes to Core tables (app.models) must go through CoreAPI."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Architecture lint for module boundaries.'
    )
    parser.add_argument(
        '--baseline',
        type=Path,
        default=DEFAULT_BASELINE_FILE,
        help='Baseline file with accepted existing violations.',
    )
    parser.add_argument(
        '--write-baseline',
        action='store_true',
        help='Write current non-test violations into the baseline file and exit.',
    )
    parser.add_argument(
        '--write-api-imports-baseline',
        action='store_true',
        help='Write current app/api/** import violations into the API imports baseline file and exit.',
    )
    parser.add_argument(
        '--api-imports-baseline',
        type=Path,
        default=API_IMPORTS_BASELINE_FILE,
        help='Baseline file with accepted existing app/api/** import violations.',
    )
    parser.add_argument(
        '--write-bare-emit-baseline',
        action='store_true',
        help='Record the emit call sites that exist today (the ratchet floor).',
    )
    parser.add_argument(
        '--write-request-scope-baseline',
        action='store_true',
        help='Record the endpoints that are global by design.',
    )
    parser.add_argument(
        '--write-raw-http-exception-baseline',
        action='store_true',
        help=(
            'Record the raw raise HTTPException sites that exist today '
            '(the ratchet floor).'
        ),
    )
    parser.add_argument(
        '--write-services-facade-baseline',
        action='store_true',
        help=(
            'Record the service places that still import the core_api facade '
            '(the ratchet floor).'
        ),
    )
    parser.add_argument(
        '--write-baseline-sizes',
        action='store_true',
        help=(
            'Record the current entry count of every suppression list and '
            'exit. The only way to change the ratchet.'
        ),
    )
    parser.add_argument(
        '--write-rejection-ledger',
        action='store_true',
        help=(
            'Regenerate the raw-ValueError-sentence ledger entries from the '
            'tree and exit. The prose header is preserved; the entries and '
            'the counts block are rewritten from the same scan the '
            'rejection gate runs. Follow with --write-baseline-sizes.'
        ),
    )
    parser.add_argument(
        '--check-baseline-hygiene',
        action='store_true',
        help='Check that baseline entries have required metadata (reason, plan).',
    )
    parser.add_argument(
        '--contracts-snapshot',
        type=Path,
        default=CONTRACTS_SNAPSHOT_FILE,
        help='Committed snapshot of public contracts DTOs (additive-only check).',
    )
    parser.add_argument(
        '--update-contracts-snapshot',
        action='store_true',
        help='Regenerate the contracts snapshot from current DTOs and exit.',
    )
    parser.add_argument(
        '--core-api-snapshot',
        type=Path,
        default=CORE_API_SNAPSHOT_FILE,
        help='Committed snapshot of the core_api facade (additive-only check).',
    )
    parser.add_argument(
        '--update-core-api-snapshot',
        action='store_true',
        help='Regenerate the core_api surface snapshot and exit.',
    )
    parser.add_argument(
        '--module-sdk-snapshot',
        type=Path,
        default=MODULE_SDK_SNAPSHOT_FILE,
        help=(
            'Committed snapshot of app.core.module_sdk — its exported names and '
            'the hook signatures a module implements (additive-only check).'
        ),
    )
    parser.add_argument(
        '--update-module-sdk-snapshot',
        action='store_true',
        help='Regenerate the module SDK snapshot and exit.',
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Collapse per-file L2 read-bypass ::notice lines into a single '
        'summary line (cleaner terminal output). Default is verbose so GitHub '
        'PR annotations stay per-file.',
    )
    return parser


#: One entry per category a check can baseline: ``key -> (label, baseline
#: file)``. ``--quiet`` prints the count of each exactly once, in the closing
#: summary, under this label; ``baselined`` in ``_run_checks`` is keyed the
#: same way. A test reads both and fails when a key is recorded there that
#: has no entry here, so a new baselined check cannot go uncounted.
_BASELINED_SUMMARY: dict[str, tuple[str, str | None]] = {
    'get_db': ('baselined get_db in async def', None),
    'migration': (
        'module(s) with baselined migration gaps',
        'app/core/module_migrations_baseline.txt',
    ),
    'twin': (
        'baselined sync/async twin(s)',
        'app/core/sync_async_twin_baseline.txt',
    ),
    'model_leak': (
        'baselined CoreAPI model leak(s)',
        'app/core/core_api_model_leak_baseline.txt',
    ),
    'toctou': (
        'baselined TOCTOU risk function(s)',
        'app/core/toctou_risk_baseline.txt',
    ),
    'bare_emit': (
        'baselined non-transactional emit(s)',
        'app/core/bare_emit_baseline.txt',
    ),
    'request_scope': (
        'baselined global endpoint(s)',
        'app/core/request_scope_baseline.txt',
    ),
    'raw_http_exception': (
        'baselined raw HTTPException raise(s)',
        'app/core/raw_http_exception_baseline.txt',
    ),
    'org_filter': (
        'baselined escape hatch(es) without org filter',
        'app/core/escape_hatch_org_filter_baseline.txt',
    ),
    'query_scope': (
        'baselined escape-hatch quer(ies) without org filter',
        'app/core/escape_hatch_query_scope_baseline.txt',
    ),
    'missing_org': (
        'baselined public_api method(s) without organization',
        'app/core/public_api_missing_org_baseline.txt',
    ),
    'unread_org': (
        'baselined function(s) taking an organization unread',
        'app/core/unread_org_parameter_baseline.txt',
    ),
    'legality': (
        'baselined CoreAPI signature legality finding(s)',
        'app/core/coreapi_signature_legality_baseline.txt',
    ),
    'test_skip': (
        'registered environmental test skip(s)',
        'app/core/test_skip_baseline.txt',
    ),
    'mixed_status': (
        'baselined assertion(s) that cannot fail',
        'app/core/mixed_status_assert_baseline.txt',
    ),
    'tx_ownership': (
        'baselined mid-stack commit(s)',
        'app/core/transaction_ownership_baseline.txt',
    ),
    'tx_rollback': (
        'baselined mid-stack rollback(s)',
        'app/core/transaction_rollback_baseline.txt',
    ),
    'services_facade': (
        'listed service place(s) importing the facade',
        'app/core/services_public_api_import_baseline.txt',
    ),
    'audit_coverage': (
        'baselined write path(s) without a journal entry',
        'app/core/audit_coverage_baseline.txt',
    ),
}


def _print_baselined_counts(baselined: dict[str, list[str]]) -> None:
    """Print the count of every baselined category, once, with its list.

    The single place ``--quiet`` reports accepted debt; the per-file notices
    of the verbose mode (CI annotations) are not repeated here.
    """
    for key, (label, baseline_file) in _BASELINED_SUMMARY.items():
        notices = baselined.get(key)
        if notices:
            pointer = f' — {baseline_file}' if baseline_file else ''
            print(f'  ({len(notices)} {label}{pointer})')


def _print_failure_summary(
    *,
    api_errors: list[str],
    public_api_errors: list[str],
    api_import_new: list[Violation],
    get_db_errors: list[str],
    i18n_errors: list[str],
    i18n_warnings: list[str],
    baselined: dict[str, list[str]],
    api_import_baseline: list[Violation],
    violations: list[Violation],
) -> None:
    """Print the per-category failure counts and the forbidden-import details.

    Only called from ``main()`` when at least one error category is non-empty.
    """
    if api_errors:
        print(
            f'Architecture lint failed: {len(api_errors)} direct DB writes in API layer.'
        )

    if public_api_errors:
        print(
            f'Architecture lint failed: {len(public_api_errors)} forbidden imports in Public API.'
        )

    if api_import_new:
        print(
            f'Architecture lint failed: {len(api_import_new)} new app/api/** model/db imports.'
        )

    if get_db_errors:
        print(f'Architecture lint failed: {len(get_db_errors)} get_db in async def.')

    if i18n_errors:
        print(f'Architecture lint failed: {len(i18n_errors)} i18n validation error(s).')

    if i18n_warnings:
        print(
            f'Architecture lint: {len(i18n_warnings)} i18n validation warning(s) '
            f'(::warning, non-blocking).'
        )

    if api_import_baseline:
        print(
            f'Architecture lint: {len(api_import_baseline)} baselined app/api/** import violation(s) '
            f'(::notice, non-blocking).'
        )

    _print_baselined_counts(baselined)

    if violations:
        print('Architecture lint failed. New forbidden imports found in app.modules:')
    for violation in violations:
        rel_path = violation.file_path.relative_to(Path.cwd())
        suggestion = _suggest_fix(violation.import_path)
        msg = f'  - {rel_path}:{violation.line} -> {violation.import_path}'
        if suggestion:
            msg += f'\n    Fix: {suggestion}'
        print(msg)

    print(ARCHITECTURE_LINT_HELP)


def _emit(entries: Iterable[str]) -> list[str]:
    """Print a check's findings and hand them back for the error tally."""
    printed = list(entries)
    for entry in printed:
        print(entry)
    return printed


def _stale_baseline_errors() -> list[str]:
    """Entries of the key-matched baselines that no finding matches.

    Left out on purpose: ``services_public_api_import`` and ``test_skip``
    (each runs its own stale check), the audit-style lists whose entries are
    not finding keys (``refusal_sentences``, ``manifest_permission_deferrals``,
    ``module_migrations``, ``get_db``), and the lists that are empty today
    (``core_api_model_leak``, ``coreapi_signature_legality``,
    ``escape_hatch_*``, ``unread_org_parameter``, ``mixed_status_assert``).
    """
    allow = _load_transaction_owner_allowlist()
    sites = [
        site
        for site in _collect_transaction_sites([SERVICES_ROOT, CORE_DIR, MODULES_ROOT])
        if site.owner_key not in allow
    ]
    checks = (
        (
            'toctou_risk_baseline.txt',
            _load_toctou_risk_baseline()[0],
            set(collect_toctou_risks(MODULES_ROOT)),
        ),
        (
            'bare_emit_baseline.txt',
            _load_bare_emit_baseline(),
            set(collect_bare_emits(APP_ROOT)),
        ),
        (
            'audit_coverage_baseline.txt',
            _load_audit_coverage_baseline()[0],
            set(collect_audit_gaps(APP_ROOT)),
        ),
        (
            'raw_http_exception_baseline.txt',
            _load_raw_http_exception_baseline(),
            {site.key for site in _collect_raw_http_exceptions([APP_ROOT])},
        ),
        (
            'request_scope_baseline.txt',
            _load_request_scope_baseline(),
            set(collect_unscoped_endpoints(APP_ROOT)),
        ),
        (
            'transaction_ownership_baseline.txt',
            _load_transaction_ownership_baseline(),
            {site.key for site in sites if site.op == 'commit'},
        ),
        (
            'transaction_rollback_baseline.txt',
            _load_transaction_rollback_baseline(),
            {site.key for site in sites if site.op == 'rollback'},
        ),
        (
            'sync_async_twin_baseline.txt',
            _load_sync_async_twin_baseline(),
            collect_twin_keys(APP_ROOT),
        ),
        (
            'public_api_missing_org_baseline.txt',
            _load_public_api_missing_org_baseline(),
            _collect_public_api_missing_org_keys(PUBLIC_API_ROOT, MODULES_ROOT),
        ),
    )
    return [
        error
        for name, baseline, live in checks
        for error in _check_stale_entries(baseline, live, name)
    ]


def _emit_baselined(
    entries: Iterable[str],
    *,
    quiet: bool,
) -> tuple[list[str], list[str]]:
    """Print a check that separates blocking errors from baselined notices.

    Eight checks share this shape: the errors go out one per line, the notices
    go out per file for GitHub annotations and are held back under ``--quiet``,
    where the closing summary (:func:`_print_baselined_counts`) reports their
    count once. Returns both lists because ``main`` still needs the errors for
    the exit code and the notices for that summary.
    """
    errors: list[str] = []
    notices: list[str] = []
    for entry in entries:
        (notices if entry.startswith('::notice') else errors).append(entry)
    for err in errors:
        print(err)
    if not quiet:
        for notice in notices:
            print(notice)
    return errors, notices


def _emit_test_skips(*, quiet: bool) -> tuple[list[str], list[str]]:
    """Skips inside test bodies against their registry, the registry's own errors first.

    Eleven of fifteen such skips fired in every run, one of them a tenant
    isolation test asking for a route that never existed.
    """
    registry, registry_errors = _load_test_skip_baseline()
    errors = _emit(registry_errors)
    hits, notices = _emit_baselined(
        _check_test_skips((MODULES_ROOT, TESTS_ROOT), registry),
        quiet=quiet,
    )
    return errors + hits, notices


def _write_route_baselines(args: argparse.Namespace) -> bool:
    """Write a route-keyed baseline and report whether one was asked for.

    The raw-HTTPException ledger and the list-envelope ledger are the same
    shape — a route's behaviour recorded per site — and grouping them keeps
    the write-mode dispatcher inside its complexity budget.
    """
    if args.write_raw_http_exception_baseline:
        _write_raw_http_exception_baseline()
        return True
    return False


def _write_raw_http_exception_baseline() -> None:
    """Record the raw ``raise HTTPException`` sites that exist today."""
    from ._constants import RAW_HTTP_EXCEPTION_BASELINE_FILE
    from ._quality_checks_raw_http_exception import _collect_raw_http_exceptions

    keys = {site.key for site in _collect_raw_http_exceptions([APP_ROOT])}
    _write_baseline(
        RAW_HTTP_EXCEPTION_BASELINE_FILE,
        keys,
        key_format='relative/path.py::qualname@N',
    )
    print(
        f'Wrote the raw-HTTPException baseline with {len(keys)} entries '
        f'to {RAW_HTTP_EXCEPTION_BASELINE_FILE}.'
    )
    print('Re-run --write-baseline-sizes if the entry count changed.')


def _emit_contract_checks(
    args: argparse.Namespace, baselined: dict[str, list[str]]
) -> tuple[list[str], list[str]]:
    """Emit the tenant-presence and raw-HTTPException gates.

    Grouped in one helper because ``main`` sits at the statement ceiling;
    the two checks share their shape and nothing else.
    """
    request_scope_errors, baselined['request_scope'] = _emit_baselined(
        _check_request_scope(APP_ROOT, _load_request_scope_baseline()),
        quiet=args.quiet,
    )
    raw_http_errors, baselined['raw_http_exception'] = _emit_baselined(
        _check_raw_http_exceptions([APP_ROOT], _load_raw_http_exception_baseline()),
        quiet=args.quiet,
    )
    return request_scope_errors, raw_http_errors


def _write_request_scope_baseline() -> None:
    """Record the endpoints that are global by design."""
    from ._constants import REQUEST_SCOPE_BASELINE_FILE
    from ._quality_checks_request_scope import collect_unscoped_endpoints

    keys = set(collect_unscoped_endpoints(APP_ROOT))
    # Written here rather than through _write_baseline: this list is
    # not import paths, and a header describing the wrong shape is
    # worse than none — the next reader trusts it.
    REQUEST_SCOPE_BASELINE_FILE.write_text(
        '\n'.join(
            [
                '# Endpoints that are global by design.',
                '# Format: relative/path.py::endpoint_function',
                '# Superuser views, pre-login flows, public token pages.',
                *sorted(keys),
            ]
        )
        + '\n',
        encoding='utf-8',
    )
    print(f'Wrote the global-endpoint baseline with {len(keys)} entries.')
    print('Re-run --write-baseline-sizes if the entry count changed.')


def _write_refusal_ledger() -> int:
    """Regenerate the refusal ledger beside the ValueError one; 1 if it refuses."""
    refusal = write_refusal_ledger(MODULES_ROOT.parent, REFUSAL_LEDGER_FILE)
    if refusal.refused:
        print(
            f'Refused to regenerate the refusal ledger: '
            f'{len(refusal.refused)} new refusal sentence(s) cannot enter it.'
        )
        for entry in refusal.refused:
            print(f'  ! {entry}')
        print(
            'Give these refusals a translation key '
            '(ServiceRejectionError / get_error_message).'
        )
        return 1
    print(f'Regenerated the refusal ledger at {REFUSAL_LEDGER_FILE}.')
    for entry in refusal.added:
        print(f'  + {entry}')
    for entry in refusal.removed:
        print(f'  - {entry}')
    return 0


def _run_write_modes(args: argparse.Namespace) -> int | None:
    """Handle the modes that write a file and exit.

    Returns the exit code for those modes, or ``None`` when the run is an
    ordinary lint.
    """
    if args.write_baseline:
        all_violations = collect_module_import_violations(MODULES_ROOT)

        keys = {
            violation.baseline_key(MODULES_ROOT.parent) for violation in all_violations
        }
        _write_baseline(args.baseline, keys)
        print(f'Wrote baseline with {len(keys)} entries to {args.baseline}.')
        return 0

    if args.write_rejection_ledger:
        rewrite = write_rejection_ledger(MODULES_ROOT.parent, REJECTION_LEDGER_FILE)
        if rewrite.refused:
            print(
                f'Refused to regenerate the rejection ledger: '
                f'{len(rewrite.refused)} new client-facing raw sentence(s) '
                'cannot enter the ledger, switch or no switch — the ledger '
                'counts existing debt, it does not open the door to new debt '
                'a reader could see.'
            )
            for entry in rewrite.refused:
                print(f'  ! {entry}')
            print(
                "Raise ServiceRejectionError('<key>') at these sites (the "
                'envelope translates it and stamps lang), or reclassify the '
                'site in REJECTION_GROUP_OVERRIDES if no client reaches it.'
            )
            return 1
        print(
            f'Regenerated the rejection ledger at {REJECTION_LEDGER_FILE}; '
            f'entries by group: '
            + ', '.join(f'{name} {count}' for name, count in rewrite.counts.items())
            + '.'
        )
        # Totals alone let a debt swap places unseen — one site paid off, one
        # new one written, same number on the line.
        for entry in rewrite.added:
            print(f'  + {entry}')
        for entry in rewrite.removed:
            print(f'  - {entry}')
        print('Re-run --write-baseline-sizes if the entry count changed.')
        return _write_refusal_ledger()

    if args.write_bare_emit_baseline:
        from ._constants import BARE_EMIT_BASELINE_FILE
        from ._quality_checks_events import collect_bare_emits

        keys = set(collect_bare_emits(APP_ROOT))
        _write_baseline(
            BARE_EMIT_BASELINE_FILE,
            keys,
            key_format='relative/path.py::function::event',
        )
        print(
            f'Wrote the non-transactional emit baseline with {len(keys)} '
            f'entries to {BARE_EMIT_BASELINE_FILE}.'
        )
        print('Re-run --write-baseline-sizes if the entry count changed.')
        return 0

    if args.write_request_scope_baseline:
        _write_request_scope_baseline()
        return 0

    if args.write_services_facade_baseline:
        from ._constants import SERVICES_PUBLIC_API_IMPORT_BASELINE_FILE

        keys = set(collect_facade_imports(SERVICES_ROOT))
        _write_baseline(
            SERVICES_PUBLIC_API_IMPORT_BASELINE_FILE,
            keys,
            key_format='relative/path.py::Class::function',
        )
        print(
            f'Wrote the services facade-import baseline with {len(keys)} '
            f'entries to {SERVICES_PUBLIC_API_IMPORT_BASELINE_FILE}.'
        )
        print('Re-run --write-baseline-sizes if the entry count changed.')
        return 0

    if args.write_baseline_sizes:
        count = write_baseline_sizes(
            CORE_DIR, BASELINE_SIZES_FILE, VULTURE_WHITELIST_FILE
        )
        print(f'Recorded the size of {count} suppression list(s).')
        return 0

    if _write_route_baselines(args):
        return 0

    if args.write_api_imports_baseline:
        api_violations = _collect_api_import_violations(API_ROOT)
        keys = {violation.baseline_key(API_ROOT.parent) for violation in api_violations}
        _write_baseline(args.api_imports_baseline, keys)
        print(
            f'Wrote API imports baseline with {len(keys)} entries to '
            f'{args.api_imports_baseline}.'
        )
        return 0

    if args.update_contracts_snapshot:
        count = write_snapshot(args.contracts_snapshot)
        print(
            f'Wrote contracts snapshot with {count} contract(s) to '
            f'{args.contracts_snapshot}.'
        )
        return 0

    if _run_snapshot_write_modes(args):
        return 0

    return None


def _run_snapshot_write_modes(args: argparse.Namespace) -> bool:
    """Regenerate one of the two surface snapshots when asked to, and say so.

    The DTO snapshot stays above with the other baseline writers; the two
    *surface* snapshots share this helper so the growing list of write modes
    does not keep pushing one function over the complexity guard.
    """
    if args.update_core_api_snapshot:
        count = write_core_api_snapshot(args.core_api_snapshot)
        print(
            f'Wrote core_api snapshot with {count} method(s) to '
            f'{args.core_api_snapshot}.'
        )
        return True

    if args.update_module_sdk_snapshot:
        count = write_module_sdk_snapshot(args.module_sdk_snapshot)
        print(
            f'Wrote module SDK snapshot with {count} exported name(s) to '
            f'{args.module_sdk_snapshot}.'
        )
        return True

    return False


def _print_api_import_findings(
    new: list[Violation], baselined: list[Violation]
) -> None:
    """Report app/api/** imports of app.models / app.database (Abstraction Guard)."""
    for violation in new:
        rel = violation.file_path.relative_to(Path.cwd())
        print(
            f'::error file={rel},line={violation.line},title=Architecture: Model import in app/api/**::'
            f"Direct import of '{violation.import_path}' in API layer. "
            f'Must use CoreAPI (app.core.public_api) or a service layer. '
            f'See backend/AGENTS.md §3 (Golden Path).'
        )
    for violation in baselined:
        rel = violation.file_path.relative_to(Path.cwd())
        print(
            f'::notice file={rel},line={violation.line},title=Architecture: app/api/** import in baseline::'
            f"Import of '{violation.import_path}' baselined — needs migration to CoreAPI. "
            f'Remove this entry from the baseline once migrated.'
        )


def _print_escape_hatch_notices(
    escape_hatch_files: list[tuple[Path, str]], *, quiet: bool
) -> None:
    """Announce the approved L2 read bypasses, one annotation per file.

    ``--quiet`` prints nothing here: the closing summary carries the count.
    """
    if quiet:
        return
    for file_path, reason in escape_hatch_files:
        rel = file_path.relative_to(Path.cwd())
        print(
            f'::notice file={rel},title=Architecture: L2 CoreAPI read bypass approved::'
            f"This file has direct DB read access to Core tables. Reason: '{reason}'. "
            f'Auto-verified: db.commit/add/delete/merge are absent (read-only confirmed).'
        )


def _emit_i18n_findings() -> tuple[list[str], list[str]]:
    """Validate every module's translations; returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith('_'):
            continue
        if not (module_dir / 'manifest.json').exists():
            continue
        for severity, message in validate_i18n(module_dir):
            if severity == 'error':
                errors.append(
                    f'::error title=Architecture: i18n validation failed::{message}'
                )
            else:
                warnings.append(
                    f'::warning title=Architecture: i18n validation warning::{message}'
                )
    for entry in (*errors, *warnings):
        print(entry)
    return errors, warnings


def _emit_core_isolation_errors() -> list[str]:
    """No app.modules.* imports inside Core.

       app/services and app/api are Core too: restricting the scan to app/core/
    left the real violations unguarded — every one found lived there.
    """
    errors: list[str] = []
    for scanned_dir in (
        CORE_DIR,
        CORE_DIR.parent / 'services',
        CORE_DIR.parent / 'api',
    ):
        if scanned_dir.is_dir():
            errors += _check_core_module_imports(scanned_dir)
    return _emit(errors)


def _print_pass_summary(
    *,
    escape_hatch_files: list[tuple[Path, str]],
    api_import_baseline: list[Violation],
    baselined: dict[str, list[str]],
) -> None:
    """Print the green line plus the counts of everything still baselined."""
    print('Architecture lint passed: no forbidden imports or direct API writes.')
    if escape_hatch_files:
        print(f'  ({len(escape_hatch_files)} L2 read-bypass file(s))')
    if api_import_baseline:
        print(
            f'  ({len(api_import_baseline)} baselined app/api/** import violation(s) — D1 in progress)'
        )
    _print_baselined_counts(baselined)


def _emit_tenancy_checks(*, quiet: bool, baselined: dict[str, list[str]]) -> list[str]:
    """The tenancy shape checks, in order; their blocking errors, joined.

    Each records its baselined notices under its own key in *baselined*, for
    the closing counts.
    """
    # 17. Tenancy: no optional `organization_id=None` in public_api.
    optional_org_errors = _emit(_check_public_api_optional_org(PUBLIC_API_ROOT))

    # 18. Tenancy: escape-hatch files must be org-scoped.
    org_filter_errors, baselined['org_filter'] = _emit_baselined(
        _check_escape_hatch_org_filter(
            APP_ROOT, _load_escape_hatch_org_filter_baseline()
        ),
        quiet=quiet,
    )

    # 18a. Tenancy: each escape-hatch query must filter on an organization.
    query_scope_baseline, query_scope_baseline_errors = (
        _load_escape_hatch_query_scope_baseline()
    )
    query_scope_errors = _emit(query_scope_baseline_errors)
    query_scope_hits, baselined['query_scope'] = _emit_baselined(
        _check_escape_hatch_query_scoping(APP_ROOT, query_scope_baseline),
        quiet=quiet,
    )
    query_scope_errors += query_scope_hits

    # 18b. Tenancy: public_api methods addressed by id must take an org.
    missing_org_errors, baselined['missing_org'] = _emit_baselined(
        _check_public_api_missing_org(
            PUBLIC_API_ROOT, _load_public_api_missing_org_baseline(), MODULES_ROOT
        ),
        quiet=quiet,
    )

    # 18c. Tenancy: a function taking the organization must read it.
    unread_org_errors, baselined['unread_org'] = _emit_baselined(
        _check_unread_org_parameter(APP_ROOT, _load_unread_org_parameter_baseline()),
        quiet=quiet,
    )

    return [
        *optional_org_errors,
        *org_filter_errors,
        *query_scope_errors,
        *missing_org_errors,
        *unread_org_errors,
    ]


def _emit_module_surface_errors() -> list[str]:
    """Every shipped module import that is not on the declared surface.

    The findings are split in two lists because they answer different
    questions — a live import nobody froze, and a frozen entry whose import is
    gone — but both block: the list only ever shrinks, and adding to it is a
    decision that has to be written down.
    """
    baseline, baseline_errors = _load_module_import_surface_baseline()
    return _emit(_check_module_import_surface(MODULES_ROOT, baseline)) + _emit(
        baseline_errors
    )


def _emit_surface_checks(
    args: argparse.Namespace,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """The declared surface, read from four angles.

    ``contracts_snapshot.json`` freezes the DTO shapes crossing the seam,
    ``core_api_snapshot.json`` freezes the facade surface those DTOs are
    passed to, ``module_sdk_snapshot.json`` freezes what a module imports to
    register itself and the hook signatures it implements, and
    ``module_import_surface_baseline.txt`` freezes the core paths the shipped
    modules still reach. They are one concern — the contract between Core and a
    module — so they are emitted together.
    """
    return (
        _emit(check_contracts_snapshot(args.contracts_snapshot)),
        _emit(check_core_api_snapshot(args.core_api_snapshot)),
        _emit(check_module_sdk_snapshot(args.module_sdk_snapshot)),
        _emit_module_surface_errors(),
    )


def _external_module_migration_errors() -> list[str]:
    """Migration gaps of modules that live outside the repo tree.

    Two configured roots may be one directory (in the container
    ``/modules-workspace`` and the repo-root twin are), so a root is read once
    per resolved path: otherwise every module there is reported twice.
    """
    errors: list[str] = []
    seen: set[Path] = set()
    for root in EXTERNAL_MODULES_ROOTS:
        if not root.is_dir() or root.resolve() in seen:
            continue
        seen.add(root.resolve())
        errors.extend(_check_module_migrations_exist(root))
    return errors


def main() -> int:
    """Run every architecture check in order; 0 when nothing blocks.

    The checks are deliberately listed one after another rather than looped
    over: their inputs, baselines and output shapes differ, and the numbering
    is the order a reader of the CI log sees.
    """
    with shared_run():
        return _run_checks()


def _run_checks() -> int:
    args = build_parser().parse_args()

    write_mode_exit = _run_write_modes(args)
    if write_mode_exit is not None:
        return write_mode_exit

    violations, escape_hatch_files = find_module_boundary_violations(
        baseline_file=args.baseline
    )
    baselined: dict[str, list[str]] = {}

    # 1. API layer: direct writes (CQRS Guard)
    # 2. Public API: model imports (Abstraction Guard)
    api_errors, public_api_errors = (
        _emit(_check_api_layer_violations(API_ROOT)),
        _emit(_check_public_api_violations(PUBLIC_API_ROOT)),
    )

    # 2b. contracts/ layer: ORM imports (Abstraction Guard)
    contracts_errors = _emit(_check_contracts_violations(CONTRACTS_ROOT))

    # 3. app/api/**: app.models / app.database imports (Abstraction Guard)
    api_import_new, api_import_baseline = find_api_layer_import_violations(
        baseline_file=args.api_imports_baseline,
    )
    _print_api_import_findings(api_import_new, api_import_baseline)

    # 4. async def with Depends(get_db) — must use get_async_db
    get_db_errors, baselined['get_db'] = _emit_baselined(
        _check_get_db_in_async_def(API_ROOT),
        quiet=args.quiet,
    )

    # 5. sync/async file duplication pattern
    _emit(_check_sync_async_file_pairs(APP_ROOT))

    # 5b. The escape-hatch marker is reserved for module code; forbid it in
    # Core services (app/services/**) where Core writes to Core-owned models
    # legitimately and the read-only marker would be misleading.
    services_escape_hatch_errors = _emit(
        _check_services_escape_hatch_marker(SERVICES_ROOT)
    )

    # 6. L2 approved bypasses (visible in PR review).
    _print_escape_hatch_notices(escape_hatch_files, quiet=args.quiet)

    # 7. Modules with models.py have migrations/
    migration_errors, baselined['migration'] = _emit_baselined(
        _check_module_migrations_exist(
            MODULES_ROOT, baseline_modules=_load_module_migrations_baseline()
        )
        + _external_module_migration_errors(),
        quiet=args.quiet,
    )

    # 8. i18n translations for all modules
    i18n_errors, i18n_warnings = _emit_i18n_findings()

    # 10. Cross-module imports (must use public API) — blocking: a leak into
    # a sibling's private service used to print here and still pass the gate.
    # The same check also names what it could not read (symlinked directory,
    # unparsable file) as ``::warning``: printed, because a scan nobody can
    # audit is worth less than a red one, and non-blocking, because what sits
    # behind the link is a review call rather than a verdict this tool can make.
    cross_module_findings = _emit(_check_cross_module_imports(MODULES_ROOT))
    cross_module_errors = [
        entry for entry in cross_module_findings if not entry.startswith('::warning')
    ]

    # 11. sync/async function pairs in the same file
    _emit(_check_sync_async_function_pairs(APP_ROOT))

    # 12. Guardrail: sync/async function twins (foo + foo_async)
    twin_errors, baselined['twin'] = _emit_baselined(
        _check_sync_async_function_twins(APP_ROOT, _load_sync_async_twin_baseline()),
        quiet=args.quiet,
    )

    # 13. Guardrail: CoreAPI model return type leak
    model_leak_errors, baselined['model_leak'] = _emit_baselined(
        _check_public_api_return_types(
            PUBLIC_API_ROOT, _load_core_api_model_leak_baseline()
        ),
        quiet=args.quiet,
    )

    # 13a. Guardrail: a public CoreAPI coroutine says so in its name.
    async_naming_errors = _emit(_check_coreapi_async_naming(PUBLIC_API_ROOT))

    # 14. Guardrail: TOCTOU risk (select + mutation without lock)
    toctou_baseline, toctou_baseline_errors = _load_toctou_risk_baseline()
    toctou_errors, baselined['toctou'] = _emit_baselined(
        _check_toctou_risk(MODULES_ROOT, toctou_baseline),
        quiet=args.quiet,
    )
    toctou_errors += _emit(toctou_baseline_errors + _stale_baseline_errors())

    # 14a. Guardrail: emits that are not tied to the transaction they describe.
    bare_emit_errors, baselined['bare_emit'] = _emit_baselined(
        _check_bare_emit(APP_ROOT, _load_bare_emit_baseline()),
        quiet=args.quiet,
    )

    # 14b/14d. Guardrails: an endpoint that touches the DB must hold the
    # tenant; a new raw HTTPException raise answers detail as a bare string,
    # and the baseline freezes the legacy population per site.
    request_scope_errors, raw_http_exception_errors = _emit_contract_checks(
        args, baselined
    )

    # 14e. Guardrail: every list endpoint answers with a documented pagination
    # envelope, or says why it is not a collection.
    list_envelope_errors = _emit(_check_list_envelopes([API_ROOT, MODULES_ROOT]))

    # 14c. Guardrail: a module's secret must be bound to that module.
    secret_binding_errors = _emit(_check_module_secret_binding(MODULES_ROOT))

    # 15. The declared surface: three additive-only snapshots, and the shipped
    # modules held to the paths those snapshots promise.
    (
        contracts_snapshot_errors,
        core_api_snapshot_errors,
        module_sdk_snapshot_errors,
        module_surface_errors,
    ) = _emit_surface_checks(args)

    # 17-18c. Tenancy: the organization is required, filtered on and read.
    tenancy_errors = _emit_tenancy_checks(quiet=args.quiet, baselined=baselined)

    # 18d. Suppression lists may shrink on their own; growing one takes an
    # explicit act that leaves a diff.
    baseline_ratchet_errors = _emit(
        _check_baseline_sizes(CORE_DIR, BASELINE_SIZES_FILE, VULTURE_WHITELIST_FILE)
    )

    # 19. Core isolation: no app.modules.* imports inside Core.
    core_isolation_errors = _emit_core_isolation_errors()

    # 19a. Dead-code whitelist: the one section whose claim a grep cannot
    # settle has to name an owner and a date.
    reserved_surface_errors = _emit(_check_reserved_surface(VULTURE_WHITELIST_FILE))

    # 19b. Manifest permissions: every declared key needs an enforcement point.
    deferred_permissions, deferral_errors = _load_manifest_permission_deferrals()
    permission_errors = _emit(
        _check_manifest_permissions_enforced(
            MODULES_ROOT, APP_ROOT, deferred_permissions
        )
        + deferral_errors
    )

    # 19c. Test hygiene: a skip inside a test body names its reason, an
    # owner and an expiry.
    test_skip_errors, baselined['test_skip'] = _emit_test_skips(quiet=args.quiet)

    # 20. Contract legality: CoreAPI signatures may only reference types a
    # community module can legally import.
    legality_errors, baselined['legality'] = _emit_baselined(
        _check_coreapi_signature_legality(
            PUBLIC_API_ROOT, _load_coreapi_signature_legality_baseline()
        ),
        quiet=args.quiet,
    )

    # 21. Test hygiene: an assertion may not accept a success and a refusal
    # at once. Twenty-six such assertions were found in the suite, each one
    # green through every change to the code it was pointed at.
    mixed_status_errors, baselined['mixed_status'] = _emit_baselined(
        _check_mixed_status_assertions(
            (MODULES_ROOT, TESTS_ROOT), _load_mixed_status_assert_baseline()
        ),
        quiet=args.quiet,
    )

    # 22. Guardrail: a service, a core module or a vertical module never
    # commits and never rolls back — the caller owns the transaction; the
    # baselines hold the sites still waiting for their conversion wave,
    # the allowlist the functions that hold their own session.
    commit_findings, rollback_findings = _check_transaction_ownership(
        [SERVICES_ROOT, CORE_DIR, MODULES_ROOT],
        commit_baseline=_load_transaction_ownership_baseline(),
        rollback_baseline=_load_transaction_rollback_baseline(),
        owner_allowlist=_load_transaction_owner_allowlist(),
    )
    tx_errors, baselined['tx_ownership'] = _emit_baselined(
        commit_findings,
        quiet=args.quiet,
    )
    tx_rollback_errors, baselined['tx_rollback'] = _emit_baselined(
        rollback_findings,
        quiet=args.quiet,
    )

    # 23. Guardrail: a core service never imports the core_api facade — the
    # facade is for modules, and a service going through it loops back
    # (services → core_api → services), hiding the dependency between two
    # services behind a middleman. The places still on the detour are listed
    # and only leave the list.
    services_facade_errors, baselined['services_facade'] = _emit_baselined(
        _check_services_facade_imports(
            SERVICES_ROOT, _load_services_public_api_import_baseline()
        ),
        quiet=args.quiet,
    )

    # 24. Guardrail: every write path reaches the organization journal — a
    # mutating route and a CoreAPI write method must reach log_action_async
    # in their own module or in Core. The baseline holds the paths that do
    # not yet (or cannot), one reasoned entry each; the size ratchet makes
    # adding one a visible act.
    audit_baseline, audit_baseline_errors = _load_audit_coverage_baseline()
    audit_errors, baselined['audit_coverage'] = _emit_baselined(
        _check_audit_coverage(APP_ROOT, audit_baseline),
        quiet=args.quiet,
    )
    audit_errors += _emit(audit_baseline_errors)

    blocking = [
        violations,
        mixed_status_errors,
        tx_errors,
        services_facade_errors,
        tx_rollback_errors,
        audit_errors,
        api_errors,
        public_api_errors,
        contracts_errors,
        api_import_new,
        get_db_errors,
        migration_errors,
        i18n_errors,
        twin_errors,
        model_leak_errors,
        async_naming_errors,
        toctou_errors,
        bare_emit_errors,
        request_scope_errors,
        raw_http_exception_errors,
        list_envelope_errors,
        secret_binding_errors,
        services_escape_hatch_errors,
        contracts_snapshot_errors,
        core_api_snapshot_errors,
        module_sdk_snapshot_errors,
        module_surface_errors,
        tenancy_errors,
        reserved_surface_errors,
        baseline_ratchet_errors,
        core_isolation_errors,
        legality_errors,
        permission_errors,
        cross_module_errors,
        test_skip_errors,
    ]
    if not any(blocking):
        _print_pass_summary(
            escape_hatch_files=escape_hatch_files,
            api_import_baseline=api_import_baseline,
            baselined=baselined,
        )
        return 0

    _print_failure_summary(
        api_errors=api_errors,
        public_api_errors=public_api_errors,
        api_import_new=api_import_new,
        get_db_errors=get_db_errors,
        i18n_errors=i18n_errors,
        i18n_warnings=i18n_warnings,
        baselined=baselined,
        api_import_baseline=api_import_baseline,
        violations=violations,
    )
    return 1
