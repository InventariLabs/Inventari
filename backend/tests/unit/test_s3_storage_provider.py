"""Unit tests for the S3-compatible storage provider.

The provider talks to S3 only through ``aioboto3.Session`` and the per-call
client it creates in ``_get_s3_client``.  Both are mocked here so nothing
leaves the process — no credentials, no network and no DB session.
"""

from __future__ import annotations

from collections.abc import Generator
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
)

from app.core.file_storage.providers.s3 import S3StorageProvider


class _NoSuchKeyError(Exception):
    """Stand-in for ``client.exceptions.NoSuchKey``."""


def _async_cm(client: MagicMock) -> MagicMock:
    """Return an object usable as ``async with await ... as client``."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.fixture
def provider() -> Generator[S3StorageProvider]:
    with patch(
        'app.core.file_storage.providers.s3.aioboto3.Session'
    ) as mock_session_cls:
        mock_session_cls.return_value = MagicMock()
        yield S3StorageProvider(
            bucket_name='inventari-bucket',
            access_key='ACCESS',
            secret_key='SECRET',
            region='eu-west-1',
            endpoint_url='https://r2.example.com',
        )


@pytest.mark.unit
class TestInit:
    def test_init_sets_configuration(self, provider: S3StorageProvider) -> None:
        assert provider.bucket_name == 'inventari-bucket'
        assert provider.access_key == 'ACCESS'
        assert provider.secret_key == 'SECRET'
        assert provider.region == 'eu-west-1'
        assert provider.endpoint_url == 'https://r2.example.com'

    def test_an_empty_endpoint_means_the_default_endpoint(self) -> None:
        # Compose hands an unset `FILE_STORAGE_S3_ENDPOINT_URL` over as an empty
        # string, and botocore refuses "" as an endpoint rather than ignoring it.
        with patch('app.core.file_storage.providers.s3.aioboto3.Session'):
            plain = S3StorageProvider(
                bucket_name='b', access_key='a', secret_key='s', endpoint_url=''
            )

        assert plain.endpoint_url is None

    async def test_get_s3_client_forwards_region_and_endpoint(
        self, provider: S3StorageProvider
    ) -> None:
        client = MagicMock()
        provider.session.client = MagicMock(return_value=client)  # type: ignore[attr-defined]
        result = await provider._get_s3_client()
        assert result is client
        provider.session.client.assert_called_once_with(  # type: ignore[attr-defined]
            's3',
            region_name='eu-west-1',
            endpoint_url='https://r2.example.com',
        )


@pytest.mark.unit
class TestSave:
    async def test_save_returns_file_info(self, provider: S3StorageProvider) -> None:
        client = MagicMock()
        client.put_object = AsyncMock(return_value={'ETag': '"abc123"'})
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            info = await provider.save(
                'uploads/x.txt', BytesIO(b'hello world'), content_type='text/plain'
            )
        assert info.path == 'uploads/x.txt'
        assert info.size == 11
        assert info.etag == 'abc123'
        assert info.content_type == 'text/plain'
        client.put_object.assert_awaited_once()

    async def test_save_propagates_client_error(
        self, provider: S3StorageProvider
    ) -> None:
        client = MagicMock()
        client.put_object = AsyncMock(
            side_effect=ClientError({'Error': {'Code': '500'}}, 'PutObject')
        )
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            with pytest.raises(ClientError):
                await provider.save('uploads/x', BytesIO(b'x'))


@pytest.mark.unit
class TestGet:
    async def test_get_returns_bytes(self, provider: S3StorageProvider) -> None:
        client = MagicMock()
        body = MagicMock()
        body.read = AsyncMock(return_value=b'file-bytes')
        client.get_object = AsyncMock(return_value={'Body': body})
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            result = await provider.get('uploads/x')
        assert result.read() == b'file-bytes'

    async def test_get_missing_raises_file_not_found(
        self, provider: S3StorageProvider
    ) -> None:
        client = MagicMock()
        client.exceptions.NoSuchKey = _NoSuchKeyError
        client.get_object = AsyncMock(side_effect=_NoSuchKeyError())
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            with pytest.raises(FileNotFoundError):
                await provider.get('uploads/x')

    async def test_get_propagates_client_error(
        self, provider: S3StorageProvider
    ) -> None:
        client = MagicMock()
        client.exceptions.NoSuchKey = _NoSuchKeyError
        client.get_object = AsyncMock(
            side_effect=ClientError({'Error': {'Code': '403'}}, 'GetObject')
        )
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            with pytest.raises(ClientError):
                await provider.get('uploads/x')


@pytest.mark.unit
class TestDelete:
    async def test_delete_calls_delete_object(
        self, provider: S3StorageProvider
    ) -> None:
        client = MagicMock()
        client.delete_object = AsyncMock()
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            await provider.delete('uploads/x')
        client.delete_object.assert_awaited_once()

    async def test_delete_propagates_client_error(
        self, provider: S3StorageProvider
    ) -> None:
        client = MagicMock()
        client.delete_object = AsyncMock(side_effect=BotoCoreError())
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            with pytest.raises(BotoCoreError):
                await provider.delete('uploads/x')


@pytest.mark.unit
class TestExists:
    async def test_exists_true(self, provider: S3StorageProvider) -> None:
        client = MagicMock()
        client.head_object = AsyncMock()
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            assert await provider.exists('uploads/x') is True

    @pytest.mark.parametrize('code', ['404', 'NoSuchKey'])
    async def test_exists_missing_codes_return_false(
        self, provider: S3StorageProvider, code: str
    ) -> None:
        client = MagicMock()
        client.head_object = AsyncMock(
            side_effect=ClientError({'Error': {'Code': code}}, 'HeadObject')
        )
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            assert await provider.exists('uploads/x') is False

    async def test_exists_other_client_error_raises(
        self, provider: S3StorageProvider
    ) -> None:
        client = MagicMock()
        client.head_object = AsyncMock(
            side_effect=ClientError({'Error': {'Code': '403'}}, 'HeadObject')
        )
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            with pytest.raises(ClientError):
                await provider.exists('uploads/x')


@pytest.mark.unit
class TestGetUrl:
    async def test_get_url_missing_raises(self, provider: S3StorageProvider) -> None:
        client = MagicMock()
        client.head_object = AsyncMock(
            side_effect=ClientError({'Error': {'Code': 'NoSuchKey'}}, 'HeadObject')
        )
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            with pytest.raises(FileNotFoundError):
                await provider.get_url('uploads/x')

    async def test_get_url_signed(self, provider: S3StorageProvider) -> None:
        client = MagicMock()
        client.head_object = AsyncMock()
        client.generate_presigned_url = MagicMock(
            return_value='https://signed.example/x'
        )
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            url = await provider.get_url('uploads/x', expires_in_seconds=3600)
        assert url == 'https://signed.example/x'
        client.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'inventari-bucket', 'Key': 'uploads/x'},
            ExpiresIn=3600,
        )

    async def test_get_url_public_custom_endpoint(
        self, provider: S3StorageProvider
    ) -> None:
        client = MagicMock()
        client.head_object = AsyncMock()
        with patch.object(
            provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            url = await provider.get_url('uploads/x')
        assert url == 'https://r2.example.com/inventari-bucket/uploads/x'

    async def test_get_url_public_aws_without_endpoint(self) -> None:
        with patch(
            'app.core.file_storage.providers.s3.aioboto3.Session'
        ) as mock_session_cls:
            mock_session_cls.return_value = MagicMock()
            aws_provider = S3StorageProvider(
                bucket_name='bucket',
                access_key='ACCESS',
                secret_key='SECRET',
                region='us-east-1',
                endpoint_url=None,
            )
        client = MagicMock()
        client.head_object = AsyncMock()
        with patch.object(
            aws_provider, '_get_s3_client', AsyncMock(return_value=_async_cm(client))
        ):
            url = await aws_provider.get_url('uploads/x')
        assert url == 'https://bucket.s3.us-east-1.amazonaws.com/uploads/x'
