"""종목 검색과 마스터 갱신."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.brokers.base import Broker, Quote
from app.models.symbol import Symbol

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 20


def search(db: Session, query: str, *, limit: int = 10) -> list[Symbol]:
    """티커 또는 이름으로 찾는다.

    숫자로만 이뤄진 질의는 티커로 본다. 종목명에 숫자가 들어가는 경우가 있어
    (예: 'SK바이오팜'은 아니지만 'KODEX 200') 이름 검색도 함께 돌린다.
    """
    q = query.strip()
    if not q:
        return []

    limit = max(1, min(limit, MAX_SEARCH_RESULTS))
    pattern = f"%{q}%"
    stmt = (
        select(Symbol)
        .where(
            Symbol.is_active.is_(True),
            or_(Symbol.ticker.like(f"{q}%"), Symbol.name.ilike(pattern)),
        )
        # 티커가 정확히 맞는 것을 맨 위로. 그 다음은 이름 짧은 순 — '삼성'을 쳤을 때
        # '삼성전자'가 '삼성바이오로직스'보다 먼저 나와야 고르기 쉽다.
        .order_by((Symbol.ticker == q).desc(), func.length(Symbol.name), Symbol.name)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def get(db: Session, ticker: str) -> Symbol | None:
    return db.get(Symbol, ticker.strip())


def upsert(db: Session, *, ticker: str, name: str, market: str | None = None) -> Symbol:
    ticker = ticker.strip()
    symbol = db.get(Symbol, ticker)
    if symbol is None:
        symbol = Symbol(ticker=ticker, name=name, market=market)
        db.add(symbol)
    else:
        symbol.name = name
        if market:
            symbol.market = market
        symbol.is_active = True
    db.flush()
    return symbol


def remember_quote(db: Session, quote: Quote) -> Symbol | None:
    """시세 조회로 알게 된 정식 이름을 마스터에 반영한다.

    증권사가 준 이름이 항상 옳다. 임포트한 CSV가 낡았어도 조회 한 번이면 교정된다.
    """
    if not quote.name:
        return None
    return upsert(db, ticker=quote.ticker, name=quote.name)


def lookup(db: Session, ticker: str, broker: Broker) -> Quote:
    """증권사에 종목을 물어본다. 존재 확인 + 현재가 + 정식 이름.

    마켓을 열기 전에 티커를 잘못 쳤는지 확인하는 경로다. 현재가를 함께 돌려주는
    이유는, 주문금액(notional_krw)을 정할 때 그게 필요하기 때문이다.
    """
    quote = broker.get_quote(ticker.strip())
    remember_quote(db, quote)
    return quote


# --------------------------------------------------------------------- 임포트


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated


REQUIRED_COLUMNS = ("ticker", "name")


def import_rows(db: Session, rows) -> ImportResult:
    """`{"ticker", "name", "market"}` 딕셔너리들을 마스터에 반영한다.

    형식이 깨진 행 때문에 전체 임포트가 죽지 않게 한다 — 상장 목록은 어디서 받든
    빈 줄이나 헤더 잔여물이 섞여 들어온다.
    """
    result = ImportResult()
    for row in rows:
        ticker = (row.get("ticker") or "").strip()
        name = (row.get("name") or "").strip()
        if not ticker or not name:
            result.skipped += 1
            continue

        existing = db.get(Symbol, ticker)
        upsert(db, ticker=ticker, name=name, market=(row.get("market") or "").strip() or None)
        if existing is None:
            result.created += 1
        else:
            result.updated += 1

    return result


def import_csv(db: Session, path: str | Path, *, encoding: str = "utf-8-sig") -> ImportResult:
    """`ticker,name,market` 헤더를 가진 CSV를 읽어들인다.

    utf-8-sig 가 기본인 이유: 국내 상장 목록은 엑셀을 거쳐 오는 경우가 많고,
    엑셀이 붙이는 BOM 때문에 첫 컬럼 이름이 'ticker'가 아니라 '\\ufeffticker'가 된다.
    """
    with Path(path).open(encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"CSV에 필요한 컬럼이 없습니다: {', '.join(missing)} "
                f"(발견된 컬럼: {', '.join(reader.fieldnames or [])})"
            )
        return import_rows(db, reader)
