"""One-shot data backfill commands.

Currently:
  - backfill stock-moves: translate ItemHistory -> StockMove for WMS orgs.
  - backfill category-emoji: populate Category.emoji for high-confidence
    keyword matches.
"""

from __future__ import annotations

import typer
from rich.console import Console
from sqlalchemy.orm import Session

from app.cli import bootstrap_db

backfill_app = typer.Typer(no_args_is_help=True, help='One-shot data backfills.')
console = Console()


def backfill_stock_moves_impl(
    db: Session,
    batch_size: int = 1000,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Core implementation.  Returns (translated, skipped).

    Kept as a plain function (not a typer command) so tests can pass in
    a session bound to the right engine without going through pgbouncer.
    """
    from sqlalchemy import func, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.engine import CursorResult

    from app.core.module_registry import module_registry
    from app.models.item import Item
    from app.models.item_history import ItemHistory
    from app.models.stock_move import StockMove
    from app.services.stock_moves_backfill import translate_history_to_move

    module_registry.discover_modules()

    wms_org_ids = _collect_wms_org_ids(db)
    if not wms_org_ids:
        return 0, 0

    history_count = db.scalar(select(func.count()).select_from(ItemHistory))
    console.print(
        f'Found {len(wms_org_ids)} WMS org(s). '
        f'Scanning {history_count} ItemHistory rows...'
    )

    translated = 0
    skipped = 0
    last_created_at = None
    last_id = None

    while True:
        stmt = (
            select(ItemHistory, Item)
            .join(Item, Item.id == ItemHistory.item_id)
            .where(Item.organization_id.in_(wms_org_ids))
            .order_by(ItemHistory.created_at.asc(), ItemHistory.id.asc())
            .limit(batch_size)
        )
        if last_created_at is not None:
            stmt = stmt.where(
                (ItemHistory.created_at > last_created_at)
                | (
                    (ItemHistory.created_at == last_created_at)
                    & (ItemHistory.id > last_id)
                )
            )

        rows = db.execute(stmt).all()
        if not rows:
            break

        batch_inserts: list[dict] = []
        batch_skipped = 0
        for history, item in rows:
            move = translate_history_to_move(history, item)
            if move is None:
                batch_skipped += 1
                continue
            batch_inserts.append(_move_to_dict(move))

        if batch_inserts and not dry_run:
            insert_stmt = pg_insert(StockMove).values(batch_inserts)
            insert_stmt = insert_stmt.on_conflict_do_nothing(
                index_elements=['reference_type', 'reference_id'],
                index_where=StockMove.reference_type == 'item_history',
            )
            result = db.execute(insert_stmt)
            # rowcount = actual rows inserted (after ON CONFLICT skip)
            batch_translated = (
                result.rowcount if isinstance(result, CursorResult) else 0
            ) or 0
        else:
            batch_translated = len(batch_inserts) if dry_run else 0
        db.commit()

        translated += batch_translated
        skipped += batch_skipped
        last_created_at = rows[-1][0].created_at
        last_id = rows[-1][0].id
        console.print(f'progress: translated={translated} skipped={skipped}')

        if len(rows) < batch_size:
            break

    return translated, skipped


def _move_to_dict(move) -> dict:
    return {
        'id': move.id,
        'organization_id': move.organization_id,
        'product_template_id': move.product_template_id,
        'from_location_id': move.from_location_id,
        'to_location_id': move.to_location_id,
        'quantity': move.quantity,
        'lot_id': move.lot_id,
        'state': move.state,
        'reference_type': move.reference_type,
        'reference_id': move.reference_id,
        'created_by': move.created_by,
        'created_at': move.created_at,
        'updated_at': move.created_at,
        'completed_at': move.completed_at,
    }


@backfill_app.command('stock-moves')
def backfill_stock_moves(
    batch_size: int = typer.Option(1000, '--batch-size', '-b', help='Rows per batch'),
    dry_run: bool = typer.Option(
        False, '--dry-run', help='Translate and count, write nothing'
    ),
):
    """One-time: translate ItemHistory -> StockMove for WMS orgs.

    Idempotent: a re-run skips rows already in StockMove (partial unique
    index on (reference_type, reference_id) WHERE reference_type='item_history').
    """
    bootstrap_db()

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        translated, skipped = backfill_stock_moves_impl(
            db, batch_size=batch_size, dry_run=dry_run
        )
        console.print(
            f'[green]DONE[/]: {translated} moves created, '
            f'{skipped} skipped (incomplete or non-quantity).'
            + (' [yellow](dry-run)[/]' if dry_run else '')
        )
    finally:
        db.close()


def _collect_wms_org_ids(db) -> list:
    """Return ids of orgs that have at least one consumes_stock_quant module.

    ``enabled_modules`` is a JSON column (not a PG array), so we filter
    in Python after a small fetch.  Org counts are tiny.
    """
    from sqlalchemy import select

    from app.core.module_registry import module_registry
    from app.models.organization import Organization

    wms_module_names = {
        m.metadata.name
        for m in module_registry.get_all()
        if m.metadata.consumes_stock_quant
    }
    if not wms_module_names:
        return []
    orgs = db.execute(select(Organization)).scalars().all()
    return [
        org.id
        for org in orgs
        if any(name in (org.enabled_modules or []) for name in wms_module_names)
    ]


# ── backfill category-emoji ──────────────────────────────────────────────


def backfill_category_emoji_impl(
    db: Session,
    dry_run: bool = False,
) -> dict[str, int]:
    """Populate ``Category.emoji`` for rows where the cascade produces a
    high-confidence (layer 2 = keyword match) result.

    Only writes layer-2 matches. Layer-3 (vertical default) and layer-4
    (last resort) are intentionally NOT written: a future ``context_tag``
    change should still be reflected at render time, and a generic 📦
    in the DB would be a worse signal than letting the cascade resolve
    on demand.

    Idempotent: re-runs are no-ops because the query filters on
    ``emoji IS NULL``.

    Returns a counter dict suitable for printing in a summary line.
    """
    from sqlalchemy import select

    from app.models.category import Category
    from app.services.category_emoji import resolve_category_emoji_with_layer

    rows = db.execute(select(Category).where(Category.emoji.is_(None))).scalars().all()
    counts = {
        'scanned': len(rows),
        'updated': 0,
        'skipped_vertical_default': 0,
        'skipped_last_resort': 0,
        'skipped_empty': 0,
    }
    if not rows:
        return counts

    console.print(f'Scanning {counts["scanned"]} categories with emoji IS NULL...')
    for cat in rows:
        if not (cat.name or cat.code):
            counts['skipped_empty'] += 1
            continue
        glyph, layer = resolve_category_emoji_with_layer(
            emoji=None,
            name=cat.name,
            code=cat.code,
            context_tag=cat.context_tag,
        )
        if layer == 2:
            # Only mutate the SQLAlchemy object when actually applying;
            # otherwise the change would be visible inside the same
            # session even without ``db.commit()``.
            if not dry_run:
                cat.emoji = glyph
            counts['updated'] += 1
            console.print(f'  [green]match[/]  layer 2: {cat.name!r:30s} -> {glyph}')
        elif layer == 3:
            counts['skipped_vertical_default'] += 1
            console.print(
                f'  [yellow]skip [/]  layer 3 (vertical default): {cat.name!r:30s} -> {glyph}'
            )
        else:
            counts['skipped_last_resort'] += 1
            console.print(
                f'  [yellow]skip [/]  layer 4 (last resort):     {cat.name!r:30s} -> {glyph}'
            )

    if not dry_run and counts['updated'] > 0:
        db.commit()

    return counts


@backfill_app.command('category-emoji')
def backfill_category_emoji(
    dry_run: bool = typer.Option(
        True,
        '--dry-run/--apply',
        help='Default --dry-run. Pass --apply to commit changes to the DB.',
    ),
) -> None:
    """Populate Category.emoji for high-confidence keyword matches.

    Only writes layer-2 (keyword-guess) results. Vertical defaults and
    last-resort fallbacks are NOT persisted so a future ``context_tag``
    change still propagates via the cascade. Idempotent: re-runs are
    no-ops because rows with non-NULL ``emoji`` are skipped.

    Examples:
        uv run python manage.py backfill category-emoji            # dry-run
        uv run python manage.py backfill category-emoji --apply    # commit
    """
    bootstrap_db()

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        counts = backfill_category_emoji_impl(db, dry_run=dry_run)
    finally:
        db.close()

    suffix = ' [yellow](dry-run)[/]' if dry_run else ''
    console.print(
        f'[green]DONE[/]: '
        f'scanned={counts["scanned"]} '
        f'updated={counts["updated"]} '
        f'skipped_vertical={counts["skipped_vertical_default"]} '
        f'skipped_last_resort={counts["skipped_last_resort"]} '
        f'skipped_empty={counts["skipped_empty"]}'
        f'{suffix}'
    )


def _secret_leaf_parent(values: dict, path: tuple[str, ...]) -> dict | None:
    """The dict holding the leaf at *path*, or ``None`` if the path is absent."""
    node: object = values
    for segment in path[:-1]:
        if not isinstance(node, dict):
            return None
        node = node.get(segment)
    return node if isinstance(node, dict) else None


def _rebind_namespace(values: dict, module_name: str) -> tuple[int, int, list[str]]:
    """Bind one module namespace's secrets in place.

    Returns ``(rebound, already_bound, unreadable_paths)``. A value that
    cannot be read is left exactly as it is — rewriting it would store an
    empty secret over one that a key rotation might still recover.
    """
    from app.core.module_registry import module_registry
    from app.core.settings_validator import iter_secret_paths
    from app.services.crypto_service import (
        _MODULE_AEAD_PREFIX,
        UndecryptableSecretError,
        decrypt_module_secret,
        encrypt_module_secret,
    )

    module = module_registry.get(module_name)
    schema = module.get_settings_schema() if module else None
    if not schema:
        return 0, 0, []

    rebound = already = 0
    unreadable: list[str] = []
    for path in iter_secret_paths(schema):
        parent = _secret_leaf_parent(values, path)
        current = parent.get(path[-1]) if parent else None
        if not isinstance(current, str) or not current:
            continue
        if current.startswith(_MODULE_AEAD_PREFIX):
            already += 1
            continue
        try:
            plain = decrypt_module_secret(module_name, current)
        except PermissionError:
            plain = ''
        except UndecryptableSecretError:
            # A rotation killed this value too; it lands in the same
            # unreadable report and stays stored exactly as it is.
            plain = ''
        if not plain:
            unreadable.append(f'{module_name}.{".".join(path)}')
            continue
        assert parent is not None
        parent[path[-1]] = encrypt_module_secret(module_name, plain)
        rebound += 1
    return rebound, already, unreadable


@backfill_app.command('rebind-module-secrets')
def rebind_module_secrets(
    dry_run: bool = typer.Option(
        True,
        '--dry-run/--apply',
        help='Default --dry-run. Pass --apply to write the rebound values.',
    ),
) -> None:
    """One-time: bind module settings secrets to the module that owns them.

    Values written before binding existed carry no owner, so they read
    back under any module's name. Nothing breaks while they sit there —
    the reader accepts the legacy shape on purpose — but they are not
    isolated, and they will not become isolated on their own: a value is
    only rewritten when somebody happens to re-save that settings form.

    This walks ``organizations.settings``, and for every namespace of the
    shape ``module:<name>`` rewrites each secret leaf the module's schema
    declares, bound to ``<name>``. Idempotent: an already-bound value is
    recognised and left alone. Values it cannot read are left untouched
    and reported, never overwritten with an empty string.
    """
    bootstrap_db()

    import copy

    from app.database import SessionLocal
    from app.models.organization import Organization

    rebound = 0
    already = 0
    unreadable: list[str] = []

    with SessionLocal() as db:
        for org in db.query(Organization).all():
            settings = copy.deepcopy(org.settings or {})
            changed = False
            for namespace, values in list(settings.items()):
                if not namespace.startswith('module:') or not isinstance(values, dict):
                    continue
                did, was, bad = _rebind_namespace(values, namespace.split(':', 1)[1])
                rebound += did
                already += was
                unreadable.extend(f'{org.name}: {entry}' for entry in bad)
                changed = changed or bool(did)
            if changed and not dry_run:
                org.settings = settings
        if not dry_run:
            db.commit()

    verb = 'would rebind' if dry_run else 'rebound'
    console.print(f'[green]{verb} {rebound} module secret(s).[/]')
    if already:
        console.print(f'  {already} already bound — left alone.')
    for entry in unreadable:
        console.print(f'  [yellow]⚠ unreadable, left as it is: {entry}[/]')
    if dry_run:
        console.print('[yellow]Dry run — pass --apply to write.[/]')
