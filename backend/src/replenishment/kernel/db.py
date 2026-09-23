from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from sqlalchemy import MetaData, Numeric
from sqlalchemy.orm import DeclarativeBase, mapped_column

Id = Annotated[UUID, mapped_column(primary_key=True, default=uuid4)]
# Retain signed quantities and source coefficient precision. Unknowns remain NULL.
Number = Annotated[Decimal, mapped_column(Numeric(30, 12))]


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
