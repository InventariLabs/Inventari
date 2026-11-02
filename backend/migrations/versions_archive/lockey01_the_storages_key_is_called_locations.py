"""the storages key is called locations: carry its stored values across

Revision ID: lockey01
Revises: locreloc01
Create Date: 2026-10-22

The core feature that keeps the shelves under the inventory was relabelled
Locations, and its key followed before the first release. An installation
that ran the old key stored it by name in three shapes, and every one of them
is rewritten here:

* ``organizations`` — the module lists (``enabled_modules``,
  ``allowed_modules``, ``pre_focus_enabled_modules``,
  ``pre_onboarding_manual_modules``), ``focus_module`` and the
  ``module:storages`` namespace in ``settings``;
* ``roles.permissions`` — ``storages:read`` and ``storages:write`` become
  ``locations:read`` and ``locations:write``;
* ``webhook_endpoints.event_types`` — ``storage.created``,
  ``storage.updated`` and ``storage.deleted`` become ``location.*``. An
  outside receiver filters on these names, so a subscription left on the
  old spelling would silently stop firing.

Where both spellings are present, the old one is the record and the new one
is dropped: nothing under the new key can predate this revision.

The sweep found no other place that stores the key. The ``module_name``
columns on items, categories and item types, and the ``module`` of a
document template, record which module a row came from — this feature is
always-on core and owns no such row — and ``emitter_module`` names the
module that emitted an event, never the core feature the event is about. A
``module_installations`` row cannot exist either: the feature has no module
directory to install.

Left as they are, on purpose: ``audit_log`` is append-only in the database
(a trigger refuses an UPDATE) and records what happened under the name it
had, and a webhook delivery log records what was sent to a receiver —
rewriting either would make the log say something else happened.

A data migration of its own, with no schema change. ``webhook_endpoints``
belongs to the webhooks module, so that step runs only where the table is
installed.
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import context, op

revision: str = 'lockey01'
down_revision: str | None = 'locreloc01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = 'storages'
NEW = 'locations'

_OLD_EVENTS = ('storage.created', 'storage.updated', 'storage.deleted')
_NEW_EVENTS = ('location.created', 'location.updated', 'location.deleted')
_EVENTS = dict(zip(_OLD_EVENTS, _NEW_EVENTS, strict=True))

_MODULE_LISTS = (
    'enabled_modules',
    'allowed_modules',
    'pre_focus_enabled_modules',
    'pre_onboarding_manual_modules',
)


def _renamed_list(names: list[str] | None, old: str, new: str) -> list[str] | None:
    if not names or old not in names:
        return names
    out: list[str] = []
    for name in names:
        name = new if name == old else name
        if name not in out:
            out.append(name)
    return out


def _renamed_permissions(keys: list[str], old: str, new: str) -> list[str]:
    out: list[str] = []
    for key in keys:
        if key.startswith(f'{old}:'):
            key = f'{new}:{key[len(old) + 1 :]}'
        if key not in out:
            out.append(key)
    return out


def _renamed_events(
    events: list[str] | None, events_map: dict[str, str]
) -> list[str] | None:
    if not events or not any(event in events_map for event in events):
        return events
    out: list[str] = []
    for event in events:
        event = events_map.get(event, event)
        if event not in out:
            out.append(event)
    return out


def _renamed_settings(
    settings: dict[str, Any] | None, old: str, new: str
) -> dict[str, Any] | None:
    if not settings or f'module:{old}' not in settings:
        return settings
    out = {key: value for key, value in settings.items() if key != f'module:{old}'}
    out.setdefault(f'module:{new}', settings[f'module:{old}'])
    return out


def _rename_organizations(bind: sa.Connection, old: str, new: str) -> None:
    columns = ', '.join(_MODULE_LISTS)
    rows = bind.execute(
        sa.text(f'SELECT id, {columns}, settings FROM organizations')
    ).mappings()
    for row in rows.all():
        changes: dict[str, Any] = {}
        for column in _MODULE_LISTS:
            renamed = _renamed_list(row[column], old, new)
            if renamed != row[column]:
                changes[column] = renamed
        settings = _renamed_settings(row['settings'], old, new)
        if settings != row['settings']:
            changes['settings'] = settings
        if not changes:
            continue
        assignments = ', '.join(
            f'{column} = CAST(:{column} AS JSON)' for column in changes
        )
        bind.execute(
            sa.text(f'UPDATE organizations SET {assignments} WHERE id = :id'),
            {
                'id': row['id'],
                **{key: json.dumps(value) for key, value in changes.items()},
            },
        )
    bind.execute(
        sa.text(
            'UPDATE organizations SET focus_module = :new WHERE focus_module = :old'
        ),
        {'old': old, 'new': new},
    )


def _rename_roles(bind: sa.Connection, old: str, new: str) -> None:
    rows = bind.execute(
        sa.text(
            'SELECT id, permissions FROM roles '
            'WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(permissions) AS p '
            'WHERE p LIKE :prefix)'
        ),
        {'prefix': f'{old}:%'},
    ).mappings()
    for row in rows.all():
        bind.execute(
            sa.text(
                'UPDATE roles SET permissions = CAST(:permissions AS JSONB) WHERE id = :id'
            ),
            {
                'id': row['id'],
                'permissions': json.dumps(
                    _renamed_permissions(row['permissions'], old, new)
                ),
            },
        )


def _rename_webhook_events(bind: sa.Connection, events_map: dict[str, str]) -> None:
    tables = set(sa.inspect(bind).get_table_names())
    if 'webhook_endpoints' not in tables:
        return
    rows = bind.execute(
        sa.text('SELECT id, event_types FROM webhook_endpoints')
    ).mappings()
    for row in rows.all():
        renamed = _renamed_events(row['event_types'], events_map)
        if renamed == row['event_types']:
            continue
        bind.execute(
            sa.text(
                'UPDATE webhook_endpoints SET event_types = CAST(:events AS JSONB) '
                'WHERE id = :id'
            ),
            {'id': row['id'], 'events': json.dumps(renamed)},
        )


def _rename(old: str, new: str, events_map: dict[str, str]) -> None:
    bind = op.get_bind()
    _rename_organizations(bind, old, new)
    _rename_roles(bind, old, new)
    _rename_webhook_events(bind, events_map)


def upgrade() -> None:
    # ``--sql`` mode writes the schema script from the revision files alone;
    # there is no connection to read the rows this revision carries across.
    if context.is_offline_mode():
        return
    _rename(OLD, NEW, _EVENTS)


def downgrade() -> None:
    if context.is_offline_mode():
        return
    _rename(NEW, OLD, {value: key for key, value in _EVENTS.items()})
