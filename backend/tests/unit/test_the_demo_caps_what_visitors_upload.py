"""A demo refuses uploads past its per-file and total limits; a normal install does not."""

from __future__ import annotations

import pytest

from app.config import settings
from app.core.demo_upload_cap import enforce_demo_upload_cap
from app.core.exceptions import AppException

_MB = 1024 * 1024


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'FILE_STORAGE_BACKEND', 'local')
    monkeypatch.setattr(settings, 'FILE_STORAGE_LOCAL_PATH', str(tmp_path))
    monkeypatch.setattr(settings, 'DEMO_UPLOAD_FILE_MB', 2)
    monkeypatch.setattr(settings, 'DEMO_UPLOAD_TOTAL_MB', 5)
    return tmp_path


def test_a_normal_install_is_not_capped(storage, monkeypatch):
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', False)
    enforce_demo_upload_cap(20 * _MB)


def test_a_demo_refuses_a_file_over_the_per_file_limit(storage, monkeypatch):
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)
    enforce_demo_upload_cap(2 * _MB)
    with pytest.raises(AppException) as exc:
        enforce_demo_upload_cap(2 * _MB + 1)
    assert exc.value.status_code == 413
    assert exc.value.detail['code'] == 'DEMO_UPLOAD_FILE_LIMIT'


def test_a_demo_refuses_an_upload_that_passes_the_total(storage, monkeypatch):
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)
    (storage / 'org').mkdir()
    (storage / 'org' / 'a.bin').write_bytes(b'x' * (4 * _MB))
    enforce_demo_upload_cap(1 * _MB)
    with pytest.raises(AppException) as exc:
        enforce_demo_upload_cap(1 * _MB + 1)
    assert exc.value.detail['code'] == 'DEMO_UPLOAD_TOTAL_LIMIT'
    assert '5 MB' in exc.value.detail['message']


async def test_the_storage_facade_asks_the_cap_before_it_writes(storage, monkeypatch):
    """Every module stores through this call, so the cap must sit on it."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.core.public_api import file_storage as fs_mod

    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)
    service = MagicMock()
    service.save = AsyncMock()

    with patch.object(fs_mod, 'FileStorageService', return_value=service):
        with pytest.raises(AppException) as exc:
            await fs_mod.CoreFileStorageAPI().save_for_org_async(
                uuid.uuid4(), 'mod_a', 'big.bin', b'x' * (2 * _MB + 1)
            )

    assert exc.value.detail['code'] == 'DEMO_UPLOAD_FILE_LIMIT'
    service.save.assert_not_called()


def _real_storage(storage, monkeypatch):
    """Point the storage singleton at the temporary directory, writes included."""
    from app.core.file_storage.providers import LocalStorageProvider
    from app.core.file_storage.service import FileStorageService

    monkeypatch.setattr(
        FileStorageService(), '_provider', LocalStorageProvider(storage), raising=False
    )


def _stored(storage) -> int:
    return sum(p.stat().st_size for p in storage.rglob('*') if p.is_file())


async def _upload_one_mb(index: int) -> bool:
    """Try to store 1 MB under its own name; say whether the demo took it."""
    import uuid

    from app.core.public_api.file_storage import CoreFileStorageAPI

    try:
        await CoreFileStorageAPI().save_for_org_async(
            uuid.uuid4(), 'mod_a', f'{index}.bin', b'x' * _MB
        )
    except AppException as exc:
        assert exc.detail['code'] == 'DEMO_UPLOAD_TOTAL_LIMIT'
        return False
    return True


async def test_uploads_arriving_together_cannot_pass_the_total(storage, monkeypatch):
    """Checking the room and writing are one step, or twenty visitors all see room.

    Each of twenty megabyte uploads asks "is there room?" while the disk still
    holds nothing, so a check made apart from the write admits every one of them.
    """
    import asyncio

    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)
    monkeypatch.setattr(settings, 'DEMO_UPLOAD_FILE_MB', 2)
    monkeypatch.setattr(settings, 'DEMO_UPLOAD_TOTAL_MB', 2)
    _real_storage(storage, monkeypatch)

    taken = await asyncio.gather(*(_upload_one_mb(i) for i in range(20)))

    assert sum(taken) == 2
    assert _stored(storage) == 2 * _MB


def _a_worker_uploads(first: int) -> int:
    import asyncio

    async def _five() -> int:
        return sum(await asyncio.gather(*(_upload_one_mb(first + n) for n in range(5))))

    return asyncio.run(_five())


def test_workers_in_separate_processes_share_one_total(storage, monkeypatch):
    """The production backend runs several workers; the total is the instance's.

    Four processes each try five megabyte uploads against a two megabyte total.
    """
    import multiprocessing

    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)
    monkeypatch.setattr(settings, 'DEMO_UPLOAD_FILE_MB', 2)
    monkeypatch.setattr(settings, 'DEMO_UPLOAD_TOTAL_MB', 2)
    _real_storage(storage, monkeypatch)

    with multiprocessing.get_context('fork').Pool(4) as pool:
        taken = pool.map(_a_worker_uploads, [0, 5, 10, 15])

    assert sum(taken) == 2
    assert _stored(storage) == 2 * _MB
