"""File storage service - main facade."""

from io import BytesIO

from app.core.db_retry import mark_external_effect
from app.core.file_storage.providers import (
    LocalStorageProvider,
    S3StorageProvider,
    StorageProvider,
)
from app.core.file_storage.providers.base import FileInfo
from app.core.file_storage.schemas import StorageConfigSchema
from app.core.logging import get_logger

from .errors import FileStorageConfigError

logger = get_logger(__name__)


class FileStorageService:
    """
    Singleton service for file storage operations.

    Abstracts away the storage backend configuration.
    """

    _instance = None
    _provider: StorageProvider | None = None

    def __new__(cls) -> 'FileStorageService':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def initialize(cls, config: StorageConfigSchema) -> 'FileStorageService':
        """
        Initialize the file storage service with backend config.

        Should be called once during app startup (in module.py).

        Args:
            config: StorageConfigSchema with backend settings

        Returns:
            Singleton instance
        """
        instance = cls()

        if config.backend == 'local':
            if not config.local_path:
                raise FileStorageConfigError('local_path required for local backend')
            instance._provider = LocalStorageProvider(config.local_path)
            logger.info('Initialized local storage: %s', config.local_path)

        elif config.backend == 's3':
            if not all([config.s3_bucket, config.s3_access_key, config.s3_secret_key]):
                raise FileStorageConfigError(
                    'S3 credentials required: bucket, access_key, secret_key'
                )
            instance._provider = S3StorageProvider(
                bucket_name=config.s3_bucket or '',
                access_key=config.s3_access_key or '',
                secret_key=config.s3_secret_key or '',
                region=config.s3_region,
                endpoint_url=config.s3_endpoint_url,
            )
            logger.info('Initialized S3 storage: %s', config.s3_bucket)

        else:
            raise FileStorageConfigError(f'Unknown backend: {config.backend}')

        return instance

    @classmethod
    def initialize_from_settings(cls) -> 'FileStorageService':
        """Initialize from the application settings, as the API does at start-up.

        A CLI command never starts the API, so one that stores a file — the
        demo reset putting photographs on its recipes — opens the storage
        here, from the same configuration rather than a copy of it.
        """
        from app.config import settings

        return cls.initialize(
            StorageConfigSchema(
                backend=settings.FILE_STORAGE_BACKEND,
                local_path=settings.FILE_STORAGE_LOCAL_PATH,
                s3_bucket=settings.FILE_STORAGE_S3_BUCKET,
                s3_access_key=settings.FILE_STORAGE_S3_ACCESS_KEY,
                s3_secret_key=settings.FILE_STORAGE_S3_SECRET_KEY,
                s3_region=settings.FILE_STORAGE_S3_REGION,
                s3_endpoint_url=settings.FILE_STORAGE_S3_ENDPOINT_URL,
            )
        )

    def _ensure_initialized(self) -> StorageProvider:
        """Check that service is initialized and return the provider."""
        if self._provider is None:
            raise FileStorageConfigError(
                'FileStorageService not initialized. Call initialize() first.'
            )
        return self._provider

    async def save(
        self,
        file_path: str,
        file_content: BytesIO,
        content_type: str = 'application/octet-stream',
    ) -> FileInfo:
        # A write to the storage backend survives the request's rollback, so
        # the request must not be retried once this has run (db_retry).
        mark_external_effect(f'file-storage:save:{file_path}')
        provider = self._ensure_initialized()
        return await provider.save(file_path, file_content, content_type)

    async def get(self, file_path: str) -> BytesIO:
        """Retrieve file from configured storage backend."""
        provider = self._ensure_initialized()
        return await provider.get(file_path)

    async def delete(self, file_path: str) -> None:
        """Delete file from configured storage backend."""
        # Deletes are as external as writes: the backend has no transaction
        # to roll back into (db_retry).
        mark_external_effect(f'file-storage:delete:{file_path}')
        provider = self._ensure_initialized()
        return await provider.delete(file_path)

    async def empty(self) -> int:
        """Delete every object object storage holds; how many went.

        The demo reset's step for a backend with no directory on this disk:
        the rows that pointed at the objects went with the schema, so from
        here on they are objects nothing can reach, adding up every day. The
        local backend does not answer here on purpose — its files are emptied
        by the guarded directory walk beside the command (which keeps the
        mount point and refuses a path that is not an uploads directory), and
        two doors to the same deletion would be two answers to where the
        refusal lives.
        """
        provider = self._ensure_initialized()
        if isinstance(provider, S3StorageProvider):
            # Emptying is the same outside effect the two calls above mark:
            # the objects are gone whether or not the transaction around a
            # request survives (db_retry).
            mark_external_effect('file-storage:empty')
            return await provider.empty()
        raise FileStorageConfigError(
            f'cannot empty {type(provider).__name__} through the service: the '
            f'local backend empties through the uploads directory walk.'
        )

    async def exists(self, file_path: str) -> bool:
        """Check if file exists in configured storage backend."""
        provider = self._ensure_initialized()
        return await provider.exists(file_path)

    async def get_url(
        self,
        file_path: str,
        expires_in_seconds: int | None = None,
    ) -> str:
        """Get URL for file."""
        provider = self._ensure_initialized()
        return await provider.get_url(file_path, expires_in_seconds)
