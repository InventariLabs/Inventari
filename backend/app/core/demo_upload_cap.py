"""What a public demo lets strangers put on its disk.

Between two resets nothing else bounds the uploads: each endpoint has a
per-file limit, none has a total. On a demo (``INVENTARI_DEMO``) the storage
facade asks here before every write, so the cap holds for every module that
stores a file without each one learning about demos. Local storage only —
the demo's compose file uses it; elsewhere the check is a no-op.

Asking and writing are one step. A check made apart from the write lets every
upload that arrives together see the same free room, and the production
backend runs several worker processes, so the step is serialised with a file
lock in the storage directory, which every worker shares.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config import settings
from app.core.exceptions import AppException
from app.core.upload_validation import format_size_limit
from app.i18n.service import get_current_lang, get_error_message

_MB = 1024 * 1024
_LOCK_NAME = '.demo-upload-admission.lock'
_LOCK_POLL_SECONDS = 0.005


def _stored_bytes(root: str) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue  # removed between listing and stat
    return total


def _is_capped() -> bool:
    return bool(settings.INVENTARI_DEMO) and settings.FILE_STORAGE_BACKEND == 'local'


def enforce_demo_upload_cap(size: int) -> None:
    """Refuse (413) a write of *size* bytes that a demo should not accept.

    Only a verdict on the room there is now: callers that go on to write hold
    :func:`demo_upload_admission`, which keeps the room from being taken
    between this answer and the write.
    """
    if not _is_capped():
        return
    lang = get_current_lang()
    file_limit = int(settings.DEMO_UPLOAD_FILE_MB * _MB)
    if size > file_limit:
        raise AppException(
            status_code=413,
            code='DEMO_UPLOAD_FILE_LIMIT',
            message=get_error_message(
                'demo_upload_file_limit', lang, limit=format_size_limit(file_limit)
            ),
        )
    total_limit = int(settings.DEMO_UPLOAD_TOTAL_MB * _MB)
    if _stored_bytes(settings.FILE_STORAGE_LOCAL_PATH) + size > total_limit:
        raise AppException(
            status_code=413,
            code='DEMO_UPLOAD_TOTAL_LIMIT',
            message=get_error_message(
                'demo_upload_total_limit', lang, limit=format_size_limit(total_limit)
            ),
        )


async def _take_the_lock() -> int:
    """Hold the instance-wide lock, waiting without parking a thread.

    A blocking ``flock`` in the thread pool would let waiting uploads fill it
    and leave the holder without a thread to write with.
    """
    root = settings.FILE_STORAGE_LOCAL_PATH
    os.makedirs(root, exist_ok=True)
    fd = os.open(os.path.join(root, _LOCK_NAME), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                await asyncio.sleep(_LOCK_POLL_SECONDS)
    except BaseException:  # the descriptor is closed on any exit, then re-raised
        os.close(fd)
        raise


@asynccontextmanager
async def demo_upload_admission(size: int) -> AsyncIterator[None]:
    """Admit a write of *size* bytes and keep the room until the write is done.

    Raises the 413 of :func:`enforce_demo_upload_cap` without writing anything.
    The lock is the open file's, so it goes with the process if one dies.
    """
    if not _is_capped():
        yield
        return
    fd = await _take_the_lock()
    try:
        await asyncio.to_thread(enforce_demo_upload_cap, size)
        yield
    finally:
        os.close(fd)
