"""Pydantic schemas for file storage module."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FileInfoSchema(BaseModel):
    """File metadata response."""

    path: str = Field(..., description='File path/key in storage')
    size: int = Field(..., description='File size in bytes')
    created_at: datetime
    content_type: str = Field(..., description='MIME type')
    etag: str | None = Field(None, description='ETag for S3 files')
    url: str = Field(..., description='URL to access the file')

    model_config = ConfigDict(from_attributes=True)


class StorageConfigSchema(BaseModel):
    """Storage backend configuration."""

    backend: str = Field('local', description='Storage backend: local, s3')
    local_path: str | None = Field(
        None,
        description='Local path for local backend',
    )
    s3_bucket: str | None = Field(None, description='S3 bucket name')
    s3_access_key: str | None = Field(None, description='S3 access key')
    s3_secret_key: str | None = Field(None, description='S3 secret key')
    s3_region: str = Field('us-east-1', description='S3 region')
    s3_endpoint_url: str | None = Field(
        None,
        description='Custom S3 endpoint (for R2, OVH, etc.)',
    )

    model_config = ConfigDict(protected_namespaces=())
