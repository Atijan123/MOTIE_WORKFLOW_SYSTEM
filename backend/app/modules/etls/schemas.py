from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

# Stripped of surrounding spaces, never empty, and bounded so nobody can store a
# novel in a form field.
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Number = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


def normalize_certificate_number(number: str) -> str:
    """"cg 2026/0042 " and "CG2026/0042" are the same certificate."""
    return "".join(number.split()).upper()


class FacilityLetterForm(BaseModel):
    importer_name: ShortText
    importer_address: LongText
    product: ShortText
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
