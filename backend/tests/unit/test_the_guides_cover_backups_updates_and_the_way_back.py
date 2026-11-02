"""The guides cover what the backup misses, the update, and the way back.

The nightly job reaches two things — the database and the ``uploads_data``
volume — and the backup section listed no exceptions, so an administrator
reading it took the archive next to the dump for the whole installation:
files stored in S3, the ``module_data`` volume, the community module trees in
the checkout and the TLS certificates were kept by nobody, and the guide did
not say so. The rollback example checked out the tag the update had just
moved to, the updating steps never said that the backend's entrypoint
migrates on every start (so the explicit ``db upgrade`` looked like the real
migration), and QUICK_DEPLOY.md ended at Troubleshooting — no update, and no
rule about the backup to take before one.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_DEPLOYMENT = _REPO_ROOT / 'DEPLOYMENT.md'
_QUICK = _REPO_ROOT / 'QUICK_DEPLOY.md'


def _section(document: Path, heading: str) -> str:
    """The text under `## <heading>`, up to the next `## ` heading."""
    text = document.read_text(encoding='utf-8')
    for part in re.split(r'^## ', text, flags=re.MULTILINE)[1:]:
        if part.splitlines()[0].strip() == heading:
            return part
    raise AssertionError(f'{document.name} has no `## {heading}` heading')


def _subsection(section: str, heading: str) -> str:
    """The text under `### <heading>`, up to the next `### ` or `## ` heading."""
    for part in re.split(r'^#{2,3} ', section, flags=re.MULTILINE)[1:]:
        if part.splitlines()[0].strip() == heading:
            return part
    raise AssertionError(f'section has no `### {heading}` heading')


class TestTheBackupsSectionSaysWhatTheNightlyRunMisses:
    """Four things live outside the service's mount; each needs a how."""

    @pytest.fixture(scope='class')
    def backups(self) -> str:
        return _section(_DEPLOYMENT, 'Database Backups')

    def test_each_of_the_four_is_named(self, backups: str) -> None:
        assert 'FILE_STORAGE_BACKEND=s3' in backups, 'S3 files not named'
        assert 'module_data' in backups, 'the tracking volume not named'
        assert 'backend/app/modules' in backups, 'the module code not named'
        assert 'frontend/src/modules' in backups, 'the module code not named'
        assert 'caddy_data' in backups, 'the certificate volume not named'

    def test_each_comes_with_a_way_to_cover_it(self, backups: str) -> None:
        # S3: the bucket is covered where it lives, and the secret that
        # reaches it is part of what is kept off the server.
        assert 'versioning' in backups, 'no way given to cover the bucket'
        assert 'FILE_STORAGE_S3_SECRET_KEY' in backups
        # The two volumes: an archive command, not a mention.
        assert 'tar -C /app/data' in backups, 'no command for module_data'
        assert 'tar -C /data' in backups, 'no command for caddy_data'
        # The module code: a tar of the two trees in the checkout.
        assert re.search(r'tar -czf \S*module-code', backups), (
            'no command given for the module trees'
        )

    def test_every_archive_name_carries_the_time_it_was_written(
        self, backups: str
    ) -> None:
        """Two runs in one day are two restore points, not one.

        The prose tells the reader to take these beside the pre-update dump
        and again whenever the set of modules changes. A name carrying only
        the date makes the second run land on the first, so the dump put
        aside for the rollback keeps no archives of its own — the defect the
        commands introduce for every one of the three, not one example.
        """
        for name in ('module-data', 'caddy-data', 'module-code'):
            stamps = re.findall(rf'{name}-\$\(date -u \+([^)]+)\)', backups)
            assert stamps, f'no archive command found for {name}'
            for stamp in stamps:
                assert stamp == '%Y%m%d-%H%M%S', (
                    f'{name} is named without the time of the run: a second '
                    'archive the same day replaces the earlier restore point'
                )


class TestTheRollbackChecksOutTheTagTheUpdateLeft:
    """The example goes back, not forward a second time."""

    @pytest.fixture(scope='class')
    def updating(self) -> str:
        return _section(_DEPLOYMENT, 'Updating')

    def test_the_update_and_the_rollback_check_out_different_tags(
        self, updating: str
    ) -> None:
        checkouts = re.findall(r'^git checkout (.+)$', updating, flags=re.MULTILINE)

        assert len(checkouts) == 2, 'the update and the rollback each check out'
        assert checkouts[0] != checkouts[1], (
            'the rollback example checks out the tag the update just moved to'
        )

    def test_the_rollback_names_it_as_the_tag_you_came_from(
        self, updating: str
    ) -> None:
        rollback = _subsection(updating, 'When an update fails')

        assert 'tag you came from' in rollback


class TestTheUpdatingSectionSaysWhoMigratesAndWhatTheStepAdds:
    """The entrypoint has already migrated; step 6 is there to be seen."""

    @pytest.fixture(scope='class')
    def updating(self) -> str:
        return _section(_DEPLOYMENT, 'Updating')

    def test_the_entrypoint_migrating_on_start_is_stated(self, updating: str) -> None:
        assert 'entrypoint' in updating
        assert 'migrates on every start' in updating

    def test_the_repeat_is_explained_and_the_step_earns_its_place(
        self, updating: str
    ) -> None:
        # Why running them again cannot change anything twice ...
        assert 'already applied' in updating
        # ... and what the explicit step adds over the entrypoint's own pass:
        # the result where the operator can see it.
        assert 'docker compose logs backend' in updating


class TestQuickDeployHasAnUpdatingSectionThatStartsWithABackup:
    """A tag alone leaves the old images running; the backup comes first."""

    @pytest.fixture(scope='class')
    def updating(self) -> str:
        return _section(_QUICK, 'Updating')

    def test_the_backup_is_taken_before_the_full_procedure_is_named(
        self, updating: str
    ) -> None:
        backup = updating.find('BACKUP_ONCE=true db-backup')
        guide = updating.find('DEPLOYMENT.md#updating')

        assert backup != -1, 'no backup to take before the update'
        assert guide != -1, 'the full procedure is not a link away'
        assert backup < guide, 'the guide is pointed at before the backup'
        assert 'backups/before-update' in updating, (
            'the backup is not set aside for the rollback'
        )
