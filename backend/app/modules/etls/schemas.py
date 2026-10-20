from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, field_validator

# Stripped of surrounding spaces, never empty, and bounded so nobody can store a
# novel in a form field.
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Number = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


def normalize_hs_code(code: str) -> str:
    """"2523.29", "2523 29" and "252329" are the same HS code: keep the digits.

    6 digits is the international HS code; 8 or 10 are national/ECOWAS tariff lines.
    """
    digits = "".join(code.replace(".", "").split())
    if not digits.isascii() or not digits.isdigit() or len(digits) not in (6, 8, 10):
        raise ValueError("an HS code is 6, 8 or 10 digits, e.g. 2523.29")
    return digits


HsCode = Annotated[str, StringConstraints(max_length=20), AfterValidator(normalize_hs_code)]


def normalize_certificate_number(number: str) -> str:
    """"cg 2026/0042 " and "CG2026/0042" are the same certificate."""
    return "".join(number.split()).upper()


class FacilityLetterForm(BaseModel):
    importer_name: ShortText
    importer_address: LongText
    product: ShortText
    # [CONFIRM] Required from the applicant: importers have it from their
    # customs declaration, and the documents check needs it before an officer
    # confirms it.
    hs_code: HsCode
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
    exporter_name: ShortText
    exporter_country: ShortText
    exporter_etls_approval_number: Number
    product_approval_numbers: list[Number] = Field(min_length=1, max_length=50)
    certificate_of_origin_numbers: list[Number] = Field(min_length=1, max_length=50)

    @field_validator("product_approval_numbers")
    @classmethod
    def _no_repeated_approvals(cls, numbers: list[str]) -> list[str]:
        if len(set(numbers)) != len(numbers):
            raise ValueError("a product approval number is listed twice")
        return numbers

    @field_validator("certificate_of_origin_numbers")
    @classmethod
    def _no_repeated_certificates(cls, numbers: list[str]) -> list[str]:
        normalized = [normalize_certificate_number(n) for n in numbers]
        if len(set(normalized)) != len(normalized):
            raise ValueError("a certificate of origin number is listed twice")
        return numbers


class FacilityLetterOut(FacilityLetterForm):
    case_id: int
    status: str  # status code; GET /cases/{id} has the full case and the next actions
    # Cases from before step 6g have no declared code.
    hs_code: str | None
    hs_code_confirmed: str | None


class HsCodeConfirmation(BaseModel):
    hs_code: HsCode
