from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import BrokerDep, CurrentAdmin, CurrentMember, DbSession
from app.models.symbol import Symbol
from app.schemas.common import QuoteOut, SymbolOut
from app.services import symbols

router = APIRouter(tags=["symbols"])


@router.get("/symbols", response_model=list[SymbolOut])
def search_symbols(
    db: DbSession,
    _: CurrentMember,
    q: str = Query(min_length=1, max_length=50, description="티커 또는 종목명"),
    limit: int = Query(default=10, ge=1, le=symbols.MAX_SEARCH_RESULTS),
) -> list[Symbol]:
    """마켓 개설 화면의 자동완성. 로컬 종목 마스터에서 찾는다."""
    return symbols.search(db, q, limit=limit)


@router.get("/symbols/{ticker}/quote", response_model=QuoteOut)
def quote_symbol(ticker: str, db: DbSession, broker: BrokerDep, _: CurrentAdmin) -> QuoteOut:
    """증권사에 직접 물어 종목 존재와 현재가를 확인한다.

    마켓을 열기 전 티커 오타를 잡는 자리다. 조회로 알게 된 정식 이름은 마스터에
    반영되므로, 마스터가 비어 있어도 쓸수록 채워진다.
    """
    quote = symbols.lookup(db, ticker, broker)
    db.commit()
    return QuoteOut(
        ticker=quote.ticker,
        name=quote.name,
        price=quote.price,
        prev_close=quote.prev_close,
    )
