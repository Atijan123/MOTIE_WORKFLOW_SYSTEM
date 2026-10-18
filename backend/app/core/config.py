from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Each field is read from the environment variable of the same name
    # (case-insensitive). If a required one is missing, the app refuses to start
    # with a clear error instead of failing later.
    database_url: str

    # A short secret could be brute-forced, letting someone forge login tokens.
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 60


settings = Settings()
