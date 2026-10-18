from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Parent class for every table class. Its `metadata` lists all tables."""
