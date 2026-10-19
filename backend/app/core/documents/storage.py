"""Where uploaded files live: one file per upload in DOCUMENT_STORAGE_DIR.

Each file gets a random name (storage_key). The name the user gave is only kept
in the database for display, so it can never point a path somewhere else
("../../etc/passwd").
"""

import hashlib
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.workflow.errors import InvalidDocument, UnsupportedFileType, UploadTooLarge

# The first bytes ("magic numbers") of the file types we accept. We trust these,
# not the Content-Type the browser sends, which anyone can set to anything.
_SIGNATURES = [
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
]
_HEAD = max(len(magic) for magic, _ in _SIGNATURES)
_KEY = re.compile(r"[0-9a-f]{32}")


@dataclass
class StoredFile:
    storage_key: str
    size_bytes: int
    sha256: str
    content_type: str


def _directory() -> Path:
    directory = Path(settings.document_storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def path_for(storage_key: str) -> Path:
    # Keys are always ours (uuid hex), but check anyway before touching the disk.
    if not _KEY.fullmatch(storage_key):
        raise ValueError("bad storage key")
    return _directory() / storage_key


async def save(chunks: AsyncIterator[bytes]) -> StoredFile:
    """Stream an upload to disk, counting, hashing and checking it on the way.

    Too big (413) or not a PDF/PNG/JPEG (415): the partial file is deleted.
    It's written as "<key>.part" and renamed only when complete, so a crash
    never leaves a half file under a real key.
    """
    key = uuid.uuid4().hex
    partial = _directory() / f"{key}.part"
    hasher, size, head = hashlib.sha256(), 0, b""
    limit = settings.max_upload_bytes
    try:
        # Plain (blocking) file writes: chunks are small and local disks fast.
        # Move to a thread or object storage if uploads ever slow the API down.
        with partial.open("wb") as out:
            async for chunk in chunks:
                size += len(chunk)
                if size > limit:
                    raise UploadTooLarge(f"Files can be at most {limit // (1024 * 1024)} MB.")
                if len(head) < _HEAD:
                    head += chunk[: _HEAD - len(head)]
                hasher.update(chunk)
                out.write(chunk)
        if size == 0:
            raise InvalidDocument("The file is empty.")
        content_type = next((t for magic, t in _SIGNATURES if head.startswith(magic)), None)
        if content_type is None:
            raise UnsupportedFileType("Only PDF, PNG and JPEG files are accepted.")
        partial.rename(path_for(key))
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return StoredFile(key, size, hasher.hexdigest(), content_type)


def delete(storage_key: str) -> None:
    path_for(storage_key).unlink(missing_ok=True)
