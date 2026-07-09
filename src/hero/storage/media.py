"""R2/S3 presigned URL helpers (INV-3: server never touches media bytes)."""

from __future__ import annotations

from typing import Any

import boto3  # type: ignore[import-untyped]

from hero.config import Settings


def get_s3_client(settings: Settings) -> Any:
    """Create an S3 client pointed at the R2 endpoint."""
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint or None,
        aws_access_key_id=settings.r2_access_key_id or None,
        aws_secret_access_key=settings.r2_secret_access_key or None,
        region_name=settings.r2_region,
    )


def presigned_upload_url(
    settings: Settings,
    object_key: str,
    content_type: str = "application/octet-stream",
    expires_in: int = 3600,
) -> str:
    """Generate a presigned PUT URL for direct client upload to R2 (INV-3)."""
    client = get_s3_client(settings)
    url: str = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.r2_bucket,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )
    return url
