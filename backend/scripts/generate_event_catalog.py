#!/usr/bin/env python3
"""Generate docs/subsystems/EVENTS.md from the event payload registry.

The event catalog is auto-generated from
``app.core.contracts.events.EVENT_PAYLOAD_TYPES`` (single source of truth)
plus deprecation metadata from ``app.core._event_deprecations`` — same
pattern as ``generate_core_api_reference.py`` for CORE_API.md.

Usage:
    docker compose exec -T backend python scripts/generate_event_catalog.py > docs/subsystems/EVENTS.md
    python backend/scripts/generate_event_catalog.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
DEFAULT_OUTPUT = _PROJECT_ROOT / 'docs' / 'subsystems' / 'EVENTS.md'


def _format_type(annotation: object) -> str:
    if isinstance(annotation, type):
        return annotation.__name__
    text = str(annotation).replace('typing.', '')
    # Escape pipes so union types don't break the Markdown table.
    return text.replace('|', '\\|')


def build_catalog() -> str:
    from app.core._event_deprecations import DEPRECATED_EVENTS
    from app.core._event_types import SystemEvent
    from app.core.contracts.events import EVENT_PAYLOAD_TYPES, TenantEventPayload

    lines: list[str] = [
        '# Event Catalog',
        '',
        'Auto-generated from `app.core.contracts.events.EVENT_PAYLOAD_TYPES` — do not edit by hand.',
        '',
        'Regenerate: `docker compose exec -T backend python scripts/generate_event_catalog.py > docs/subsystems/EVENTS.md`',
        '',
        '## Conventions',
        '',
        "- Event names are namespaced: `<module>.<event>` (core events live in `SystemEvent`, module events in the module's own `events.py`).",
        '- Tenant events carry `organization_id` (str) in the payload.',
        '- Emit via `core_api.events.emit_async` / `emit_transactional_async`; subscribe via `core_api.events.subscribe` (optional `org_filter`).',
        '- Modules declare payload contracts via `core_api.events.register_payload(name, Model)` in `on_startup`; module-owned classes live in core until the planned move (see `_payloads.py` docstrings).',
        '- Payloads are validated against the registered contract at emit time, in `event_bus.emit` itself — raw emits included (`EventValidationError`); unregistered names fail open with a warning.',
        "- Handlers run at least once. A handler that raises (or outlasts its 30 s bound) on a stream delivery is recorded in `event_deliveries` and retried alone — its sibling handlers are not re-run — up to 5 attempts with doubling backoff from 30 s; then it is parked as `dead` and the organization's admins get a notification. **Contract:** a handler raises before its side effect, or makes the side effect safe to repeat for the same event.",
        '',
        '## Events',
        '',
        '| Event | Payload type | Contract fields | Tenant | Status |',
        '|---|---|---|---|---|',
    ]

    core_names = {e.value for e in SystemEvent}
    for event_name in sorted(EVENT_PAYLOAD_TYPES):
        payload_type = EVENT_PAYLOAD_TYPES[event_name]
        tenant = 'yes' if issubclass(payload_type, TenantEventPayload) else 'no'
        fields: list[str] = []
        for fname, field in payload_type.model_fields.items():
            if fname == 'organization_id':
                continue
            required = '' if field.is_required() else '?'
            fields.append(f'`{fname}{required}`: {_format_type(field.annotation)}')
        fields_cell = ', '.join(fields) if fields else '—'
        deprecation = DEPRECATED_EVENTS.get(event_name)
        if deprecation is not None:
            status = f'**deprecated** → {deprecation.replacement} (removed in {deprecation.removal_release})'
        elif event_name in core_names:
            status = 'core'
        else:
            status = 'module'
        lines.append(
            f'| `{event_name}` | `{payload_type.__name__}` | {fields_cell} | {tenant} | {status} |'
        )

    lines += [
        '',
        '## Deprecations',
        '',
        'Deprecated events keep working until their removal release; the bus logs a warning on emit.',
        '',
        '| Event | Replacement | Removal release |',
        '|---|---|---|',
    ]
    for event_name in sorted(DEPRECATED_EVENTS):
        deprecation = DEPRECATED_EVENTS[event_name]
        lines.append(
            f'| `{event_name}` | {deprecation.replacement} | {deprecation.removal_release} |'
        )

    lines.append('')
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--output', default=None, help='Write Markdown to this file (default: stdout).'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Exit 1 if the committed catalog (--output, or the default path) '
        'differs from the generated one.',
    )
    args = parser.parse_args()

    catalog = build_catalog()

    if args.check:
        target = Path(args.output) if args.output else DEFAULT_OUTPUT
        if not target.exists():
            print(
                f'CHECK FAILED: {target} does not exist — run without --check to generate it.'
            )
            return 1
        # Compared the way the drift test compares: the committed file is
        # written through print() (see Usage), which ends it with one more
        # newline than the catalog it printed, and an exact comparison failed
        # on that newline alone.
        if target.read_text().rstrip() != catalog.rstrip():
            print(f'CHECK FAILED: {target} is out of sync — regenerate it.')
            return 1
        print('CHECK OK: event catalog is in sync.')
        return 0

    if args.output:
        Path(args.output).write_text(catalog)
        print(f'Wrote event catalog to {args.output}', file=sys.stderr)
    else:
        print(catalog)
    return 0


if __name__ == '__main__':
    sys.exit(main())
