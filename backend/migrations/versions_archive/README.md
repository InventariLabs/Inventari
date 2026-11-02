# Migration chains this repository no longer replays — reference only

Nothing here runs. `migrations/versions/` holds the chain an installation
replays: the `baseline_002` revision and the few written after it.

## The 0.11.0 flattening — the chain before the first release

The 114 revisions that grew after the previous squash are in this directory
unchanged. They had two roots (`baseline_001_full_schema.py` and
`001_add_stock_reservations.py`, whose revision id `a1b2c3d4e5f6` was a
placeholder), four merge revisions and three forks. Several of them existed
only to repair databases created before the previous squash — `tzaware01`,
`trgmidx01`, `catorg01`, `seedfield01`, `stypei18n01` and `aiconn02` (the
stock-takes module's own `005` is the same kind, in that module's chain) — and `migrations/versions_archive/README.md`
recorded that no instance older than that squash was supported. `auditimm01`
is the other kind: it restored the audit-log trigger that the squash had left
out of every database built from the baseline.

The last three joined the old line after the first draft of this flattening:
`poolcode01` widened `label_pool.short_code` to the length a location's code
may have, `docurl01` rewrote the stored notification links from `/documents`
to `/warehouse/documents`, and `docvis01` merged the two heads. The first is
the baseline's column width now; the second changed rows, not tables.

They are kept for reading; the objects they explain are now in
`migrations/versions/baseline_002_full_schema.py`, which builds the schema the
previous head (`docvis01`) left, including the audit trigger, the stock
guard, the quantities-from-records view and the seven trigram indexes that the
first squash lost and later revisions had to restore. A database at that head
is stamped onto the baseline (`manage.py db stamp-baseline`) rather than
replayed; the stamp checks the recorded revision too, because a database that
stopped one revision earlier can have the same schema and still keep the old
notification links. `DEPLOYMENT.md` has the upgrade procedure.

## The first squash — the chain before 2026-06-10

The 155 migrations that were already here built the schema before it was
squashed into `baseline_001_full_schema.py`. A database built through that
chain differs from a fresh one (missing primary keys, nullable tenancy
columns, a purchase-order number unique across organizations), and no
migration brings it in line: no instance that predates that squash is
supported.

The two generations share this directory and file names do not tell them
apart: Alembic's default template gave `<hex revision>_<slug>.py`, this project
mostly writes `<key01>_<slug>.py`, but a few later revisions carry hand-typed
hex ids (`e5f6a7b8c9d0_merge_wms_pick_branch.py`). Git history records which
commit moved which.

They stay for reading — some module migrations cite the archived revision
whose object they restore or replace.
