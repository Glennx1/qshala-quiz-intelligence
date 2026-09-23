import io
import mimetypes
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, BinaryIO
import httpx
from backend.app.config import settings

logger = logging.getLogger(__name__)

class VercelBlobService:
    """
    Client for Vercel Blob Object Storage REST API (x-api-version: 7).
    Automatically falls back to local disk storage when BLOB_READ_WRITE_TOKEN is not configured.
    """
    API_BASE = "https://blob.vercel-storage.com"
    API_VERSION = "7"

    def __init__(self, token: Optional[str] = None, local_dir: Optional[Path] = None):
        self.token = token or settings.BLOB_READ_WRITE_TOKEN
        self.is_configured = bool(self.token)
        self.local_dir = local_dir or settings.BLOBS_DIR
        self.local_dir.mkdir(parents=True, exist_ok=True)

    async def put(
        self,
        pathname: str,
        data: Union[bytes, BinaryIO, io.BytesIO],
        content_type: Optional[str] = None,
        add_random_suffix: bool = False
    ) -> Dict[str, Any]:
        """
        Uploads an object to Vercel Blob or local disk storage fallback.
        """
        clean_pathname = pathname.lstrip("/").replace("\\", "/")
        if not content_type:
            content_type, _ = mimetypes.guess_type(clean_pathname)
            if not content_type:
                content_type = "application/octet-stream"

        # Read binary data into bytes
        if hasattr(data, "read"):
            body_bytes = data.read()
            if isinstance(body_bytes, str):
                body_bytes = body_bytes.encode("utf-8")
        elif isinstance(data, bytes):
            body_bytes = data
        else:
            body_bytes = bytes(data)

        if not self.is_configured:
            # Local filesystem fallback
            local_file_path = self.local_dir / clean_pathname
            local_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_file_path, "wb") as f:
                f.write(body_bytes)

            url = f"/static/blobs/{clean_pathname}"
            logger.info(f"[VercelBlobService] Stored locally: {clean_pathname} ({len(body_bytes)} bytes)")
            return {
                "url": url,
                "downloadUrl": url,
                "pathname": clean_pathname,
                "contentType": content_type,
                "contentDisposition": f'inline; filename="{Path(clean_pathname).name}"'
            }

        # Vercel Blob REST API PUT
        url = f"{self.API_BASE}/{clean_pathname}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "x-api-version": self.API_VERSION,
            "content-type": content_type,
            "x-content-type": content_type,
            "x-add-random-suffix": "1" if add_random_suffix else "0"
        }

        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.put(url, content=body_bytes, headers=headers)
            if resp.status_code >= 400:
                logger.error(f"[VercelBlobService] PUT failed ({resp.status_code}): {resp.text}")
                resp.raise_for_status()
            res_json = resp.json()
            return res_json

    async def delete(self, urls: List[str]) -> None:
        """
        Deletes one or more blobs by URL.
        """
        if not urls:
            return

        if not self.is_configured:
            # Local fallback deletion
            for url in urls:
                if "/static/blobs/" in url:
                    rel_path = url.split("/static/blobs/")[-1]
                    local_path = self.local_dir / rel_path
                    if local_path.exists():
                        try:
                            local_path.unlink()
                            logger.info(f"[VercelBlobService] Deleted local blob: {rel_path}")
                        except Exception as e:
                            logger.warning(f"[VercelBlobService] Failed to delete local blob {rel_path}: {e}")
            return

        url = f"{self.API_BASE}/delete"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "x-api-version": self.API_VERSION,
            "content-type": "application/json"
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.post(url, json={"urls": urls}, headers=headers)
            if resp.status_code >= 400:
                logger.error(f"[VercelBlobService] DELETE failed ({resp.status_code}): {resp.text}")
                resp.raise_for_status()

    async def download(self, url: str) -> bytes:
        """
        Downloads blob bytes from either a remote URL or local storage fallback.
        """
        if "/static/blobs/" in url:
            rel_path = url.split("/static/blobs/")[-1]
            local_path = self.local_dir / rel_path
            if local_path.exists():
                with open(local_path, "rb") as f:
                    return f.read()

        if url.startswith("http://") or url.startswith("https://"):
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content

        # Direct pathname lookup on local fallback
        local_path = self.local_dir / url.lstrip("/")
        if local_path.exists():
            with open(local_path, "rb") as f:
                return f.read()

        raise FileNotFoundError(f"Blob resource not found for URL or pathname: {url}")

    async def download_to_file(self, url: str, destination_path: Path) -> Path:
        """
        Downloads blob to a specific local file path.
        """
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        content = await self.download(url)
        with open(destination_path, "wb") as f:
            f.write(content)
        return destination_path


_global_blob_service: Optional[VercelBlobService] = None

def get_blob_service() -> VercelBlobService:
    global _global_blob_service
    if _global_blob_service is None:
        _global_blob_service = VercelBlobService()
    return _global_blob_service
