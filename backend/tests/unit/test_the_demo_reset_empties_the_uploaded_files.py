"""``docs/DEMO.md`` promises that nothing survives a reset, so the files go too.

A visitor on the demo uploads item images and attachments. The rows that point
at them live in the database, which the reset drops; the files live in the
uploads volume — or, with object storage, as keys in a bucket — which it used
to leave alone, so every night left a layer of files nothing could reach, and
the storage only grew.

Properties, tested apart because they fail apart:

* after a reset the uploads directory holds only what the seed itself wrote,
* the emptying sits behind the guard that allows the schema to be dropped,
* a path that is not an uploads directory is refused before anything is
  deleted, and links are removed rather than followed, and
* a directory that cannot be emptied does not stop the rebuild, and
* the reset service mounts the volume the backend writes the uploads to, and
* with object storage the bucket goes the same way: emptied behind the same
  guard, in the pages the store answers with — every version and delete
  marker, not only the keys a listing shows, and a store that keeps no
  versions is emptied through the listing it does have — and a store that
  refuses does not stop the rebuild either.

Everything runs against a temporary directory and an in-memory bucket; no step
but the one under test reaches the database or the network.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml
from botocore.exceptions import (  # type: ignore[import-untyped]
    ClientError,
)

from app.cli import commands_demo
from app.config import Settings, settings
from app.core.file_storage.errors import StorageError
from app.core.file_storage.providers import S3StorageProvider
from app.core.file_storage.service import FileStorageService


@pytest.fixture(autouse=True)
def _the_storage_service_keeps_no_state_between_tests():
    """The reset opens the storage service, a process-wide singleton.

    Left as it was, the next test would inherit a provider built from this
    one's settings; both halves are put back afterwards so nothing outside
    this file sees the swap.
    """
    instance, provider = FileStorageService._instance, FileStorageService._provider
    FileStorageService._instance = None
    FileStorageService._provider = None
    yield
    FileStorageService._instance, FileStorageService._provider = instance, provider


def _arrange_reset(monkeypatch, uploads: Path, order: list[str]) -> None:
    """Every step but the uploads one replaced by a note; the seed writes a file."""
    monkeypatch.setattr(commands_demo, 'guard_demo_instance', lambda: None)
    monkeypatch.setattr(commands_demo, '_clear_the_demo_inbox', lambda: None)
    monkeypatch.setattr(commands_demo, '_drop_schema', lambda: order.append('drop'))

    def _seed(*args, **kwargs) -> dict:
        order.append('seed')
        (uploads / 'seeded.jpg').write_bytes(b'from the seed')
        return {'items_total': 3}

    monkeypatch.setattr(commands_demo, '_seed_everything', _seed)
    monkeypatch.setattr(
        commands_demo, '_record_reset_time', lambda: order.append('record')
    )
    monkeypatch.setattr(settings, 'FILE_STORAGE_BACKEND', 'local')
    monkeypatch.setattr(settings, 'FILE_STORAGE_LOCAL_PATH', str(uploads))


def _visitors_files(uploads: Path) -> None:
    (uploads / 'items').mkdir()
    (uploads / 'items' / 'photo.jpg').write_bytes(b'a visitor')
    (uploads / 'attachment.pdf').write_bytes(b'another visitor')


class _FakeBucket:
    """An object store that keeps every version, the way a versioned bucket does.

    Only what emptying it touches: ``list_object_versions`` answers with a
    page of versions and delete markers, ``list_objects_v2`` with the current
    objects alone — what a delete marker hides stays hidden — and
    ``delete_objects`` removes the exact versions it is given. A delete that
    names no version lays another marker over the key instead of removing
    anything, which is the move that leaves the old bytes readable behind a
    version id; ``refuse=True`` is what a store that grants the listing and
    withholds the deletion looks like.

    A bucket whose versioning was never turned on keeps one ``null`` version
    per key, and the versions listing answers with those just the same, so
    the same fake stands for both. ``versions_listing_error`` is a store that
    answers the versions listing with a refusal of its own — the code decides
    whether the emptier may fall back to the keys it does list.
    """

    PAGE = 1000

    def __init__(
        self,
        keys: list[str] | tuple[str, ...] = (),
        *,
        refuse: bool = False,
        versioned: bool = False,
        versions_listing_error: str | None = None,
    ):
        self.versioned = versioned
        self.refuse = refuse
        self.versions_listing_error = versions_listing_error
        self.list_calls = 0
        self.served_buckets: list[str] = []
        self._versions: dict[str, list[tuple[str, bool]]] = {}
        self._issued = 0
        for key in keys:
            self.put(key)

    # The store's own moves, so a test can arrange history.
    def put(self, key: str) -> None:
        """Store another version of *key*; an unversioned bucket replaces it."""
        if self.versioned:
            self._issued += 1
            self._versions.setdefault(key, []).append((f'v{self._issued}', False))
        else:
            self._versions[key] = [('null', False)]

    def remove_key(self, key: str) -> None:
        """Delete *key* the way a client that names no version does."""
        if self.versioned:
            self._issued += 1
            self._versions.setdefault(key, []).append((f'v{self._issued}', True))
        else:
            self._versions.pop(key, None)

    def entries(self) -> list[tuple[str, str, bool]]:
        """Everything the store holds: (key, version id, is a delete marker)."""
        return [
            (key, version_id, is_marker)
            for key in sorted(self._versions)
            for version_id, is_marker in self._versions[key]
        ]

    @property
    def keys(self) -> list[str]:
        """The keys the current-objects listing answers with: none behind a marker."""
        return [
            key
            for key in sorted(self._versions)
            if self._versions[key] and not self._versions[key][-1][1]
        ]

    # What the provider calls.
    async def list_object_versions(self, **kwargs: Any) -> dict:
        if self.versions_listing_error is not None:
            raise ClientError(
                {
                    'Error': {
                        'Code': self.versions_listing_error,
                        'Message': 'the store does not do this',
                    }
                },
                'ListObjectVersions',
            )
        self.list_calls += 1
        self.served_buckets.append(str(kwargs.get('Bucket')))
        page = self.entries()[: self.PAGE]
        return {
            'Versions': [
                {'Key': key, 'VersionId': version_id}
                for key, version_id, is_marker in page
                if not is_marker
            ],
            'DeleteMarkers': [
                {'Key': key, 'VersionId': version_id}
                for key, version_id, is_marker in page
                if is_marker
            ],
        }

    async def list_objects_v2(self, **kwargs: Any) -> dict:
        self.list_calls += 1
        self.served_buckets.append(str(kwargs.get('Bucket')))
        return {'Contents': [{'Key': key} for key in self.keys[: self.PAGE]]}

    async def delete_objects(self, **kwargs: Any) -> dict:
        self.served_buckets.append(str(kwargs.get('Bucket')))
        objects = (kwargs.get('Delete') or {}).get('Objects') or []
        if self.refuse:
            return {
                'Errors': [
                    {'Key': obj['Key'], 'Message': 'AccessDenied'} for obj in objects
                ]
            }
        for obj in objects:
            key, version_id = obj['Key'], obj.get('VersionId')
            held = self._versions.get(key, [])
            if version_id is None:
                if self.versioned:
                    self._issued += 1
                    self._versions[key] = held + [(f'v{self._issued}', True)]
                else:
                    self._versions.pop(key, None)
            else:
                kept = [entry for entry in held if entry[0] != version_id]
                if kept:
                    self._versions[key] = kept
                else:
                    self._versions.pop(key, None)
        return {'Deleted': [{'Key': obj['Key']} for obj in objects]}


class _EnteredClient:
    """What ``session.client(...)`` hands back: awaited, then entered."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def __aenter__(self) -> Any:
        return self._client

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


def _point_storage_at(monkeypatch, bucket: _FakeBucket) -> None:
    """Every S3 client built from here on answers out of *bucket*."""

    async def _get_s3_client(self: S3StorageProvider) -> _EnteredClient:
        return _EnteredClient(bucket)

    monkeypatch.setattr(S3StorageProvider, '_get_s3_client', _get_s3_client)


def _storage_goes_to_object_storage(monkeypatch) -> None:
    monkeypatch.setattr(settings, 'FILE_STORAGE_BACKEND', 's3')
    monkeypatch.setattr(settings, 'FILE_STORAGE_S3_BUCKET', 'demo-bucket')
    monkeypatch.setattr(settings, 'FILE_STORAGE_S3_ACCESS_KEY', 'key')
    monkeypatch.setattr(settings, 'FILE_STORAGE_S3_SECRET_KEY', 'secret')


def _arrange_reset_with_bucket(
    monkeypatch, bucket: _FakeBucket, order: list[str]
) -> None:
    """Every step but the uploads one replaced by a note; the seed stores a cover."""
    monkeypatch.setattr(commands_demo, 'guard_demo_instance', lambda: None)
    monkeypatch.setattr(commands_demo, '_clear_the_demo_inbox', lambda: None)
    monkeypatch.setattr(commands_demo, '_drop_schema', lambda: order.append('drop'))

    def _seed(*args, **kwargs) -> dict:
        order.append('seed')
        bucket.put('recipes/cover.jpg')
        return {'items_total': 3}

    monkeypatch.setattr(commands_demo, '_seed_everything', _seed)
    monkeypatch.setattr(
        commands_demo, '_record_reset_time', lambda: order.append('record')
    )
    _storage_goes_to_object_storage(monkeypatch)
    _point_storage_at(monkeypatch, bucket)


class TestTheResetEmptiesTheUploads:
    def test_only_what_the_seed_wrote_is_left(self, monkeypatch, tmp_path):
        uploads = tmp_path / 'uploads'
        uploads.mkdir()
        _visitors_files(uploads)
        order: list[str] = []
        _arrange_reset(monkeypatch, uploads, order)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert order == ['drop', 'seed', 'record']
        assert sorted(p.name for p in uploads.iterdir()) == ['seeded.jpg']

    def test_the_directory_itself_stays_because_it_is_a_mount(
        self, monkeypatch, tmp_path
    ):
        uploads = tmp_path / 'uploads'
        uploads.mkdir()
        _visitors_files(uploads)

        removed = commands_demo.empty_uploads_directory(uploads)

        assert removed == 2
        assert uploads.is_dir()
        assert list(uploads.iterdir()) == []

    def test_a_directory_that_does_not_exist_is_nothing_to_empty(self, tmp_path):
        assert commands_demo.empty_uploads_directory(tmp_path / 'nowhere') == 0

    def test_a_link_is_removed_and_not_followed(self, tmp_path):
        """A link in the uploads must not carry the deletion out of them."""
        outside = tmp_path / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_bytes(b'not an upload')
        uploads = tmp_path / 'uploads'
        uploads.mkdir()
        (uploads / 'link').symlink_to(outside, target_is_directory=True)

        commands_demo.empty_uploads_directory(uploads)

        assert list(uploads.iterdir()) == []
        assert (outside / 'keep.txt').read_bytes() == b'not an upload'

    @pytest.mark.parametrize('path', ['/', 'uploads', ''])
    def test_a_path_that_is_not_an_uploads_directory_is_refused(self, path):
        """The path is a setting; a mistyped one must stop before it deletes."""
        with pytest.raises(commands_demo.DemoGuardError):
            commands_demo.empty_uploads_directory(Path(path))

    @staticmethod
    def _nothing_may_be_listed(monkeypatch) -> None:
        """Fail loudly if a refused path is still walked, instead of deleting for real."""

        def _walked(self):
            raise AssertionError(f'{self} was listed after it should have been refused')

        monkeypatch.setattr(Path, 'iterdir', _walked)

    @pytest.mark.parametrize('path', ['/var/..', '/app/uploads/../../', '/./', '//'])
    def test_another_spelling_of_the_filesystem_root_is_refused(
        self, monkeypatch, path
    ):
        """``/var/..`` is the filesystem root as much as ``/`` is."""
        self._nothing_may_be_listed(monkeypatch)

        with pytest.raises(commands_demo.DemoGuardError):
            commands_demo.empty_uploads_directory(Path(path))

    def test_a_link_that_leads_to_the_filesystem_root_is_refused(
        self, monkeypatch, tmp_path
    ):
        """The setting may name a link; what counts is where it ends up."""
        alias = tmp_path / 'uploads'
        alias.symlink_to('/', target_is_directory=True)
        self._nothing_may_be_listed(monkeypatch)

        with pytest.raises(commands_demo.DemoGuardError):
            commands_demo.empty_uploads_directory(alias)

    def test_a_directory_that_holds_the_application_code_is_refused(self, monkeypatch):
        """An uploads setting that is an ancestor of the code is not an uploads directory.

        On a dev stack ``/app`` is the host's source tree, mounted in; the
        sweep would delete it. Every ancestor counts, the code's own
        directory included.
        """
        code = Path(commands_demo.__file__).resolve()
        self._nothing_may_be_listed(monkeypatch)

        for ancestor in code.parents:
            if ancestor == Path(ancestor.anchor):
                continue  # the filesystem root has its own refusal
            with pytest.raises(commands_demo.DemoGuardError):
                commands_demo.empty_uploads_directory(ancestor)

    def test_a_spelling_that_leads_to_the_code_is_refused(self, monkeypatch):
        """``<code dir>/uploads/..`` ends up in the code as much as the code dir does."""
        code_dir = Path(commands_demo.__file__).resolve().parent
        self._nothing_may_be_listed(monkeypatch)

        with pytest.raises(commands_demo.DemoGuardError):
            commands_demo.empty_uploads_directory(code_dir / 'uploads' / '..')

    def test_a_spelling_with_dots_that_stays_inside_is_still_emptied(self, tmp_path):
        """The guard reads where the path ends up, not whether it contains dots."""
        uploads = tmp_path / 'uploads'
        uploads.mkdir()
        (uploads / 'a.png').write_bytes(b'x')
        (tmp_path / 'other').mkdir()

        removed = commands_demo.empty_uploads_directory(
            tmp_path / 'other' / '..' / 'uploads'
        )

        assert removed == 1
        assert list(uploads.iterdir()) == []

    def test_files_kept_elsewhere_are_not_touched(self, monkeypatch, tmp_path):
        """With object storage there is no local directory to empty."""
        uploads = tmp_path / 'uploads'
        uploads.mkdir()
        _visitors_files(uploads)
        order: list[str] = []
        _arrange_reset(monkeypatch, uploads, order)
        monkeypatch.setattr(settings, 'FILE_STORAGE_BACKEND', 's3')

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert (uploads / 'attachment.pdf').exists()


class TestTheGuardStandsInFrontOfTheUploads:
    """The files are deleted wherever, and only where, the schema may be dropped."""

    def test_an_instance_that_is_not_a_demo_keeps_its_files(
        self, monkeypatch, tmp_path
    ):
        uploads = tmp_path / 'uploads'
        uploads.mkdir()
        _visitors_files(uploads)
        # The real guard, not the stub: the marker is simply not there.
        monkeypatch.setattr(settings, 'FILE_STORAGE_BACKEND', 'local')
        monkeypatch.setattr(settings, 'FILE_STORAGE_LOCAL_PATH', str(uploads))
        monkeypatch.delenv(commands_demo.DEMO_MARKER_ENV, raising=False)
        order: list[str] = []
        monkeypatch.setattr(commands_demo, '_drop_schema', lambda: order.append('drop'))

        with pytest.raises(typer.Exit):
            commands_demo.reset(
                items=3, admin_email='a@example.com', admin_password='x'
            )

        assert order == []
        assert (uploads / 'attachment.pdf').exists()
        assert (uploads / 'items' / 'photo.jpg').exists()

    def test_production_keeps_its_files_even_when_the_marker_says_demo(
        self, monkeypatch, tmp_path
    ):
        uploads = tmp_path / 'uploads'
        uploads.mkdir()
        _visitors_files(uploads)
        monkeypatch.setattr(settings, 'FILE_STORAGE_BACKEND', 'local')
        monkeypatch.setattr(settings, 'FILE_STORAGE_LOCAL_PATH', str(uploads))
        monkeypatch.setenv(commands_demo.DEMO_MARKER_ENV, 'true')
        monkeypatch.setenv('INVENTARI_ENV', 'production')
        monkeypatch.setattr(
            commands_demo,
            '_drop_schema',
            lambda: pytest.fail('the schema was dropped in production'),
        )

        with pytest.raises(typer.Exit):
            commands_demo.reset(
                items=3, admin_email='a@example.com', admin_password='x'
            )

        assert (uploads / 'attachment.pdf').exists()


class TestADirectoryThatCannotBeEmptiedDoesNotStopTheRebuild:
    def test_the_seed_still_runs(self, monkeypatch, tmp_path):
        uploads = tmp_path / 'uploads'
        uploads.mkdir()
        order: list[str] = []
        _arrange_reset(monkeypatch, uploads, order)

        def _refuse(root: Path) -> int:
            raise PermissionError('not ours to delete')

        monkeypatch.setattr(commands_demo, 'empty_uploads_directory', _refuse)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert order == ['drop', 'seed', 'record']


class TestTheResetEmptiesObjectStorage:
    """Object storage: after the reset the bucket holds what the seed wrote."""

    def test_only_what_the_seed_wrote_is_left_in_the_bucket(self, monkeypatch):
        bucket = _FakeBucket(
            ['org-1/cover.jpg', 'org-2/attachment.pdf', 'sandbox/cover.jpg']
        )
        order: list[str] = []
        _arrange_reset_with_bucket(monkeypatch, bucket, order)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert order == ['drop', 'seed', 'record']
        assert bucket.keys == ['recipes/cover.jpg']

    def test_an_object_store_that_cannot_be_emptied_does_not_stop_the_rebuild(
        self, monkeypatch
    ):
        """A listing granted and a deletion withheld is a warning, not a halt."""
        bucket = _FakeBucket(['org-1/cover.jpg'], refuse=True)
        order: list[str] = []
        _arrange_reset_with_bucket(monkeypatch, bucket, order)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert order == ['drop', 'seed', 'record']

    def test_an_instance_that_is_not_a_demo_keeps_its_objects(self, monkeypatch):
        """The real guard, not the stub: the marker is simply not there."""
        bucket = _FakeBucket(['org-1/cover.jpg'])
        _storage_goes_to_object_storage(monkeypatch)
        _point_storage_at(monkeypatch, bucket)
        monkeypatch.delenv(commands_demo.DEMO_MARKER_ENV, raising=False)
        order: list[str] = []
        monkeypatch.setattr(commands_demo, '_drop_schema', lambda: order.append('drop'))

        with pytest.raises(typer.Exit):
            commands_demo.reset(
                items=3, admin_email='a@example.com', admin_password='x'
            )

        assert order == []
        assert bucket.keys == ['org-1/cover.jpg']

    def test_a_versioned_bucket_keeps_only_what_the_seed_wrote(self, monkeypatch):
        """A previous version and a delete marker are files, not just history.

        The rows that named them went with the schema; a version id still
        opens the bytes, so a bucket that holds them has not been emptied.
        """
        bucket = _FakeBucket(
            ['org-1/cover.jpg', 'org-2/attachment.pdf'], versioned=True
        )
        bucket.put('org-1/cover.jpg')  # an older version of the same key
        bucket.remove_key('org-2/attachment.pdf')  # deleted: a marker over it
        order: list[str] = []
        _arrange_reset_with_bucket(monkeypatch, bucket, order)

        commands_demo.reset(items=3, admin_email='a@example.com', admin_password='x')

        assert order == ['drop', 'seed', 'record']
        assert [key for key, _version, _marker in bucket.entries()] == [
            'recipes/cover.jpg'
        ]


class TestTheBucketIsEmptiedWholesale:
    """The store side: every version goes, in the pages the listing answers with."""

    async def test_every_object_goes_and_the_count_comes_back(self, monkeypatch):
        bucket = _FakeBucket(['org-1/cover.jpg', 'org-2/attachment.pdf'])
        _point_storage_at(monkeypatch, bucket)
        provider = S3StorageProvider('demo-bucket', 'key', 'secret')

        removed = await provider.empty()

        assert removed == 2
        assert bucket.keys == []
        assert set(bucket.served_buckets) == {'demo-bucket'}

    async def test_a_bucket_that_spans_two_pages_is_emptied(self, monkeypatch):
        """One listing is one page; the next object may be a page away."""
        bucket = _FakeBucket([f'org-1/{number}.jpg' for number in range(1005)])
        _point_storage_at(monkeypatch, bucket)
        provider = S3StorageProvider('demo-bucket', 'key', 'secret')

        removed = await provider.empty()

        assert removed == 1005
        assert bucket.keys == []

    async def test_versions_and_delete_markers_go_too(self, monkeypatch):
        """A version id opens the bytes long after the key itself is gone.

        Listing keys and deleting them by name is not emptying a versioned
        bucket: what stays behind is every older version of a file and every
        delete marker, each readable on its own.
        """
        bucket = _FakeBucket(versioned=True)
        bucket.put('visitor/private.txt')
        bucket.put('visitor/private.txt')  # a second version of the same file
        bucket.put('org-1/old-cover.jpg')
        bucket.remove_key('org-1/old-cover.jpg')
        bucket.put('sandbox/note.txt')
        bucket.remove_key('sandbox/note.txt')
        _point_storage_at(monkeypatch, bucket)
        provider = S3StorageProvider('demo-bucket', 'key', 'secret')

        removed = await provider.empty()

        assert removed == 6
        assert bucket.entries() == []
        assert await provider.empty() == 0
        # What an operator sees through the current-objects listing agrees.
        page = await bucket.list_objects_v2(Bucket='demo-bucket')
        assert page['Contents'] == []

    async def test_a_store_with_no_versions_listing_is_emptied_by_its_keys(
        self, monkeypatch
    ):
        """A store that keeps no versions has none to leave behind.

        Cloudflare R2's S3 API implements no versioning operation at all, so
        its keys are everything it holds and the door it does answer is the
        one that empties it.
        """
        bucket = _FakeBucket(
            ['org-1/cover.jpg', 'org-2/attachment.pdf'],
            versions_listing_error='NotImplemented',
        )
        _point_storage_at(monkeypatch, bucket)
        provider = S3StorageProvider('demo-bucket', 'key', 'secret')

        removed = await provider.empty()

        assert removed == 2
        assert bucket.keys == []

    async def test_any_other_answer_to_the_listing_stops_the_emptier(self, monkeypatch):
        """A store that does list versions is never emptied by its keys.

        Deleting keys instead of versions is how old bytes survive a reset:
        on a versioned bucket every delete lays a marker over the key.
        """
        bucket = _FakeBucket(['org-1/cover.jpg'], versions_listing_error='AccessDenied')
        _point_storage_at(monkeypatch, bucket)
        provider = S3StorageProvider('demo-bucket', 'key', 'secret')

        with pytest.raises(ClientError):
            await provider.empty()

        assert bucket.keys == ['org-1/cover.jpg']

    async def test_a_store_that_refuses_stops_instead_of_listing_forever(
        self, monkeypatch
    ):
        """Keys the deletion never removed would otherwise be listed again and again."""
        bucket = _FakeBucket(['org-1/cover.jpg'], refuse=True)
        _point_storage_at(monkeypatch, bucket)
        provider = S3StorageProvider('demo-bucket', 'key', 'secret')

        with pytest.raises(StorageError):
            await provider.empty()

        assert bucket.list_calls == 1
        assert bucket.keys == ['org-1/cover.jpg']


_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


def _services(compose_file: str) -> dict[str, Any]:
    text = (_REPO_ROOT / compose_file).read_text(encoding='utf-8')
    return yaml.safe_load(text)['services']


class TestTheResetServiceSeesTheUploads:
    """A reset that cannot see the volume empties its own empty directory."""

    def test_it_mounts_the_volume_the_backend_writes_to(self) -> None:
        backend = _services('docker-compose.prod.yml')['backend']['volumes']
        reset = _services('docker-compose.demo.yml')['demo-reset']['volumes']
        default_path = Settings.model_fields['FILE_STORAGE_LOCAL_PATH'].default

        uploads_mounts = [v for v in backend if v.endswith(f':{default_path}')]
        assert uploads_mounts, 'the backend no longer mounts its uploads directory'
        assert uploads_mounts[0] in reset
