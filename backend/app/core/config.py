from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Each field is read from the environment variable of the same name
    # (case-insensitive). If a required one is missing, the app refuses to start
    # with a clear error instead of failing later.
    database_url: str  # the API's own user (motie_app)

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


settings = Settings()
