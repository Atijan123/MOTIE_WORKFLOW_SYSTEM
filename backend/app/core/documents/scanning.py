"""Scanning a paper document with a phone's camera (step 13g).

Records photographs a document page by page from the case page. Each photo:
  - is checked: it must really be a JPEG, PNG or HEIC (iPhones) image, not
    too big as it arrives, and not a "decompression bomb" (a small file that
    unpacks into a huge image);
  - is turned upright from the photo's own orientation tag (phones store
    "rotate me" instead of rotating the pixels);
  - is shrunk so its long side is SCAN_LONG_SIDE pixels (about 200 dpi on
    A4: sharp enough to read, a fraction of the size) and saved as a JPEG,
    without the photo's metadata (location, phone model);
and is kept on the server as one pending page (core.scan_pages). "Finish"
joins the pages into one PDF and stores it through documents.service.upload(),
exactly as if it had been uploaded: the same permission check, size limit,
file-type check and audit row. Then the pages are deleted.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pillow_heif
from fpdf import FPDF
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.documents import service, storage
from app.core.documents.models import CaseDocument, ScanPage
from app.core.identity.models import User
from app.core.workflow import service as workflow
from app.core.workflow.errors import InvalidDocument, UnsupportedFileType, UploadTooLarge

pillow_heif.register_heif_opener()  # lets Pillow open HEIC/HEIF photos

# Bigger than any phone photo (a 200-megapixel camera is 200M). Anything over
# this is refused before its pixels are decoded.
MAX_PIXELS = 220_000_000
# Pages are pending for this long; older ones are cleared.
PENDING_FOR = timedelta(hours=24)

# What a page may be, by its first bytes (never by the name or the browser's word).
_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1")


def photo_kind(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    # HEIF: a box called "ftyp" at byte 4, then the brand.
    if head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return "heic"
    return None


def process_page(content: bytes) -> bytes:
    """One photo -> one upright, shrunk, compressed JPEG with no metadata."""
    if photo_kind(content[:16]) is None:
        raise UnsupportedFileType("A page must be a photo: JPEG, PNG or HEIC.")
    try:
        # Pillow itself refuses images of absurd size (DecompressionBombError).
        with Image.open(BytesIO(content)) as image:
            # Opening reads only the header; check the size before decoding pixels.
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise UploadTooLarge("That photo is far too large to be a page.")
            upright = ImageOps.exif_transpose(image)
            page = upright.convert("RGB")
    except Image.DecompressionBombError as exc:
        raise UploadTooLarge("That photo is far too large to be a page.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise UnsupportedFileType("That photo couldn't be read. Take it again.") from exc
    page.thumbnail((settings.scan_long_side, settings.scan_long_side))  # never enlarges
    out = BytesIO()
    # No exif= argument: the location and camera details are left behind.
    page.save(out, "JPEG", quality=settings.scan_jpeg_quality, optimize=True)
    return out.getvalue()


def join_pages(pages: list[bytes]) -> bytes:
    """JPEG pages -> one PDF, one page each, on A4 turned to suit the photo.
    fpdf2 embeds the JPEGs as they are (no second compression)."""
    pdf = FPDF(unit="mm")
    pdf.set_auto_page_break(False)
    pdf.set_creator("MOTIE ETLS phone scan")
    for content in pages:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
        landscape = width > height
        page_w, page_h = (297, 210) if landscape else (210, 297)
        pdf.add_page(orientation="L" if landscape else "P", format="A4")
        margin = 8
        scale = min((page_w - 2 * margin) / width, (page_h - 2 * margin) / height)
        w, h = width * scale, height * scale
        pdf.image(BytesIO(content), x=(page_w - w) / 2, y=(page_h - h) / 2, w=w, h=h)
    return bytes(pdf.output())


async def _read_capped(chunks: AsyncIterator[bytes]) -> bytes:
    """The photo, refused (413) as soon as it passes SCAN_MAX_PHOTO_BYTES."""
    parts, size = [], 0
    async for chunk in chunks:
        size += len(chunk)
        if size > settings.scan_max_photo_bytes:
            raise UploadTooLarge(f"A photo can be at most {settings.scan_max_photo_bytes // (1024 * 1024)} MB.")
        parts.append(chunk)
    return b"".join(parts)


async def _check_may_add(session: AsyncSession, case_id: int, type_code: str, actor: User) -> None:
    """The same rules as uploading: a case they can see, still open, that takes this document."""
    case = await workflow.get_case(session, case_id, actor)
    if case.current_status.is_final:
        raise InvalidDocument("This case is closed; no more documents can be added.")
    if not any(s.requirement.document_type.code == type_code for s in await service.checklist(session, case)):
        raise InvalidDocument(f"This kind of case doesn't take a '{type_code}' document.")


def _mine(case_id: int, type_code: str, actor: User):
    return (ScanPage.case_id == case_id, ScanPage.document_type == type_code, ScanPage.user_id == actor.id)


async def pages(session: AsyncSession, case_id: int, type_code: str, actor: User) -> list[ScanPage]:
    await workflow.get_case(session, case_id, actor)  # 404 unless they can see the case
    return list(
        await session.scalars(select(ScanPage).where(*_mine(case_id, type_code, actor)).order_by(ScanPage.page_no))
    )


async def _clear_old(session: AsyncSession, actor: User) -> None:
    """This person's pages left unfinished for over a day, anywhere."""
    old = (
        await session.scalars(
            select(ScanPage).where(ScanPage.user_id == actor.id, ScanPage.created_at < datetime.now(timezone.utc) - PENDING_FOR)
        )
    ).all()
    for page in old:
        storage.delete(page.storage_key)
        await session.delete(page)


async def add_page(
    session: AsyncSession, *, case_id: int, type_code: str, chunks: AsyncIterator[bytes], actor: User,
    replace: int | None = None,
) -> list[ScanPage]:
    """Add a photo as the next page, or as page `replace` (a retake). Returns the pages."""
    await _check_may_add(session, case_id, type_code, actor)
    await _clear_old(session, actor)
    current = await pages(session, case_id, type_code, actor)
    if replace is None and len(current) >= settings.scan_max_pages:
        raise UploadTooLarge(f"A document can have at most {settings.scan_max_pages} pages.")
    if replace is not None and replace not in {p.page_no for p in current}:
        raise InvalidDocument(f"There is no page {replace} to take again.")

    stored = await storage.save_bytes(process_page(await _read_capped(chunks)))
    try:
        if replace is None:
            session.add(ScanPage(
                case_id=case_id, document_type=type_code, user_id=actor.id,
                page_no=len(current) + 1, storage_key=stored.storage_key, size_bytes=stored.size_bytes,
            ))
        else:
            page = next(p for p in current if p.page_no == replace)
            old_key = page.storage_key
            page.storage_key, page.size_bytes = stored.storage_key, stored.size_bytes
            page.created_at = datetime.now(timezone.utc)
        await session.commit()
    except BaseException:
        storage.delete(stored.storage_key)
        raise
    if replace is not None:
        storage.delete(old_key)
    return await pages(session, case_id, type_code, actor)


async def page_image(session: AsyncSession, case_id: int, type_code: str, page_no: int, actor: User) -> bytes:
    """The page as it will be in the PDF (upright, shrunk), for the preview."""
    for page in await pages(session, case_id, type_code, actor):
        if page.page_no == page_no:
            return storage.path_for(page.storage_key).read_bytes()
    raise workflow.NotFound("No such page.")


async def remove_page(session: AsyncSession, case_id: int, type_code: str, page_no: int, actor: User) -> list[ScanPage]:
    """Remove one page; the ones after it move up, so the numbers stay 1, 2, 3…"""
    current = await pages(session, case_id, type_code, actor)
    page = next((p for p in current if p.page_no == page_no), None)
    if page is None:
        raise workflow.NotFound("No such page.")
    await session.delete(page)
    await session.flush()
    # Renumber one at a time, in order, so no two pages share a number on the way.
    for later in sorted((p for p in current if p.page_no > page_no), key=lambda p: p.page_no):
        later.page_no -= 1
        await session.flush()
    await session.commit()
    storage.delete(page.storage_key)
    return await pages(session, case_id, type_code, actor)


async def cancel(session: AsyncSession, case_id: int, type_code: str, actor: User) -> None:
    current = await pages(session, case_id, type_code, actor)
    await session.execute(delete(ScanPage).where(*_mine(case_id, type_code, actor)))
    await session.commit()
    for page in current:
        storage.delete(page.storage_key)


async def finish(session: AsyncSession, *, case_id: int, type_code: str, actor: User) -> CaseDocument:
    """Join the pages into one PDF and store it as an upload of this document."""
    current = await pages(session, case_id, type_code, actor)
    if not current:
        raise InvalidDocument("Take a photo of at least one page first.")
    pdf = join_pages([storage.path_for(p.storage_key).read_bytes() for p in current])

    async def one_chunk():
        yield pdf

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    document = await service.upload(
        session, case_id=case_id, type_code=type_code, filename=f"{type_code}-scan-{stamp}.pdf",
        chunks=one_chunk(), actor=actor,
    )
    await cancel(session, case_id, type_code, actor)  # the pages are in the PDF now
    return document
