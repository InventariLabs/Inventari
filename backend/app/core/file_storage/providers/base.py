"""
Abstract base class for storage providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO


@dataclass
class FileInfo:
    """Metadata about a stored file."""

    path: str
    size: int
    created_at: datetime
    content_type: str
    etag: str | None = None


class StorageProvider(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    async def save(
        self,
        file_path: str,
        file_content: BytesIO,
        content_type: str = 'application/octet-stream',
    ) -> FileInfo:
        """
        Save a file to storage.

        Args:
            file_path: Path/key in storage (e.g., 'uploads/2026/02/photo.webp')
            file_content: File content as BytesIO
            content_type: MIME type

        Returns:
            FileInfo with metadata

        Raises:
            StorageError: If save fails
        """
        pass

    @abstractmethod
    async def get(self, file_path: str) -> BytesIO:
        """
        Retrieve file content.

        Args:
            file_path: Path/key in storage

        Returns:
            File content as BytesIO

        Raises:
            StoredFileNotFoundError: If file doesn't exist (a ``StorageError``
                and a built-in ``FileNotFoundError``)
            StorageError: If retrieval fails
        """
        pass

    @abstractmethod
    async def delete(self, file_path: str) -> None:
        """
        Delete a file.

        Args:
            file_path: Path/key in storage

        Raises:
            StoredFileNotFoundError: If file doesn't exist (a ``StorageError``
                and a built-in ``FileNotFoundError``)
            StorageError: If delete fails
        """
        pass

    @abstractmethod
    async def exists(self, file_path: str) -> bool:
        """Check if file exists."""
        pass

    @abstractmethod
    async def get_url(
        self,
        file_path: str,
        expires_in_seconds: int | None = None,
    ) -> str:
        """
        Get a URL to access the file.

        Args:
            file_path: Path/key in storage
            expires_in_seconds: For signed URLs, expiration time. None = public URL

        Returns:
            Full URL

        Raises:
            StoredFileNotFoundError: If file doesn't exist (a ``StorageError``
                and a built-in ``FileNotFoundError``)
        """
        pass
