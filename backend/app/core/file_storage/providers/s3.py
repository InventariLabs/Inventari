"""
S3-compatible storage provider (AWS S3, Cloudflare R2, OVH Object Storage).
"""

from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import aioboto3  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
)

from app.core.logging import get_logger

from ..errors import StorageError
from .base import FileInfo, StorageProvider

logger = get_logger(__name__)

#: The answers a store gives when it does not implement the versions listing —
#: Cloudflare R2's S3 API implements no versioning operation at all, so there
#: are no versions behind its keys for it to leave standing. Only these fall
#: back to the current-object listing; every other answer to that listing is
#: raised, because deleting the keys instead on a bucket that does keep
#: versions writes a marker over each one and leaves every old version
#: readable, which is the defect the versions listing exists to close.
_NO_VERSION_LISTING = frozenset(
    {
        'NotImplemented',
        'MethodNotAllowed',
        'MalformedXML',
        'InvalidArgument',
        '501',
        '405',
        '400',
    }
)


class S3StorageProvider(StorageProvider):
    """
    S3-compatible storage (AWS S3, Cloudflare R2, OVH Object Storage).

    All providers use the same S3 API, only configuration differs.
    """

    def __init__(
        self,
        bucket_name: str,
        access_key: str,
        secret_key: str,
        region: str = 'us-east-1',
        endpoint_url: str | None = None,
    ):
        """
        Initialize S3-compatible storage.

        Args:
            bucket_name: S3 bucket name
            access_key: AWS Access Key ID (or equivalent)
            secret_key: AWS Secret Key (or equivalent)
            region: AWS region (e.g., 'us-east-1' or 'eu-west-1')
            endpoint_url: Custom endpoint URL for R2/OVH. None = AWS S3

        Examples:
            # AWS S3
            S3StorageProvider('my-bucket', 'AKIAIOSFODNN7EXAMPLE', '...', region='eu-west-1')

            # Cloudflare R2
            S3StorageProvider(
                'my-bucket',
                'account-id.access-key',
                '...',
                endpoint_url='https://<account-id>.r2.cloudflarestorage.com'
            )

            # OVH Object Storage
            S3StorageProvider(
                'my-bucket',
                'region:my-bucket',  # region:bucket format
                '...',
                endpoint_url='https://s3.<region>.perf.cloud.ovh.net'
            )
        """
        self.bucket_name = bucket_name
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        # An unset variable arrives from compose as "", which botocore rejects.
        self.endpoint_url = endpoint_url or None

        # Session config
        self.session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    async def _get_s3_client(self) -> Any:
        """Create S3 client with custom endpoint if provided."""
        return self.session.client(
            's3',
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        )

    async def save(
        self,
        file_path: str,
        file_content: BytesIO,
        content_type: str = 'application/octet-stream',
    ) -> FileInfo:
        """Upload file to S3."""
        file_content.seek(0)
        size = len(file_content.getvalue())

        async with await self._get_s3_client() as client:
            try:
                response = await client.put_object(
                    Bucket=self.bucket_name,
                    Key=file_path,
                    Body=file_content,
                    ContentType=content_type,
                )
                etag = response.get('ETag', '').strip('"')
            except (BotoCoreError, ClientError) as e:
                logger.error('Failed to upload %s: %s', file_path, e)
                raise

        return FileInfo(
            path=file_path,
            size=size,
            created_at=datetime.now(UTC),
            content_type=content_type,
            etag=etag,
        )

    async def get(self, file_path: str) -> BytesIO:
        """Download file from S3."""
        async with await self._get_s3_client() as client:
            try:
                response = await client.get_object(
                    Bucket=self.bucket_name,
                    Key=file_path,
                )
                body = response['Body']
                content = await body.read()
                return BytesIO(content)
            except client.exceptions.NoSuchKey:
                raise FileNotFoundError(f'File not found: {file_path}') from None
            except (BotoCoreError, ClientError) as e:
                logger.error('Failed to get %s: %s', file_path, e)
                raise

    async def delete(self, file_path: str) -> None:
        """Delete file from S3."""
        async with await self._get_s3_client() as client:
            try:
                await client.delete_object(
                    Bucket=self.bucket_name,
                    Key=file_path,
                )
                logger.info('Deleted S3 object: %s', file_path)
            except (BotoCoreError, ClientError) as e:
                logger.error('Failed to delete %s: %s', file_path, e)
                raise

    async def empty(self) -> int:
        """Delete everything the bucket holds — every version of it; how many went.

        What the demo reset does to object storage: the rows that pointed at
        the objects went with the schema, so from here on they are objects
        nothing can reach, adding up every day. The listing that shows them
        all is the versions listing, because on a bucket with versioning on
        a key is not the file: a cover an earlier reset wrote and the delete
        marker over a visitor's upload are both still readable through their
        version id, and deleting the key they stand behind only lays another
        marker over it. Each entry goes with the VersionId the listing named
        — a bucket whose versioning was never turned on answers with ``null``
        ones, which are its objects.

        A store that does not implement that listing at all has no versions
        behind its keys, so its current-object listing empties it instead;
        that refusal is the one the emptier answers with the other door
        (``_first_page``), and every other failure of the listing is raised.

        One listing answers with one page (a thousand entries at most), so a
        page is deleted and the listing starts again from the top until it
        comes back empty — the deleted entries are gone from the next page,
        and a continuation token would keep pointing into a listing that has
        already moved.

        A deletion is reported per entry rather than per request: any entry
        the store refused raises here, because listing it again would be the
        only other answer and that loop never ends.
        """
        removed = 0
        async with await self._get_s3_client() as client:
            by_version, page = await self._first_page(client)
            while True:
                if by_version:
                    entries = [
                        {'Key': item['Key'], 'VersionId': item['VersionId']}
                        for item in (page.get('Versions') or [])
                        + (page.get('DeleteMarkers') or [])
                    ]
                else:
                    entries = [
                        {'Key': item['Key']} for item in (page.get('Contents') or [])
                    ]
                if not entries:
                    break
                response = await client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={'Objects': entries},
                )
                errors = response.get('Errors') or []
                if errors:
                    raise StorageError(
                        f'could not delete {len(errors)} of {len(entries)} entries '
                        f'from {self.bucket_name}: {errors[0].get("Message", "")}'
                    )
                removed += len(entries)
                if by_version:
                    page = await client.list_object_versions(Bucket=self.bucket_name)
                else:
                    page = await client.list_objects_v2(Bucket=self.bucket_name)
        logger.info('Emptied S3 bucket %s: %d entries', self.bucket_name, removed)
        return removed

    async def _first_page(self, client: Any) -> tuple[bool, Any]:
        """The listing this store has, and its first page: ``(versions?, page)``.

        Asked once, before the first page is used: the versions listing if the
        store answers it, and otherwise — for the store that says it does not
        have that operation, with nothing to lose because it keeps no versions
        — the current-object listing it does answer. Any other answer is raised
        to the caller: a refused permission or a broken store is a warning for
        the reset to print, never a reason to delete by key, which on a
        versioned bucket is how old versions survive a reset.
        """
        try:
            return True, await client.list_object_versions(Bucket=self.bucket_name)
        except ClientError as exc:
            code = str(exc.response.get('Error', {}).get('Code', ''))
            if code not in _NO_VERSION_LISTING:
                raise
            logger.warning(
                'S3 store does not list object versions (%s): emptying %s '
                'through its current-object listing.',
                code,
                self.bucket_name,
            )
            return False, await client.list_objects_v2(Bucket=self.bucket_name)

    async def exists(self, file_path: str) -> bool:
        """Check if file exists in S3."""
        try:
            async with await self._get_s3_client() as client:
                await client.head_object(
                    Bucket=self.bucket_name,
                    Key=file_path,
                )
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ('404', 'NoSuchKey'):
                return False
            logger.error('S3 exists() check failed for %s: %s', file_path, e)
            raise

    async def get_url(
        self,
        file_path: str,
        expires_in_seconds: int | None = None,
    ) -> str:
        """
        Generate URL to access file.

        Args:
            file_path: S3 key
            expires_in_seconds: Expiration for signed URL. None = public URL

        Returns:
            HTTP URL
        """
        if not await self.exists(file_path):
            raise FileNotFoundError(f'File not found: {file_path}')

        async with await self._get_s3_client() as client:
            if expires_in_seconds:
                # Signed URL (requires presign permissions)
                url: str = client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': self.bucket_name,
                        'Key': file_path,
                    },
                    ExpiresIn=expires_in_seconds,
                )
            else:
                # Public URL
                if self.endpoint_url:
                    # Custom endpoint (R2, OVH)
                    url = f'{self.endpoint_url}/{self.bucket_name}/{file_path}'
                else:
                    # AWS S3
                    url = f'https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{file_path}'

        return url
