from string import Formatter
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

# The only placeholders a file reference format may use.
REFERENCE_FIELDS = {"year", "case_id"}


class Settings(BaseSettings):
    # Each field is read from the environment variable of the same name
    # (case-insensitive). If a required one is missing, the app refuses to start
    # with a clear error instead of failing later.
    database_url: str  # the API's own user (motie_app)

    # "development" only on a developer's machine. Tools that delete or invent
    # data (scripts/reset-dev.sh, app/dev_seed.py) refuse to run otherwise.
    # The default is "production", so a server that forgets to set it is safe.
    app_env: Literal["development", "production"] = "production"

    # The schema owner (motie_owner), used by Alembic and tests only. The API
    # container doesn't get it, so a compromised API can't alter tables.
    migration_database_url: str | None = None

    # A short secret could be brute-forced, letting someone forge login tokens.
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 60

    # Uploaded documents are stored here, one file per upload, under a random
    # name. In Compose it's the "documents" volume; back it up with the database.
    document_storage_dir: str = "/data/documents"
    # Bigger uploads are refused (413) while they stream in, before they fill the disk.
    max_upload_bytes: int = 10 * 1024 * 1024

    # [CONFIRM] The Ministry's file reference format for ETLS facility letters.
    # Placeholders: {year} and {case_id}, e.g. {case_id:05d} for 00042.
    facility_letter_reference_format: str = "MOTIE/ETLS/FL/{year}/{case_id:05d}"

    @field_validator("facility_letter_reference_format")
    @classmethod
    def _only_known_placeholders(cls, value: str) -> str:
        # str.format() can reach into objects ("{case_id.__class__}"), so allow
        # plain known names only, and fail at startup rather than on a letter.
        for _, field, _, _ in Formatter().parse(value):
            if field is not None and field not in REFERENCE_FIELDS:
                raise ValueError(f"unknown placeholder {{{field}}}; use only {sorted(REFERENCE_FIELDS)}")
        return value


settings = Settings()
