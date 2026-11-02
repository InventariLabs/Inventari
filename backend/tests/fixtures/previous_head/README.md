# The database the previous core chain left behind

`previous_chain_docvis01.sql.gz` is the database the pre-0.11.0 core
migration chain built at its last revision (`docvis01`) — the schema, the rows
the first run writes and the demo seed; the file is named after that chain
and revision, not after a release. It was cut with the demo reset and dump procedure of
`scripts/release-db-snapshot.sh`, from the development line before the chain
was flattened into `baseline_002` and after the last three revisions joined it
(`poolcode01`, `docurl01`, `docvis01`). It is not a release snapshot and
`test_a_released_database_upgrades_to_head` does not read it.

`tests/integration/test_a_previous_chain_database_is_stamped.py` restores it
and runs `manage.py db stamp-baseline` over it, which is the upgrade path for
an installation created before the release. The test fails if the stamp
changes a row, if the stamped revision is not the baseline, if the schema
stops matching the models, or if a database that is not at that head is
accepted.

The chain's last revision moves while the release is being prepared, so this
file is cut again from the line that still carried the chain — never from this
checkout, which no longer replays it: the test needs the schema and the rows
the old code left, not the current baseline. A change to the baseline itself
is covered by `backend/tests/fixtures/release_databases/` instead.
