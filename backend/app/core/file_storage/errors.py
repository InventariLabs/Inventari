"""Exceptions for file storage module."""


class StorageError(Exception):
    """Base exception for storage operations."""

    pass


class FileStorageConfigError(StorageError):
    """Configuration error."""

    pass


class FileNotFoundError(StorageError):
    """File doesn't exist."""

    pass
