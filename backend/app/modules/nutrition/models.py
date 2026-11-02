from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class OFFBase(DeclarativeBase):
    """Separate Base for OFF products database."""

    pass


class OFFProductLocal(OFFBase):
    """
    Local copy of Open Food Facts product data.
    Using Text for fields to avoid truncation errors with dirty data.
    """

    __tablename__ = 'off_products_local'

    barcode: Mapped[str] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return (
            f'<OFFProductLocal(barcode="{self.barcode}", name="{self.name[:30]}...")>'
        )
