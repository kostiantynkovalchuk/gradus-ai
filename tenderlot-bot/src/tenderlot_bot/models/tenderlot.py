"""
Mock mirror of the tenderlot.net production MariaDB schema.

When moving to production:
  1. Change engine URL to mysql+pymysql://...
  2. Remove this file's CREATE TABLE calls — the real tables already exist.
  3. Keep the ORM classes — they are the read-only interface used by tenderlot_repo.py.
"""

from datetime import datetime

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TenderlotBase(DeclarativeBase):
    pass


class TenderlotUser(TenderlotBase):
    """Mirror of tenderlot `users` view / table."""

    __tablename__ = "tenderlot_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)  # E.164 format
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20))  # "supplier" | "carrier"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TenderlotTender(TenderlotBase):
    """Mirror of tenderlot `tender` table."""

    __tablename__ = "tenderlot_tender"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    tender_type: Mapped[str] = mapped_column(String(50))  # "auction" | "proposal_collection"
    start_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="UAH")  # ISO 4217
    starts_at: Mapped[datetime] = mapped_column()
    ends_at: Mapped[datetime] = mapped_column()
    start_mail_status: Mapped[int] = mapped_column(Integer, default=0)  # 0=pending, 1=ready
    end_mail_status: Mapped[int] = mapped_column(Integer, default=0)
    target_role: Mapped[str] = mapped_column(String(20))  # "supplier"|"carrier"|"both"
