from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Read from the DATABASE_URL environment variable (name match is case-insensitive).
    # If it's missing, the app refuses to start with a clear error instead of failing later.
    database_url: str


settings = Settings()
