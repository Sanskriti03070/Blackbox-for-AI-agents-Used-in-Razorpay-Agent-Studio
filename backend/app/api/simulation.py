import uuid
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.db.session import get_db_session
from app.simulation import services
from app.simulation.models import Communication, Customer, Payment, PaymentLink, Refund, Subscription

router = APIRouter(tags=["payment-simulation"])
class ORM(BaseModel): model_config = ConfigDict(from_attributes=True)
class PaymentOut(ORM): id: uuid.UUID; merchant_id: uuid.UUID; customer_id: uuid.UUID; subscription_id: uuid.UUID | None; retry_of_payment_id: uuid.UUID | None; amount: Decimal; currency: str; status: str; failure_code: str | None
class CustomerOut(ORM): id: uuid.UUID; merchant_id: uuid.UUID; name: str; email: str; phone: str | None
class SubscriptionOut(ORM): id: uuid.UUID; merchant_id: uuid.UUID; customer_id: uuid.UUID; plan_name: str; amount: Decimal; currency: str; status: str
class LinkOut(ORM): id: uuid.UUID; customer_id: uuid.UUID; payment_id: uuid.UUID | None; subscription_id: uuid.UUID | None; token: str; amount: Decimal; currency: str; status: str
class RefundOut(ORM): id: uuid.UUID; payment_id: uuid.UUID; amount: Decimal; currency: str
class MessageOut(ORM): id: uuid.UUID; customer_id: uuid.UUID; channel: str; body: str; status: str
class RetryIn(BaseModel): idempotency_key: str | None = Field(default=None, max_length=128)
class LinkIn(BaseModel): customer_id: uuid.UUID; amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2); currency: str = Field(default="INR", min_length=3, max_length=3); payment_id: uuid.UUID | None = None; subscription_id: uuid.UUID | None = None; idempotency_key: str | None = Field(default=None, max_length=64)
class MessageIn(BaseModel): customer_id: uuid.UUID; channel: str = Field(min_length=1, max_length=32); body: str = Field(min_length=1, max_length=5000); idempotency_key: str | None = Field(default=None, max_length=128)
class RefundIn(BaseModel): payment_id: uuid.UUID; amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2); idempotency_key: str | None = Field(default=None, max_length=128)
def call(operation):
    try: return operation()
    except services.NotFoundError as error: raise HTTPException(404, str(error)) from error
    except services.InvalidOperationError as error: raise HTTPException(409, str(error)) from error
@router.get("/payments/{payment_id}", response_model=PaymentOut)
def payment(payment_id: uuid.UUID, session: Session = Depends(get_db_session)): return call(lambda: services.get_payment(session, payment_id))
@router.get("/customers/{customer_id}", response_model=CustomerOut)
def customer(customer_id: uuid.UUID, session: Session = Depends(get_db_session)): return call(lambda: services.get_customer(session, customer_id))
@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionOut)
def subscription(subscription_id: uuid.UUID, session: Session = Depends(get_db_session)): return call(lambda: services.get_subscription(session, subscription_id))
@router.get("/payments/{payment_id}/history", response_model=list[PaymentOut])
def history(payment_id: uuid.UUID, session: Session = Depends(get_db_session)): return call(lambda: services.get_payment_history(session, payment_id))
@router.post("/payments/{payment_id}/retry", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def retry(payment_id: uuid.UUID, body: RetryIn, session: Session = Depends(get_db_session)):
    result = call(lambda: services.retry_payment(session, payment_id, body.idempotency_key)); session.commit(); return result
@router.post("/payment-links", response_model=LinkOut, status_code=status.HTTP_201_CREATED)
def link(body: LinkIn, session: Session = Depends(get_db_session)):
    result = call(lambda: services.create_payment_link(session, **body.model_dump())); session.commit(); return result
@router.post("/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def message(body: MessageIn, session: Session = Depends(get_db_session)):
    result = call(lambda: services.send_message(session, **body.model_dump())); session.commit(); return result
@router.post("/refunds", response_model=RefundOut, status_code=status.HTTP_201_CREATED)
def refund(body: RefundIn, session: Session = Depends(get_db_session)):
    result = call(lambda: services.issue_refund(session, **body.model_dump())); session.commit(); return result
