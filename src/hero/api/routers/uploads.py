"""Upload endpoint — presigned R2 upload URL per INV-3.

Server never touches media bytes. Client uploads directly to R2 via presigned URL.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from hero.config import get_settings
from hero.storage.media import presigned_upload_url

router = APIRouter()


class PresignedUploadRequest(BaseModel):
    ticket_id: str
    filename: str
    content_type: str = "application/octet-stream"


class PresignedUploadResponse(BaseModel):
    upload_url: str
    object_key: str


@router.post("/presign", response_model=PresignedUploadResponse)
async def get_presigned_upload(request: PresignedUploadRequest) -> PresignedUploadResponse:
    """Generate a presigned PUT URL for direct client upload to R2 (INV-3)."""
    settings = get_settings()
    object_key = f"tickets/{request.ticket_id}/{uuid.uuid4()}/{request.filename}"

    url = presigned_upload_url(
        settings,
        object_key=object_key,
        content_type=request.content_type,
    )

    return PresignedUploadResponse(upload_url=url, object_key=object_key)
