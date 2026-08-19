from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import BrokerDep, CurrentAdmin, CurrentMember, DbSession
from app.core.config import settings
from app.core.errors import NotFoundError
from app.models.fund import Fund, Position
from app.models.trade import Order
from app.schemas.common import FundCreate, FundOut, PositionOut
from app.schemas.market import DecisionOut, OrderOut, RejectRequest
from app.services import execution

router = APIRouter(tags=["trading"])


@router.post("/funds", response_model=FundOut, status_code=status.HTTP_201_CREATED)
def create_fund(payload: FundCreate, db: DbSession, _: CurrentAdmin) -> Fund:
    fund = Fund(name=payload.name, account_no=payload.account_no, broker=payload.broker)
    db.add(fund)
    db.commit()
    db.refresh(fund)
    return fund


@router.get("/funds", response_model=list[FundOut])
def list_funds(db: DbSession, _: CurrentMember) -> list[Fund]:
    return list(db.scalars(select(Fund).order_by(Fund.id)).all())


@router.post("/decisions/{decision_id}/approve", response_model=OrderOut)
def approve_decision(
    decision_id: int, db: DbSession, broker: BrokerDep, admin: CurrentAdmin
) -> Order:
    """결정을 승인해 실제 주문을 낸다. 리스크 가드를 통과해야만 나간다."""
    decision = execution.get_decision(db, decision_id)
    order = execution.execute_decision(db, decision, broker, admin_id=admin.id)
    db.commit()
    db.refresh(order)
    return order


@router.post("/decisions/{decision_id}/reject", response_model=DecisionOut)
def reject_decision(
    decision_id: int, payload: RejectRequest, db: DbSession, admin: CurrentAdmin
):
    decision = execution.get_decision(db, decision_id)
    execution.reject_decision(db, decision, admin_id=admin.id, reason=payload.reason)
    db.commit()
    db.refresh(decision)
    return decision


@router.get("/orders", response_model=list[OrderOut])
def list_orders(db: DbSession, _: CurrentMember, limit: int = 50) -> list[Order]:
    return list(
        db.scalars(select(Order).order_by(Order.id.desc()).limit(min(limit, 200))).all()
    )


@router.get("/funds/{fund_id}/positions", response_model=list[PositionOut])
def list_positions(fund_id: int, db: DbSession, _: CurrentMember) -> list[Position]:
    if db.get(Fund, fund_id) is None:
        raise NotFoundError(f"펀드 {fund_id}을(를) 찾을 수 없습니다.")
    return list(
        db.scalars(
            select(Position).where(Position.fund_id == fund_id, Position.quantity > 0)
        ).all()
    )


@router.post("/funds/{fund_id}/sync", response_model=list[PositionOut])
def sync_fund(fund_id: int, db: DbSession, broker: BrokerDep, _: CurrentAdmin) -> list[Position]:
    """증권사 잔고를 읽어 로컬 포지션을 맞춘다."""
    if db.get(Fund, fund_id) is None:
        raise NotFoundError(f"펀드 {fund_id}을(를) 찾을 수 없습니다.")
    positions = execution.sync_positions(db, fund_id, broker)
    db.commit()
    return [p for p in positions if p.quantity > 0]


@router.get("/system/status")
def system_status(_: CurrentMember) -> dict:
    """지금 이 서버가 어떤 모드로 돌고 있는지. UI 상단 배너에 쓴다."""
    return {
        "broker_backend": settings.broker_backend,
        "kis_env": settings.kis_env,
        "live_trading_enabled": settings.live_trading_enabled,
        "kill_switch": settings.kill_switch,
        "max_order_amount_krw": str(settings.max_order_amount_krw),
        "max_daily_orders": settings.max_daily_orders,
        "execution_min_probability": str(settings.execution_min_probability),
        "quorum_ratio": str(settings.quorum_ratio),
    }
