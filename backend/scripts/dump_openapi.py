#!/usr/bin/env python
"""Dump the app's OpenAPI schema in its canonical, committable form.

What this dump is for
---------------------
`docs/api/openapi.json` is a *maintained artifact*: the canonical export of
the REST schema for readers who explore the API without running the backend
(Postman / Insomnia / Bruno import — see MODULES_GUIDE.md). Production serves
no `/openapi.json` (`main.py` gates it on DEBUG), so the committed file is
the only export there is. `make check-openapi-fresh` (in `make
check-frontend`) compares this dump against the committed file and fails on
drift — that gate, not anyone's memory, is what keeps the artifact current.
Run `make generate-openapi` after changing endpoints or response models.

Why the canonical form
----------------------
The dump is canonicalised — `paths` and `components.schemas` sorted by key —
so the artifact is a function of the API alone. Router registration order
follows module discovery order, and while discovery is sorted today, any
variance in that order would otherwise make two hosts serving the identical
API produce byte-different files, and the freshness gate would fail on a
diff nobody can act on. The TS-types pipeline canonicalises the schema for
the same reason (see `frontend/scripts/generate-api-types.sh`).

Usage:
    python -m scripts.dump_openapi            # canonical dump to stdout
    make generate-openapi                     # write docs/api/openapi.json
    make check-openapi-fresh                  # fail when the artifact drifted

`-m` (not `python scripts/dump_openapi.py`): running a file by path puts the
file's own directory on `sys.path` instead of the project root, and the app
package would not import.
"""

from __future__ import annotations

import json
from typing import Any


def canonical(schema: dict[str, Any]) -> dict[str, Any]:
    """Sort the path and schema maps so the dump depends on the API alone.

    Only the two maps whose key order follows router/model registration
    order are touched; every other key keeps the order the code declared
    it in, and any content is left byte-identical.
    """
    if 'paths' in schema:
        schema['paths'] = dict(sorted(schema['paths'].items()))
    components = schema.get('components')
    if isinstance(components, dict) and 'schemas' in components:
        components['schemas'] = dict(sorted(components['schemas'].items()))
    return schema


def main() -> int:
    # Late import: building the app logs ~60 startup lines to stderr and
    # needs no server, no lifespan, no database — a plain import produces
    # the schema a served one would (see the comment over OPENAPI_JSON in
    # the Makefile).
    from app.main import app

    print(json.dumps(canonical(app.openapi()), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
