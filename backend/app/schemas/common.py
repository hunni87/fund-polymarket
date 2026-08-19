from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import Role


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MemberCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.MEMBER


class MemberOut(ORMModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime


class MemberWithBalance(MemberOut):
    balance: Decimal


class FundCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    account_no: str = Field(min_length=1, max_length=20)
    broker: str = "KIS"


class FundOut(ORMModel):
    id: int
    name: str
    broker: str
    account_no: str
    base_currency: str
    is_active: bool


class PositionOut(ORMModel):
    id: int
    ticker: str
    ticker_name: str | None
    quantity: int
    avg_price: Decimal


class LedgerEntryOut(ORMModel):
    id: int
    market_id: int | None
    entry_type: str
    amount: Decimal
    memo: str | None
    created_at: datetime


class ScoreOut(BaseModel):
    member_id: int
    name: str
    balance: Decimal
    net_profit: Decimal
    settled_markets: int
    hits: int
    hit_rate: Decimal
    brier: Decimal | None


class SymbolOut(ORMModel):
    ticker: str
    name: str
    market: str | None


class QuoteOut(BaseModel):
    ticker: str
    name: str | None
    price: Decimal
    prev_close: Decimal | None
