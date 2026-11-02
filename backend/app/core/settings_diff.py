"""What moved between two readings of one settings record.

A module's own configuration endpoints (a document profile, a purchase
order's approval flag) used to write without a trace, exactly like the
shared module-settings path once did. Building the journal entry's
before/after is mechanical and lives here once: name the top-level keys
that changed, mask the leaves marked secret, and answer ``None`` when
nothing moved — a journal records changes, not keystrokes.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import inspect

#: The display form of a secret the reader is not shown. Lives here so a
#: core helper and the crypto layer spell it identically; the crypto module
#: re-exports it.
MASKED_VALUE = '**********'

#: How a stored secret starts. Lives beside the mask for the same reason:
#: the journal has to recognise a ciphertext without importing the crypto
#: layer, which sits above it. ``crypto_service`` reads its own prefix from
#: here so the two cannot drift apart.
CIPHERTEXT_PREFIX = 'enc:'

#: What the "after" side of a rotated secret reads as. Masking each side on
#: its own collapses two different keys into the same ten asterisks, and the
#: reading side drops a line whose halves are equal — so a key that had just
#: been replaced showed up as a dash in the Details column. The value stays
#: hidden; the fact that it moved does not. The reader's interface turns
#: this into words, the way it already does for other sentinels.
ROTATED_VALUE = 'ROTATED_VALUE'


async def journal_config_change(
    db: Any,
    org_id: Any,
    user_id: Any,
    *,
    module: str,
    subject: str,
    keys: set[str],
    before: Any,
    after: Any,
    secret_paths: frozenset[tuple[str, ...]] | set[tuple[str, ...]] | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Journal one module-owned configuration write when — and only when —
    it moved.

    `before` and `after` are the same record read on both sides of the
    write (``after=None`` reads as a deletion); `keys` limits the snapshot
    to what the payload could have moved, so unrelated column churn (a
    timestamp the refresh bumps) cannot dress up as a change. The entry is
    the same shape the shared module-settings path writes: actor, module,
    subject, and a before/after naming the keys that moved.

    `secret_paths` names the leaves whose value the journal must not carry.
    Left unsaid it is read from the module's own settings schema — the same
    authority the shared settings path asks — so a module that declares a
    secret gets it masked here too, on routes nobody remembered to tell.

    `context` is which record the entry is about, written beside the two
    sides whatever moved: an edit that changed only a shelf's limit still
    names the shelf and the product, by id and by the name each had then
    (AUDIT.md, "A reference is written with its name").
    """
    from app.core.contracts import AuditAction, AuditTargetType
    from app.core.public_api import core_api
    from app.services.audit_service import audit_value

    before_map = _restricted(before, keys)
    after_map = _restricted(after, keys)
    if secret_paths is None:
        secret_paths = _module_secret_paths(module)
    snapshot = changed_settings_snapshot(before_map, after_map, secret_paths)
    if snapshot is None:
        return
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.MODULE,
        target_id=org_id,
        snapshot={
            'name': module,
            'subject': subject,
            **audit_value(context or {}),
            **snapshot,
        },
    )


def _restricted(record: Any, keys: set[str]) -> dict[str, Any]:
    if record is None:
        return {}
    return {key: value for key, value in record_settings(record).items() if key in keys}


def _module_secret_paths(module: str) -> frozenset[tuple[str, ...]]:
    """The leaves this module declares secret, read where the shared
    module-settings path reads them: the module's own settings schema.

    A module-owned route journals rows, not the settings blob, so the two
    vocabularies need not overlap — a module that names none of its columns
    there gets the empty set, and the ciphertext backstop below still holds.
    """
    from app.core.logging import get_logger
    from app.core.module_registry import module_registry
    from app.core.settings_validator import iter_secret_paths

    instance = module_registry.get(module)
    if instance is None:
        return frozenset()
    try:
        schema = instance.get_settings_schema()
    except Exception:  # noqa: BLE001 — a module's own code; logged with its traceback
        # Masking nothing is the unsafe direction, so a module that cannot
        # say what it keeps secret says so out loud. The ciphertext
        # backstop below is what still holds while someone reads this.
        get_logger(__name__).exception(
            'Module %s raised in get_settings_schema()', module
        )
        return frozenset()
    if not schema:
        return frozenset()
    return frozenset(iter_secret_paths(schema))


def _mask_leaf(
    value: Any,
    path: tuple[str, ...],
    secret_paths: frozenset[tuple[str, ...]] | set[tuple[str, ...]],
) -> Any:
    """One reading of one leaf, with a secret's value withheld.

    Two things make a value secret here. The schema saying so is the
    contract; a value that is already stored as ciphertext is the backstop,
    because a configuration column no schema describes would otherwise
    reach a journal that roles outside that configuration can read — and
    the gate over the declared path would stay green while it did.
    """
    if not isinstance(value, str) or not value:
        return value
    if path in secret_paths or value.startswith(CIPHERTEXT_PREFIX):
        return MASKED_VALUE
    return value


def _masked_pair(
    before: Any,
    after: Any,
    path: tuple[str, ...],
    secret_paths: frozenset[tuple[str, ...]] | set[tuple[str, ...]],
) -> tuple[Any, Any]:
    """Both readings of one leaf, masked together rather than each alone.

    Masking side by side is what turned a rotation into two identical
    masks: the pair is the only place that still knows the values differed.
    """
    if isinstance(before, dict) or isinstance(after, dict):
        before_fields = before if isinstance(before, dict) else None
        after_fields = after if isinstance(after, dict) else None
        keys = sorted(set(before_fields or {}) | set(after_fields or {}))
        pairs = {
            key: _masked_pair(
                (before_fields or {}).get(key),
                (after_fields or {}).get(key),
                path + (key,),
                secret_paths,
            )
            for key in keys
        }
        return (
            {key: pairs[key][0] for key in before_fields}
            if before_fields is not None
            else before,
            {key: pairs[key][1] for key in after_fields}
            if after_fields is not None
            else after,
        )

    masked_before = _mask_leaf(before, path, secret_paths)
    masked_after = _mask_leaf(after, path, secret_paths)
    if before != after and masked_before == masked_after == MASKED_VALUE:
        masked_after = ROTATED_VALUE
    return masked_before, masked_after


def record_settings(record: Any) -> dict[str, Any]:
    """A record as the plain JSON-safe settings dict it effectively is.

    Module-owned configuration lives in rows, not in the JSON blob the
    shared settings path reads, and its columns carry UUIDs, timestamps and
    structured values a journal entry cannot hold raw. They are rendered the
    way every other journal entry renders them (``audit_value``): a UUID as
    its string, a JSON column as a walked copy rather than its Python repr.
    A plain mapping passes through with the same rendering.

    A ``Decimal`` alone stays a number until the entry is written. As digits,
    the ``8.00`` a column holds and the ``8`` a form posts read as a change,
    and every resave of an untouched rate wrote one.
    """
    from app.services.audit_service import audit_value

    if isinstance(record, dict):
        items: list[tuple[str, Any]] = list(record.items())
    else:
        items = [
            (column.key, getattr(record, column.key))
            for column in inspect(record).mapper.column_attrs
        ]
    return {
        key: value if isinstance(value, Decimal) else audit_value(value)
        for key, value in items
    }


def changed_settings_snapshot(
    before: dict[str, Any],
    after: dict[str, Any],
    secret_paths: frozenset[tuple[str, ...]] | set[tuple[str, ...]] = frozenset(),
) -> dict[str, dict[str, Any]] | None:
    """Before/after for the top-level keys that moved, secrets masked.

    Detection reads the raw values; a secret is compared by whatever the
    caller stored, so a resave of an unchanged secret shows up as no change
    and a genuinely new value names the key while the snapshot shows only
    the mask — and, where the value moved, says so rather than printing the
    same ten asterisks twice.

    Whether a key moved is ``audit_key``'s answer, the one every other
    journal entry asks: a number as a number, a mapping whatever order its
    keys came in. What is written is ``audit_value``'s.
    """
    from app.services.audit_service import audit_key, audit_value

    changed = [
        key
        for key in sorted(set(before) | set(after))
        if audit_key(before.get(key)) != audit_key(after.get(key))
    ]
    if not changed:
        return None
    pairs = {
        key: _masked_pair(before.get(key), after.get(key), (key,), secret_paths)
        for key in changed
    }
    return {
        'before': {key: audit_value(pair[0]) for key, pair in pairs.items()},
        'after': {key: audit_value(pair[1]) for key, pair in pairs.items()},
    }
