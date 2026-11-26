from string import Formatter
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

# The only placeholders a file reference format may use.
REFERENCE_FIELDS = {"year", "case_id"}
# The registry file reference from the spec's example. Used on a developer's
# machine only: a real server must be told the Ministry's own.
DEV_REGISTRY_REFERENCE = "ADM 151/420/01/PART IV"


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

    # How emails leave. Only "fake" exists yet: it logs them and sends nothing.
    # [CONFIRM] the Ministry's mail server; then "smtp" with its settings.
    email_backend: Literal["fake"] = "fake"
    # How often the notification worker looks for emails to send.
    notification_poll_seconds: int = 30

    # Where people open the site; links in emails start with it.
    # [CONFIRM] the Ministry's address for the service.
    public_base_url: str = "http://localhost:3000"
    # How long a "set your password" link works. [CONFIRM] with the Ministry.
    password_link_hours: int = Field(default=72, gt=0, le=24 * 14)

    # The Ministry's registry file reference, printed at the top of each ETLS
    # facility letter (SCREENS.md global rules). Not the case reference
    # (MOTIE/ETLS/FL/2026/0001), which is the tracking number. [CONFIRM] what
    # its parts mean, and whether any part changes per letter. Placeholders
    # {year} and {case_id} are allowed, e.g. "ADM 151/420/01/{year}".
    # Empty = not set. Read it through registry_reference_format().
    facility_letter_reference_format: str | None = None

    # --- The two front ends (step 12b) ---------------------------------------
    # Each front end's server proves which one it is with its own key, sent as
    # X-Portal-Key on every API call. Only the staff app's server knows the
    # staff key, so the public applicant portal can't call the API as the staff
    # app, even if it is broken into. Unset = that portal can't be used at all.
    # Keys starting "dev-" (docker-compose.yml's defaults) only work in development.
    staff_portal_key: str | None = Field(default=None, min_length=32)
    applicant_portal_key: str | None = Field(default=None, min_length=32)
    # The domains each portal is served on, comma-separated, e.g.
    # "staff.motie.gov.gm". A staff request whose browser address is an
    # applicant domain is refused; with staff hosts set, any other domain is too.
    # Empty (development) = not checked.
    staff_portal_hosts: str = ""
    applicant_portal_hosts: str = ""

    @field_validator("staff_portal_key", "applicant_portal_key", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: str | None) -> str | None:
        # Compose passes an empty value when .env leaves a key out.
        return value.strip() or None if isinstance(value, str) else value

    def portal_key(self, portal: str) -> str | None:
        key = self.staff_portal_key if portal == "staff" else self.applicant_portal_key
        if key and key.startswith("dev-") and self.app_env != "development":
            return None  # the published dev default must never open a real server
        return key

    @staticmethod
    def _hosts(text: str) -> set[str]:
        return {h.strip().lower() for h in text.split(",") if h.strip()}

    def portal_hosts(self, portal: str) -> set[str]:
        return self._hosts(self.staff_portal_hosts if portal == "staff" else self.applicant_portal_hosts)

    @field_validator("facility_letter_reference_format")
    @classmethod
    def _only_known_placeholders(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None  # Compose passes an empty value when .env leaves it out
        # str.format() can reach into objects ("{case_id.__class__}"), so allow
        # plain known names only, and fail at startup rather than on a letter.
        for _, field, _, _ in Formatter().parse(value):
            if field is not None and field not in REFERENCE_FIELDS:
                raise ValueError(f"unknown placeholder {{{field}}}; use only {sorted(REFERENCE_FIELDS)}")
        return value.strip()

    def registry_reference_format(self) -> str | None:
        """The reference to print, or None when a real server hasn't been told
        it. Signing is then blocked (check etls_registry_reference_set), so no
        letter goes out with the example reference."""
        if self.facility_letter_reference_format:
            return self.facility_letter_reference_format
        return DEV_REGISTRY_REFERENCE if self.app_env == "development" else None


settings = Settings()
