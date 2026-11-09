"""Fictional facility letter cases for a demo (development only).

    scripts/seed-demo.sh      resets the dev database, then runs this

Every person, business and number here is made up. The cases are made through
the API itself, logged in as the dev users (app/dev_seed.py), so their
history, audit rows, references and emails are exactly what real use would
give. It refuses to run unless APP_ENV=development.

The cases, one per stage of the route:
  1. sent to GRA            (whole route, signed by the Director; the importer can download
                             their copy; its certificate is reused by case 6)
  2. signed, to dispatch    (the Director away: an authorised signatory signs, "in the Director's absence")
  3. verified, to sign      (waiting for the Director, or while they're away, a signatory)
  4. at the desk            (cement: the receipt applies; ready to check)
  5. returned               (Records asked for a clearer invoice)
  6. flagged duplicate      (at the desk, on hold: same certificate as case 1)
  7. submitted              (waiting for Records)
  8. draft                  (half filled in)

Plus a small fictional register of historical letters (write_demo_register()),
imported the way the real one is, so the Statistics page (S13) has history:
three letters, one of them filed twice, and one data check.
"""

import asyncio
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
from fpdf import FPDF

from app.core.config import settings
from app.core.identity.service import create_user, get_user_by_email
from app.dev_seed import DEFAULT_PASSWORD

API_URL = os.environ.get("DEMO_API_URL", "http://api:8000")

# Fictional applicants: (email, name). Each logs in with the dev password.
APPLICANTS = [
    ("fatou.jallow@demo.test", "Fatou Jallow"),
    ("lamin.ceesay@demo.test", "Lamin Ceesay"),
    ("awa.touray@demo.test", "Awa Touray"),
]


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def form(**changes) -> dict:
    base = {
        "importer_name": "Kombo Feeds Ltd",
        "importer_address": "14 Kairaba Avenue, Serrekunda",
        "product": "Poultry feed",
        "hs_code": "2309.90",
        "quantity": "1200",
        "unit": "bags",
        "exporter_name": "Dakar Agro SA",
        "exporter_country": "Senegal",
        "exporter_etls_approval_number": "SN-ETLS-0042",
        "product_approval_numbers": ["SN-PA-0042-01"],
        "certificates_of_origin": [{"number": "SN-CO-2026-1001", "issued_on": days_ago(20)}],
    }
    base.update(changes)
    return base


def demo_pdf(title: str, case_label: str) -> bytes:
    """A one-page PDF that says plainly it's a made-up demo document."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 14, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 13)
    pdf.cell(0, 10, case_label, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.multi_cell(0, 8, "DEMO DOCUMENT. Fictional: every name, number and amount is made up. Not a real record.")
    return bytes(pdf.output())


class Demo:
    def __init__(self, client: httpx.AsyncClient, password: str):
        self.client = client
        self.password = password
        self.tokens: dict[str, str] = {}

    async def call(self, who: str, method: str, path: str, expect: int = 200, **kwargs) -> dict | None:
        if who not in self.tokens:
            r = await self.client.post("/auth/login", json={"email": who, "password": self.password})
            r.raise_for_status()
            self.tokens[who] = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {self.tokens[who]}", **kwargs.pop("headers", {})}
        r = await self.client.request(method, path, headers=headers, **kwargs)
        if r.status_code != expect:
            sys.exit(f"Demo seed stopped: {who} {method} {path} gave {r.status_code}: {r.text}")
        return r.json() if r.content else None

    async def move(self, who: str, case_id: int, to_status: str, **body) -> dict:
        return await self.call(who, "POST", f"/cases/{case_id}/status", json={"to_status": to_status, **body})

    # --- one step of the route each ---

    async def draft(self, applicant: str, **changes) -> int:
        letter = await self.call(applicant, "POST", "/etls/facility-letters", expect=201, json=form(**changes))
        return letter["case_id"]

    async def upload_all(self, applicant: str, case_id: int, label: str) -> None:
        for item in await self.call(applicant, "GET", f"/cases/{case_id}/documents"):
            if item["missing"]:
                await self.call(
                    applicant, "POST", f"/cases/{case_id}/documents/{item['type']}", expect=201,
                    content=demo_pdf(item["name"], label),
                    params={"filename": f"{item['type']}.pdf"},
                    headers={"Content-Type": "application/octet-stream"},
                )

    async def submitted(self, applicant: str, label: str, **changes) -> int:
        case_id = await self.draft(applicant, **changes)
        await self.upload_all(applicant, case_id, label)
        await self.move(applicant, case_id, "submitted")
        return case_id

    async def accepted(self, case_id: int) -> None:
        records = "records@motie.test"
        for item in await self.call(records, "GET", f"/cases/{case_id}/documents"):
            if item["original_pending"] and item["documents"]:
                await self.call(records, "POST", f"/cases/{case_id}/documents/{item['documents'][0]['id']}/original-seen")
        await self.move(records, case_id, "originals_received")

    async def verified(self, case_id: int, hs_code: str = "2309.90") -> None:
        desk = "desk@motie.test"
        await self.call(desk, "POST", f"/etls/facility-letters/{case_id}/hs-code", json={"hs_code": hs_code})
        for tick in await self.call(desk, "GET", f"/cases/{case_id}/checklist"):
            if tick["at_current_step"] and not tick["ticked"]:
                await self.call(desk, "PUT", f"/cases/{case_id}/checklist/{tick['code']}", json={"ticked": True})
        await self.move(desk, case_id, "verified")


async def seed_users(session, password: str) -> None:
    """The fictional applicants (the staff come from app/dev_seed.py)."""
    for email, name in APPLICANTS:
        if await get_user_by_email(session, email) is None:
            await create_user(session, email=email, full_name=name, password=password, role_codes=["applicant"])


async def _users(password: str) -> None:
    from app.db.session import SessionLocal, engine

    try:
        async with SessionLocal() as session:
            await seed_users(session, password)
    finally:
        await engine.dispose()


async def _wait_for_api(client: httpx.AsyncClient) -> None:
    # reset-dev.sh has only just started the API.
    deadline = time.monotonic() + 90
    while True:
        try:
            if (await client.get("/health/db")).status_code == 200:
                return
        except httpx.TransportError:
            pass
        if time.monotonic() > deadline:
            sys.exit(f"Demo seed stopped: the API at {API_URL} didn't answer.")
        await asyncio.sleep(2)


async def _cases(password: str) -> list[tuple[str, int]]:
    async with httpx.AsyncClient(base_url=API_URL, timeout=60) as client:
        await _wait_for_api(client)
        return await seed_cases(client, password)


async def seed_cases(client: httpx.AsyncClient, password: str) -> list[tuple[str, int]]:
    """Make the demo cases through the API `client` talks to. Returns
    ("<reference>  <stage>", case id) per case, in the order above.
    (Tests pass their in-process client.)"""
    fatou, lamin, awa = (email for email, _ in APPLICANTS)
    d = Demo(client, password)
    made = []

    # 1. The whole route, ending "Sent to GRA".
    c1 = await d.submitted(fatou, "Kombo Feeds Ltd: poultry feed")
    await d.accepted(c1)
    await d.verified(c1)
    await d.move("director@motie.test", c1, "signed")
    await d.call("records@motie.test", "POST", f"/etls/facility-letters/{c1}/sent-to-gra", json={"dispatched_on": date.today().isoformat()})
    made.append(("Sent to GRA", c1))

    # 2. Signed by the DPS, acting for the PS who is away; waiting for Records to dispatch.
    c2 = await d.submitted(
        lamin, "Ceesay Building Supplies: roofing sheets",
        importer_name="Ceesay Building Supplies", importer_address="3 Mosque Road, Brikama",
        product="Galvanised roofing sheets", hs_code="7210.49", quantity="850", unit="pieces",
        exporter_name="Accra Steel Works Ltd", exporter_country="Ghana",
        exporter_etls_approval_number="GH-ETLS-0310", product_approval_numbers=["GH-PA-0310-02"],
        certificates_of_origin=[{"number": "GH-CO-2026-0555", "issued_on": days_ago(35)}],
    )
    await d.accepted(c2)
    await d.verified(c2, hs_code="7210.49")
    await d.call("director@motie.test", "POST", "/absences", expect=201, json={
        "starts_on": date.today().isoformat(), "ends_on": (date.today() + timedelta(days=2)).isoformat(),
        "reason": "ECOWAS industry meeting (demo)",
    })
    await d.move("signer1@motie.test", c2, "signed", comment="Signed while the Director is at the ECOWAS meeting.")
    made.append(("Signed by an authorised signatory in the Director's absence; waiting for dispatch", c2))

    # 3. Verified: waiting for the Director (recorded as away, so both signatories see it too).
    c3 = await d.submitted(
        awa, "Touray Trading: palm oil",
        importer_name="Touray Trading Company", importer_address="27 Liberation Avenue, Banjul",
        product="Refined palm oil", hs_code="1511.90", quantity="400", unit="cartons",
        exporter_name="Abidjan Oils SARL", exporter_country="Côte d’Ivoire",
        exporter_etls_approval_number="CI-ETLS-0077", product_approval_numbers=["CI-PA-0077-01"],
        certificates_of_origin=[{"number": "CI-CO-2026-0201", "issued_on": days_ago(15)}],
    )
    await d.accepted(c3)
    await d.verified(c3, hs_code="1511.90")
    made.append(("Verified: waiting for signature", c3))

    # 4. At the desk, ready to check: cement, so the receipt applies once the code is confirmed.
    c4 = await d.submitted(
        lamin, "Ceesay Building Supplies: cement",
        importer_name="Ceesay Building Supplies", importer_address="3 Mosque Road, Brikama",
        product="Portland cement", hs_code="2523.29", quantity="300", unit="tonnes",
        exporter_name="Lagos Cement Plc", exporter_country="Nigeria",
        exporter_etls_approval_number="NG-ETLS-1204", product_approval_numbers=["NG-PA-1204-01"],
        certificates_of_origin=[{"number": "NG-CO-2026-0789", "issued_on": days_ago(40)}],
    )
    await d.accepted(c4)
    made.append(("At the ETLS desk, to verify", c4))

    # 5. Returned by Records: the applicant must fix and resubmit.
    c5 = await d.submitted(
        awa, "Touray Trading: rice",
        importer_name="Touray Trading Company", importer_address="27 Liberation Avenue, Banjul",
        product="Parboiled rice", hs_code="1006.30", quantity="2000", unit="bags",
        exporter_name="Saint-Louis Rice SA", exporter_country="Senegal",
        exporter_etls_approval_number="SN-ETLS-0158", product_approval_numbers=["SN-PA-0158-03"],
        certificates_of_origin=[{"number": "SN-CO-2026-1422", "issued_on": days_ago(10)}],
    )
    await d.move(
        "records@motie.test", c5, "returned",
        applicant_message="The invoice scan is unreadable. Please upload a clearer copy.",
        comment="Invoice page 2 is blurred.",
    )
    made.append(("Returned to the applicant", c5))

    # 6. Same certificate number as case 1: on hold at the desk.
    c6 = await d.submitted(
        lamin, "Ceesay Building Supplies: poultry feed",
        importer_name="Ceesay Building Supplies", importer_address="3 Mosque Road, Brikama",
        quantity="600",
    )
    await d.accepted(c6)
    made.append(("At the desk, on hold: duplicate certificate (same as case 1)", c6))

    # 7. Just submitted: waiting for Records.
    c7 = await d.submitted(
        fatou, "Kombo Feeds Ltd: maize",
        product="Yellow maize", hs_code="1005.90", quantity="150", unit="tonnes",
        exporter_name="Lomé Grains SARL", exporter_country="Togo",
        exporter_etls_approval_number="TG-ETLS-0021", product_approval_numbers=["TG-PA-0021-01"],
        certificates_of_origin=[{"number": "TG-CO-2026-0333", "issued_on": days_ago(5)}],
    )
    made.append(("Submitted: waiting for Records", c7))

    # 8. A draft, half filled in.
    c8 = await d.draft(
        awa,
        importer_name="Touray Trading Company", importer_address="27 Liberation Avenue, Banjul",
        product="Tomato paste", hs_code=None, quantity=None, unit="cartons",
        exporter_name="Kumasi Foods Ltd", exporter_country="Ghana",
        exporter_etls_approval_number=None, product_approval_numbers=[], certificates_of_origin=[],
    )
    made.append(("Draft, half filled in", c8))

    refs = {}
    for _, case_id in made:
        case = await d.call("records@motie.test", "GET", f"/cases/{case_id}")
        refs[case_id] = case["reference"] or "(draft, no reference yet)"
    return [(f"{refs[case_id]:<26} {label}", case_id) for label, case_id in made]


def write_demo_register(folder: Path) -> Path:
    """A made-up register in the real one's format. Every name and number is fictional."""
    from app.modules.etls.import_history import write_register

    letters = [
        {"Letter no.": 1, "Folio(s) in file": "2", "Letter reference": "ADM 151/420/01/PART III",
         "Letter date": "14th August, 2025", "Importer": "Kombo Feeds Ltd", "Goods (as in letter)": "Poultry feed",
         "Category": "Animal feed", "Exporter": "Dakar Agro SA", "Exporter country": "Senegal",
         "Exporter approval no. (standard)": "SN-ETLS-0042", "Certificate of origin no(s).": "SN-CO-2025-0700",
         "Signed by": "Demo Director (fictional)", "Signed as": "For: Permanent Secretary",
         "Also filed at (second copy of this letter)": "File 2, p. 3 (folio 3)"},
        {"Letter no.": 3, "Folio(s) in file": "7", "Letter reference": "ADM 151/420/01/PART III",
         "Letter date": "2nd December, 2025", "Importer": "Ceesay Building Supplies", "Goods (as in letter)": "Cement",
         "Category": "Cement", "Exporter": "Lagos Cement Plc", "Exporter country": "Nigeria",
         "Certificate of origin no(s).": "NG-CO-2025-0310; NG-CO-2025-0311",
         "Signed by": "Demo Director (fictional)", "Signed as": "For: Permanent Secretary"},
        {"Letter no.": 4, "Folio(s) in file": "9", "Letter reference": "ADM 151/420/01/PART III",
         "Letter date": "20th January, 2026", "Importer": "Touray Trading Company", "Goods (as in letter)": "Palm oil",
         "Category": "Food", "Exporter": "Abidjan Oils SARL", "Exporter country": "Côte d’Ivoire",
         "Certificate of origin no(s).": "NG-CO-2025-0311", "Signed by": "Demo Signatory (fictional)",
         "Signed as": "In the Director's absence"},
    ]
    goods = [
        {"Line no.": 1, "Letter no.": 1, "Product": "Poultry feed", "Category": "Animal feed", "Quantity": 900, "Unit": "bags"},
        {"Line no.": 2, "Letter no.": 3, "Product": "Portland cement", "Category": "Cement", "Quantity": 250, "Unit": "tonnes"},
        {"Line no.": 3, "Letter no.": 4, "Product": "Refined palm oil", "Category": "Food", "Quantity": 300, "Unit": "cartons"},
    ]
    checks = [
        {"Check no.": 1, "Folio(s)": "9", "What looks wrong": "Certificate NG-CO-2025-0311 also on folio 7",
         "What to check": "Ask the desk which consignment it covers"},
    ]
    return write_register(folder / "demo-register.xlsx", letters, goods, checks)


async def _history() -> list[str]:
    """Import the fictional register as the schema owner, as the real import does."""
    import tempfile

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.modules.etls.import_history import import_file

    engine = create_async_engine(settings.migration_database_url)
    try:
        with tempfile.TemporaryDirectory() as folder:
            async with AsyncSession(engine) as session:
                return (await import_file(session, write_demo_register(Path(folder)))).lines()
    finally:
        await engine.dispose()


def main() -> None:
    if settings.app_env != "development":
        sys.exit(f"Refusing to seed demo cases: APP_ENV is '{settings.app_env}', not 'development'.")
    password = os.environ.get("DEV_SEED_PASSWORD") or DEFAULT_PASSWORD
    asyncio.run(_users(password))
    made = asyncio.run(_cases(password))
    history = asyncio.run(_history())
    print("\nDemo cases (all fictional):")
    for line, _ in made:
        print(f"  {line}")
    print("\nFictional historical register imported:")
    for line in history:
        print(f"  {line}")
    print(f"\nDemo logins, all with the password: {password}")
    print("  Applicants:  fatou.jallow@demo.test   (Kombo Feeds Ltd)")
    print("               lamin.ceesay@demo.test   (Ceesay Building Supplies)")
    print("               awa.touray@demo.test     (Touray Trading Company)")
    print("  Records:     records@motie.test")
    print("  ETLS desk:   desk@motie.test")
    print("  Director:    director@motie.test      (recorded as away for 3 days: the signatories sign)")
    print("  Signatories: signer1@motie.test, signer2@motie.test")
    print("  List keeper: signatories@motie.test   (Signatories screen, S12)")
    print("  Statistics:  stats@motie.test, or director@motie.test  (S13)")
    print("  Recorder:    recorder@motie.test")
    print("  Admin:       admin@motie.test         (Lists)")
    print("\nOpen http://localhost:3001")


if __name__ == "__main__":
    main()
