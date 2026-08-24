"""Explicit deterministic seed command: python -m app.simulation.seed."""
import uuid
from decimal import Decimal
from sqlalchemy import select
from app.db.session import SessionLocal
from app.simulation.models import Customer, Merchant, Payment, PaymentStatus, Subscription, SubscriptionStatus
MERCHANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
def run() -> None:
    with SessionLocal() as session:
        if session.get(Merchant, MERCHANT_ID): return
        merchant = Merchant(id=MERCHANT_ID, name="Acme Fitness", email="billing@acme-fitness.test")
        ava = Customer(id=uuid.UUID("00000000-0000-0000-0000-000000000011"), merchant=merchant, name="Ava Shah", email="ava@example.test")
        ben = Customer(id=uuid.UUID("00000000-0000-0000-0000-000000000012"), merchant=merchant, name="Ben Kumar", email="ben@example.test")
        cora = Customer(id=uuid.UUID("00000000-0000-0000-0000-000000000013"), merchant=merchant, name="Cora Das", email="cora@example.test")
        sa = Subscription(id=uuid.UUID("00000000-0000-0000-0000-000000000021"), merchant_id=MERCHANT_ID, customer=ava, plan_name="Pro Monthly", amount=Decimal("999.00"), currency="INR", status=SubscriptionStatus.ACTIVE)
        sb = Subscription(id=uuid.UUID("00000000-0000-0000-0000-000000000022"), merchant_id=MERCHANT_ID, customer=ben, plan_name="Enterprise", amount=Decimal("75000.00"), currency="INR", status=SubscriptionStatus.PAST_DUE)
        sc = Subscription(id=uuid.UUID("00000000-0000-0000-0000-000000000023"), merchant_id=MERCHANT_ID, customer=cora, plan_name="Starter", amount=Decimal("499.00"), currency="INR", status=SubscriptionStatus.ACTIVE)
        payments = [Payment(id=uuid.UUID("00000000-0000-0000-0000-000000000031"), merchant_id=MERCHANT_ID, customer=ava, subscription=sa, amount=Decimal("999.00"), currency="INR", status=PaymentStatus.CAPTURED), Payment(id=uuid.UUID("00000000-0000-0000-0000-000000000032"), merchant_id=MERCHANT_ID, customer=ava, subscription=sa, amount=Decimal("999.00"), currency="INR", status=PaymentStatus.FAILED, failure_code="card_declined"), Payment(id=uuid.UUID("00000000-0000-0000-0000-000000000033"), merchant_id=MERCHANT_ID, customer=ben, subscription=sb, amount=Decimal("75000.00"), currency="INR", status=PaymentStatus.FAILED, failure_code="retry_declined"), Payment(id=uuid.UUID("00000000-0000-0000-0000-000000000034"), merchant_id=MERCHANT_ID, customer=cora, subscription=sc, amount=Decimal("499.00"), currency="INR", status=PaymentStatus.CAPTURED)]
        session.add_all([merchant, ava, ben, cora, sa, sb, sc, *payments]); session.commit()
if __name__ == "__main__": run()
