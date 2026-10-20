import logging
import mimetypes
from pathlib import Path
from typing import Optional, List, Union, BinaryIO

from backend.app.config import settings

logger = logging.getLogger(__name__)


class CloudflareR2Service:
    """
    Client for Cloudflare R2 object storage (S3-compatible API).

    R2 is the preferred media store for QShala's extracted slide images, audio
    clips, and video clues: storage is ~$0.015/GB-month and, unlike Vercel Blob,
    R2 charges nothing to download (egress) -- which matters a lot here since
    quiz media gets replayed repeatedly in the Slide Viewer / Media Viewer.

    This service is purely additive: when R2 credentials aren't configured,
    `is_configured` is False and callers should keep using local disk exactly
    as before. Nothing breaks if R2 is never set up.
    """

    def __init__(self):
        self.account_id = settings.R2_ACCOUNT_ID
        self.access_key_id = settings.R2_ACCESS_KEY_ID
        self.secret_access_key = settings.R2_SECRET_ACCESS_KEY
        self.bucket_name = settings.R2_BUCKET_NAME
        self.public_base_url = (settings.R2_PUBLIC_BASE_URL or "").rstrip("/")

        self.is_configured = bool(
            self.account_id and self.access_key_id and self.secret_access_key
            and self.bucket_name and self.public_base_url
        )

        self._client = None
        if self.is_configured:
            try:
                import boto3
                from botocore.config import Config as BotoConfig

                self._client = boto3.client(
                    "s3",
                    endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
                    aws_access_key_id=self.access_key_id,
                    aws_secret_access_key=self.secret_access_key,
                    config=BotoConfig(signature_version="s3v4"),
                    region_name="auto",
                )
            except Exception as e:
                logger.warning(f"[CloudflareR2Service] Failed to initialize R2 client, falling back to local disk: {e}")
                self.is_configured = False
                self._client = None

    def upload_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> str:
        """
        Uploads bytes to R2 under `key` and returns the public HTTPS URL.
        Raises if R2 isn't configured or the upload fails -- callers should
        catch this and fall back to local disk.
        """
        if not self.is_configured or self._client is None:
            raise RuntimeError("CloudflareR2Service is not configured")

        clean_key = key.lstrip("/").replace("\\", "/")
        if not content_type:
            content_type, _ = mimetypes.guess_type(clean_key)
            content_type = content_type or "application/octet-stream"

        self._client.put_object(
            Bucket=self.bucket_name,
            Key=clean_key,
            Body=data,
            ContentType=content_type,
        )
        url = f"{self.public_base_url}/{clean_key}"
        logger.info(f"[CloudflareR2Service] Uploaded {clean_key} ({len(data)} bytes) -> {url}")
        return url

    def upload(
        self,
        pathname: str,
        data: Union[bytes, BinaryIO],
        content_type: Optional[str] = None
    ) -> str:
        """Convenience wrapper accepting a file-like object or raw bytes, mirroring
        the shape of VercelBlobService.put() so call sites can swap storage backends
        with minimal changes."""
        if hasattr(data, "read"):
            body_bytes = data.read()
            if isinstance(body_bytes, str):
                body_bytes = body_bytes.encode("utf-8")
        else:
            body_bytes = bytes(data)
        return self.upload_bytes(pathname, body_bytes, content_type=content_type)

    def delete(self, keys: List[str]) -> None:
        if not self.is_configured or self._client is None or not keys:
            return
        for key in keys:
            clean_key = key
            if self.public_base_url and key.startswith(self.public_base_url):
                clean_key = key[len(self.public_base_url):].lstrip("/")
            try:
                self._client.delete_object(Bucket=self.bucket_name, Key=clean_key)
            except Exception as e:
                logger.warning(f"[CloudflareR2Service] Failed to delete {clean_key}: {e}")

    def download(self, key_or_url: str) -> bytes:
        if not self.is_configured or self._client is None:
            raise RuntimeError("CloudflareR2Service is not configured")
        clean_key = key_or_url
        if self.public_base_url and key_or_url.startswith(self.public_base_url):
            clean_key = key_or_url[len(self.public_base_url):].lstrip("/")
        resp = self._client.get_object(Bucket=self.bucket_name, Key=clean_key)
        return resp["Body"].read()


_global_r2_service: Optional[CloudflareR2Service] = None


def get_r2_service() -> CloudflareR2Service:
    global _global_r2_service
    if _global_r2_service is None:
        _global_r2_service = CloudflareR2Service()
    return _global_r2_service


def get_media_storage() -> Optional[CloudflareR2Service]:
    """
    Returns the configured R2 service, or None when R2 isn't set up (meaning
    callers should fall back to local disk / existing behavior unchanged).
    """
    svc = get_r2_service()
    return svc if svc.is_configured else None
