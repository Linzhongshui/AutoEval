"""Official pricing evidence and independent CNY budget accounts."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.models import Base, Record


class ModelPrice(Record, Base):
    __tablename__ = 'model_price_version'
    provider: Mapped[str] = mapped_column(String(64))
    remote_model: Mapped[str] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(3), default='CNY')
    source_url: Mapped[str] = mapped_column(String(2048))
    source_sha256: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rates: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('provider', 'remote_model', 'source_sha256'),
                      CheckConstraint("currency = 'CNY'"),)


class BudgetAccount(Record, Base):
    __tablename__ = 'model_budget_account'
    budget_key: Mapped[str] = mapped_column(String(128), unique=True)
    currency: Mapped[str] = mapped_column(String(3), default='CNY')
    total_limit: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    evaluation_limit: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    analysis_limit: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    reserved: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal(0))
    spent: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal(0))
    state: Mapped[str] = mapped_column(String(24), default='configured')
    policy: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        CheckConstraint("currency = 'CNY'"),
        CheckConstraint('total_limit > 0 AND evaluation_limit >= 0 AND analysis_limit >= 0'),
        CheckConstraint('evaluation_limit + analysis_limit <= total_limit'),
        CheckConstraint('reserved >= 0 AND spent >= 0 AND reserved + spent <= total_limit'),
        CheckConstraint("state IN ('configured','active','blocked','closed')"),
    )


class TargetBilling(Record, Base):
    __tablename__ = 'target_billing_binding'
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('target_binding_version.id'), unique=True)
    price_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('model_price_version.id'))
    budget_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('model_budget_account.id'))
    billing_basis: Mapped[str] = mapped_column(String(32))
    __table_args__ = (CheckConstraint("billing_basis IN ('official_direct','official_reference')"),)
