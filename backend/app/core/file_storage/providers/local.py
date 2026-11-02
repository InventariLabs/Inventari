"""
Local filesystem storage provider.
"""

import asyncio
from datetime import datetime
from io import BytesIO
from pathlib import Path

from app.core.logging import get_logger

from .base import FileInfo, StorageProvider

logger = get_logger(__name__)


class LocalStorageProvider(StorageProvider):
    """Stores files on local VPS filesystem."""

    def __init__(self, base_path: str | Path):
        """
        Initialize local storage.

        Args:
            base_path: Root directory for files (e.g., '/app/uploads')
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_full_path(self, file_path: str) -> Path:
        """
        Resolve full path with security check (prevent path traversal).

        Args:
            file_path: Relative path (e.g., 'uploads/2026/02/photo.webp')

        Returns:
            Full Path object

        Raises:
            RuntimeError: If path tries to escape base_path (the upload route
            refuses such a path before it gets here, so no reader sees this)
        """
        base_resolved = self.base_path.resolve()
        full_path = (self.base_path / file_path).resolve()
        if not full_path.is_relative_to(base_resolved):
            raise RuntimeError(f'Path traversal attempted: {file_path}')
        return full_path

    async def save(
        self,
        file_path: str,
        file_content: BytesIO,
        content_type: str = 'application/octet-stream',
    ) -> FileInfo:
        """Save file to local filesystem."""
        full_path = self._get_full_path(file_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file asynchronously
        def _write() -> int:
            file_content.seek(0)
            with open(full_path, 'wb') as f:
                f.write(file_content.read())
            size = full_path.stat().st_size
            return size

        size = await asyncio.to_thread(_write)
        stat = full_path.stat()

        return FileInfo(
            path=file_path,
            size=size,
            created_at=datetime.fromtimestamp(stat.st_ctime),
            content_type=content_type,
            etag=None,
        )

    async def get(self, file_path: str) -> BytesIO:
        """Retrieve file from local filesystem."""
        full_path = self._get_full_path(file_path)

        if not full_path.exists():
            raise FileNotFoundError(f'File not found: {file_path}')

        def _read() -> BytesIO:
            with open(full_path, 'rb') as f:
                content = f.read()
            return BytesIO(content)

        return await asyncio.to_thread(_read)

    async def delete(self, file_path: str) -> None:
        """Delete file from local filesystem."""
        full_path = self._get_full_path(file_path)

        if not full_path.exists():
            raise FileNotFoundError(f'File not found: {file_path}')

        def _delete() -> None:
            full_path.unlink()

        await asyncio.to_thread(_delete)
        logger.info('Deleted file: %s', file_path)

    async def exists(self, file_path: str) -> bool:
        """Check if file exists."""
        try:
            full_path = self._get_full_path(file_path)
            return full_path.exists()
        except ValueError:
            return False

    async def get_url(
        self,
        file_path: str,
        expires_in_seconds: int | None = None,
    ) -> str:
        """
        Get URL to file. For local storage, returns a relative path URL.

        In production, use a reverse proxy (Nginx/Caddy) to serve /uploads/*
        """
        if not await self.exists(file_path):
            raise FileNotFoundError(f'File not found: {file_path}')

        # Return relative URL (assumes reverse proxy serves /uploads/)
        return f'/uploads/{file_path}'
