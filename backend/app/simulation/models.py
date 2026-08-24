import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PaymentStatus(str, enum.Enum):
    CREATED = "created"; PENDING = "pending"; AUTHORIZED = "authorized"; CAPTURED = "captured"; FAILED = "failed"; REFUNDED = "refunded"; PARTIALLY_REFUNDED = "partially_refunded"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"; PAST_DUE = "past_due"; CANCELLED = "cancelled"


class LinkStatus(str, enum.Enum):
    ACTIVE = "active"; PAID = "paid"; EXPIRED = "expired"; CANCELLED = "cancelled"


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Merchant(Timestamped, Base):
    __tablename__ = "merchants"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    customers: Mapped[list["Customer"]] = relationship(back_populates="merchant")


class Customer(Timestamped, Base):
    __tablename__ = "customers"; __table_args__ = (UniqueConstraint("merchant_id", "email", name="uq_customer_merchant_email"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False); email: Mapped[str] = mapped_column(String(320), nullable=False); phone: Mapped[str | None] = mapped_column(String(32))
    merchant: Mapped[Merchant] = relationship(back_populates="customers")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="customer")
    payments: Mapped[list["Payment"]] = relationship(back_populates="customer")
    payment_links: Mapped[list["PaymentLink"]] = relationship(back_populates="customer")
    communications: Mapped[list["Communication"]] = relationship(back_populates="customer")


class Subscription(Timestamped, Base):
    __tablename__ = "subscriptions"; __table_args__ = (Index("ix_subscriptions_customer_status", "customer_id", "status"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id"), index=True, nullable=False); customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    plan_name: Mapped[str] = mapped_column(String(160), nullable=False); amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False); currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[SubscriptionStatus] = mapped_column(Enum(SubscriptionStatus, name="subscription_status", values_callable=lambda values: [item.value for item in values]), index=True, nullable=False, default=SubscriptionStatus.ACTIVE)
    customer: Mapped[Customer] = relationship(back_populates="subscriptions"); payments: Mapped[list["Payment"]] = relationship(back_populates="subscription"); payment_links: Mapped[list["PaymentLink"]] = relationship(back_populates="subscription")


class Payment(Timestamped, Base):
    __tablename__ = "payments"; __table_args__ = (Index("ix_payments_subscription_attempted", "subscription_id", "attempted_at"), Index("ix_payments_customer_status", "customer_id", "status"))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id"), index=True, nullable=False); customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False); subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    retry_of_payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), index=True); idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False); currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, name="payment_status", values_callable=lambda values: [item.value for item in values]), index=True, nullable=False, default=PaymentStatus.CREATED); failure_code: Mapped[str | None] = mapped_column(String(80)); attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False); captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer: Mapped[Customer] = relationship(back_populates="payments"); subscription: Mapped[Subscription | None] = relationship(back_populates="payments"); refunds: Mapped[list["Refund"]] = relationship(back_populates="payment"); payment_links: Mapped[list["PaymentLink"]] = relationship(back_populates="payment")


class Refund(Base):
    __tablename__ = "refunds"; __table_args__ = (Index("ix_refunds_payment_created", "payment_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4); payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False); currency: Mapped[str] = mapped_column(String(3), nullable=False); idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    payment: Mapped[Payment] = relationship(back_populates="refunds")


class PaymentLink(Timestamped, Base):
    __tablename__ = "payment_links"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4); customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False); payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), index=True); subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False); amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False); currency: Mapped[str] = mapped_column(String(3), nullable=False); status: Mapped[LinkStatus] = mapped_column(Enum(LinkStatus, name="payment_link_status", values_callable=lambda values: [item.value for item in values]), index=True, nullable=False, default=LinkStatus.ACTIVE); expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer: Mapped[Customer] = relationship(back_populates="payment_links"); payment: Mapped[Payment | None] = relationship(back_populates="payment_links"); subscription: Mapped[Subscription | None] = relationship(back_populates="payment_links")


class Communication(Base):
    """Minimal persisted local message audit so recovery messaging has real state."""
    __tablename__ = "communications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4); customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False); channel: Mapped[str] = mapped_column(String(32), nullable=False); body: Mapped[str] = mapped_column(Text, nullable=False); idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True); status: Mapped[str] = mapped_column(String(32), nullable=False, default="sent"); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    customer: Mapped[Customer] = relationship(back_populates="communications")
