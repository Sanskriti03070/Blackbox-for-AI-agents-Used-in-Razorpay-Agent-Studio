from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["backend"]


class DatabaseHealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["connected"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="backend")


@router.get("/health/db", response_model=DatabaseHealthResponse)
def database_health(session: Session = Depends(get_db_session)) -> DatabaseHealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc

    return DatabaseHealthResponse(status="ok", database="connected")
