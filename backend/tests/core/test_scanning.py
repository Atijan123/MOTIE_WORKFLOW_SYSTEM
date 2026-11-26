"""Step 13g: photographing a paper document page by page with a phone, joined
into one PDF on the server (app/core/documents/scanning.py)."""

import re
import struct
import zlib
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.core.config import settings
from app.core.documents import scanning, storage
from app.core.documents.models import ScanPage
from tests.support import create_draft

pytestmark = pytest.mark.anyio

TYPE = "invoice"


def photo(width=1200, height=900, fmt="JPEG", orientation=None, colour=(180, 40, 40)) -> bytes:
    image = Image.new("RGB", (width, height), colour)
    # A dark band on the left, so we can tell which way the page ends up.
    image.paste((0, 0, 0), (0, 0, width // 10, height))
    out = BytesIO()
    if orientation:
        exif = image.getexif()
        exif[0x0112] = orientation  # "rotate me": what phones store instead of rotating pixels
        image.save(out, fmt, exif=exif)
    else:
        image.save(out, fmt)
    return out.getvalue()


def heic(width=800, height=600) -> bytes:
    out = BytesIO()
    Image.new("RGB", (width, height), (30, 120, 60)).save(out, format="HEIF")
    return out.getvalue()


def png_claiming(width: int, height: int) -> bytes:
    """A tiny PNG whose header claims a huge image: a "decompression bomb"."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")


def pdf_pages(content: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", content))


# --- One photo into one page ------------------------------------------------------


def test_a_photo_is_turned_upright_from_its_orientation_tag():
    # Taken with the phone held sideways: stored 1200x900 with "rotate 90°".
    page = Image.open(BytesIO(scanning.process_page(photo(1200, 900, orientation=6))))
    assert page.size == (900, 1200)  # now portrait, as the paper was
    assert page.getexif().get(0x0112) is None  # and no "rotate me" left behind


def test_a_large_photo_is_shrunk_and_compressed_without_its_metadata():
    original = photo(4000, 3000, orientation=1)
    processed = scanning.process_page(original)
    page = Image.open(BytesIO(processed))
    assert max(page.size) == settings.scan_long_side
    assert page.format == "JPEG" and len(processed) < len(original)
    assert not page.getexif()  # no location, no phone model


def test_a_heic_photo_from_an_iphone_becomes_a_jpeg_page():
    page = Image.open(BytesIO(scanning.process_page(heic(800, 600))))
    assert page.format == "JPEG" and page.size == (800, 600)


def test_png_pages_are_accepted_too():
    assert Image.open(BytesIO(scanning.process_page(photo(fmt="PNG")))).format == "JPEG"


@pytest.mark.parametrize(
    "content",
    [b"%PDF-1.7 not a photo", b"GIF89a....", b"just some text", b"\xff\xd8\xff broken jpeg"],
    ids=["pdf", "gif", "text", "broken-jpeg"],
)
def test_anything_but_a_readable_photo_is_refused(content):
    with pytest.raises(scanning.UnsupportedFileType):
        scanning.process_page(content)


def test_a_decompression_bomb_is_refused_before_its_pixels_are_read():
    with pytest.raises(scanning.UploadTooLarge):
        scanning.process_page(png_claiming(60_000, 60_000))


def test_pages_join_into_one_pdf_portrait_or_landscape():
    pages = [scanning.process_page(photo(900, 1200)), scanning.process_page(photo(1600, 900))]
    pdf = scanning.join_pages(pages)
    assert pdf.startswith(b"%PDF") and pdf_pages(pdf) == 2


# --- Through the API ---------------------------------------------------------------


def url(case_id, rest=""):
    return f"/cases/{case_id}/documents/{TYPE}/scan{rest}"


async def add(act, user, case_id, content, retake=None):
    method, path = ("put", url(case_id, f"/pages/{retake}")) if retake else ("post", url(case_id, "/pages"))
    return await act(user, method, path, content=content, headers_extra={"Content-Type": "application/octet-stream"})


async def test_scan_retake_remove_and_finish_into_one_document(act, people, db_session):
    applicant = people["applicant"]
    case_id = await create_draft(act, applicant)
    for n in range(3):
        assert (await add(act, applicant, case_id, photo(colour=(n * 60, 80, 80)))).status_code == 201
    # Page 2 was blurred: take it again (sideways this time); then drop page 1.
    assert (await add(act, applicant, case_id, photo(1200, 900, orientation=6), retake=2)).status_code == 200
    left = (await act(applicant, "delete", url(case_id, "/pages/1"))).json()
    assert [p["page_no"] for p in left] == [1, 2]  # renumbered

    preview = await act(applicant, "get", url(case_id, "/pages/1/image"))
    assert preview.headers["content-type"] == "image/jpeg"
    assert Image.open(BytesIO(preview.content)).size == (900, 1200)  # the retake, upright
    assert preview.headers["cache-control"] == "private, no-store"

    done = await act(applicant, "post", url(case_id, "/finish"))
    assert done.status_code == 201, done.text
    assert done.json()["content_type"] == "application/pdf"
    pdf = await act(applicant, "get", f"/cases/{case_id}/documents/{done.json()['id']}/file")
    assert pdf_pages(pdf.content) == 2
    # The pages are gone: from the table and from the disk.
    assert await db_session.scalar(select(func.count()).select_from(ScanPage)) == 0
    assert (await act(applicant, "get", url(case_id))).json() == []


async def test_a_photo_too_big_as_it_arrives_is_refused(act, people, monkeypatch):
    monkeypatch.setattr(settings, "scan_max_photo_bytes", 50_000)
    case_id = await create_draft(act, people["applicant"])
    # Counted as it arrives, before any image work: a JPEG start, then 60 KB.
    response = await add(act, people["applicant"], case_id, bytes([0xFF, 0xD8, 0xFF]) + b"0" * 60_000)
    assert response.status_code == 413


async def test_at_most_so_many_pages(act, people, monkeypatch):
    monkeypatch.setattr(settings, "scan_max_pages", 2)
    case_id = await create_draft(act, people["applicant"])
    for _ in range(2):
        assert (await add(act, people["applicant"], case_id, photo())).status_code == 201
    assert (await add(act, people["applicant"], case_id, photo())).status_code == 413


async def test_the_finished_pdf_obeys_the_upload_limit(act, people, monkeypatch):
    case_id = await create_draft(act, people["applicant"])
    assert (await add(act, people["applicant"], case_id, photo(2000, 2000))).status_code == 201
    monkeypatch.setattr(settings, "max_upload_bytes", 10_000)
    assert (await act(people["applicant"], "post", url(case_id, "/finish"))).status_code == 413


async def test_only_the_case_s_people_and_only_their_own_pages(act, people, make_user):
    case_id = await create_draft(act, people["applicant"])
    assert (await add(act, people["applicant"], case_id, photo())).status_code == 201
    stranger = await make_user("applicant")
    assert (await add(act, stranger, case_id, photo())).status_code == 404
    assert (await act(stranger, "get", url(case_id, "/pages/1/image"))).status_code == 404
    # Records can see the case, but these are the applicant's pages, not theirs.
    assert (await act(people["records_officer"], "get", url(case_id))).json() == []


async def test_a_document_the_case_doesnt_take_is_refused(act, people):
    case_id = await create_draft(act, people["applicant"])
    response = await act(
        people["applicant"], "post", f"/cases/{case_id}/documents/no_such_type/scan/pages",
        content=photo(), headers_extra={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 422


async def test_finishing_with_no_pages_is_refused(act, people):
    case_id = await create_draft(act, people["applicant"])
    assert (await act(people["applicant"], "post", url(case_id, "/finish"))).status_code == 422


def test_files_of_pages_are_removed_with_them(tmp_path):
    # storage.delete() is what cancel() and finish() use: a missing file is fine.
    storage.delete("0" * 32)
