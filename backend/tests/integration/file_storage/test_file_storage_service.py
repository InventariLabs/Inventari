"""Integration tests for file storage module."""

import io

import pytest

from app.core.file_storage.errors import StorageError
from app.core.file_storage.providers import (
    LocalStorageProvider,
)
from app.core.file_storage.service import FileStorageService


@pytest.mark.integration
class TestLocalStorageProvider:
    """Tests for LocalStorageProvider."""

    @pytest.fixture
    def temp_storage(self, tmp_path):
        """Create temporary storage directory."""
        return LocalStorageProvider(tmp_path)

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, temp_storage):
        """Test saving and retrieving a file."""
        content = b'Hello, World!'
        file_obj = io.BytesIO(content)

        # Save
        info = await temp_storage.save('test/file.txt', file_obj, 'text/plain')
        assert info.path == 'test/file.txt'
        assert info.size == len(content)
        assert info.content_type == 'text/plain'

        # Retrieve
        retrieved = await temp_storage.get('test/file.txt')
        assert retrieved.getvalue() == content

    @pytest.mark.asyncio
    async def test_file_not_found(self, temp_storage):
        """Test retrieving non-existent file."""
        with pytest.raises(FileNotFoundError):
            await temp_storage.get('nonexistent.txt')

    @pytest.mark.asyncio
    async def test_a_missing_file_is_a_storage_error_as_well(self, temp_storage):
        """Both handlers a caller may write catch a missing file.

        Every caller in the codebase catches the built-in
        ``FileNotFoundError``; the storage contract offers ``StorageError`` as
        the one handler for every storage failure. A missing file has to be
        both, or the generic handler lets the commonest failure through.
        """
        for call in (temp_storage.get, temp_storage.delete, temp_storage.get_url):
            with pytest.raises(FileNotFoundError) as caught:
                await call('nonexistent.txt')
            assert isinstance(caught.value, StorageError), call.__name__

    @pytest.mark.asyncio
    async def test_exists(self, temp_storage):
        """Test exists check."""
        file_obj = io.BytesIO(b'test')
        await temp_storage.save('test.txt', file_obj)

        assert await temp_storage.exists('test.txt') is True
        assert await temp_storage.exists('nonexistent.txt') is False

    @pytest.mark.asyncio
    async def test_delete(self, temp_storage):
        """Test file deletion."""
        file_obj = io.BytesIO(b'test')
        await temp_storage.save('test.txt', file_obj)

        assert await temp_storage.exists('test.txt') is True
        await temp_storage.delete('test.txt')
        assert await temp_storage.exists('test.txt') is False

    @pytest.mark.asyncio
    async def test_path_traversal_protection(self, temp_storage):
        """Test protection against path traversal attacks."""
        with pytest.raises(RuntimeError, match='Path traversal'):
            await temp_storage.save('../../../etc/passwd', io.BytesIO(b'x'))

    @pytest.mark.asyncio
    async def test_path_traversal_prefix_bypass(self, tmp_path):
        """
        Test that a directory sharing the base_path prefix is blocked.

        Regression: startswith('/app/uploads') would pass for '/app/uploads_evil'
        because it matches the string prefix. is_relative_to() does component-wise
        comparison and correctly rejects it.
        """
        provider = LocalStorageProvider(tmp_path)
        # Sibling directory that shares the exact string prefix with tmp_path
        sibling_name = tmp_path.name + '_evil'
        evil_relative = f'../{sibling_name}/pwned.txt'
        with pytest.raises(RuntimeError, match='Path traversal'):
            await provider.save(evil_relative, io.BytesIO(b'x'))
        with pytest.raises(RuntimeError, match='Path traversal'):
            await provider.get(evil_relative)
        with pytest.raises(RuntimeError, match='Path traversal'):
            await provider.delete(evil_relative)

    @pytest.mark.asyncio
    async def test_a_path_outside_the_base_does_not_exist_for_a_probe(self, tmp_path):
        """``exists`` and ``get_url`` answer a traversal as "not there".

        The write and read paths refuse a traversal loudly (a programmer's
        mistake); an existence probe has no file to refuse, so it says no,
        and ``get_url`` — which only hands out URLs of files that exist —
        reports the same missing file rather than leaking the guard's error.
        """
        provider = LocalStorageProvider(tmp_path / 'base')
        (tmp_path / 'outside.txt').write_bytes(b'secret')

        assert await provider.exists('../outside.txt') is False
        with pytest.raises(FileNotFoundError):
            await provider.get_url('../outside.txt')

    @pytest.mark.asyncio
    async def test_get_url(self, temp_storage):
        """Test URL generation."""
        file_obj = io.BytesIO(b'test')
        await temp_storage.save('uploads/photo.jpg', file_obj)

        url = await temp_storage.get_url('uploads/photo.jpg')
        assert '/uploads/photo.jpg' in url


@pytest.mark.integration
class TestFileStorageService:
    """Tests for FileStorageService singleton."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test, then restore the original state."""
        saved_instance = FileStorageService._instance
        saved_provider = FileStorageService._provider
        FileStorageService._instance = None
        FileStorageService._provider = None
        yield
        FileStorageService._instance = saved_instance
        FileStorageService._provider = saved_provider

    @pytest.mark.asyncio
    async def test_not_initialized_error(self):
        """Test error when service not initialized."""
        service = FileStorageService()
        with pytest.raises(Exception, match='not initialized'):
            await service.exists('test.txt')

    @pytest.mark.asyncio
    async def test_local_initialization(self, tmp_path):
        """Test initializing with local backend."""
        from app.core.file_storage.schemas import StorageConfigSchema

        config = StorageConfigSchema(
            backend='local',
            local_path=str(tmp_path),
        )
        FileStorageService.initialize(config)

        service = FileStorageService()
        file_obj = io.BytesIO(b'test content')
        info = await service.save('test.txt', file_obj, 'text/plain')

        assert info.path == 'test.txt'
        assert await service.exists('test.txt') is True

    @pytest.mark.asyncio
    async def test_singleton_pattern(self, tmp_path):
        """Test singleton pattern - same instance always."""
        from app.core.file_storage.schemas import StorageConfigSchema

        config = StorageConfigSchema(
            backend='local',
            local_path=str(tmp_path),
        )
        FileStorageService.initialize(config)

        service1 = FileStorageService()
        service2 = FileStorageService()

        assert service1 is service2
