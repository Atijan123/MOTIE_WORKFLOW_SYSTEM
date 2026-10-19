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


settings = Settings()
