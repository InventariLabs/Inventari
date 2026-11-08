"""Exceptions for file storage module."""


class StorageError(Exception):
    """Base exception for storage operations."""

    pass


class FileStorageConfigError(StorageError):
    """Configuration error."""

    pass


class StoredFileNotFoundError(StorageError, FileNotFoundError):
    """The file a path names is not in storage.

    Both kinds at once, on purpose. Every caller in the codebase catches the
    built-in ``FileNotFoundError``, and the contract offers ``StorageError``
    as the one handler for every storage failure: a missing file that was only
    the first slipped past the second. The class used to sit here under the
    built-in's own name, raised by no provider, so neither half held.
    """
