"""종목 검색과 마스터 임포트."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.brokers.mock import MockBroker
from app.models.symbol import Symbol
from app.services import symbols


@pytest.fixture
def master(db: Session) -> Session:
    for ticker, name, market in [
        ("005930", "삼성전자", "KOSPI"),
        ("005935", "삼성전자우", "KOSPI"),
        ("000660", "SK하이닉스", "KOSPI"),
        ("247540", "에코프로비엠", "KOSDAQ"),
    ]:
        symbols.upsert(db, ticker=ticker, name=name, market=market)
    return db


class TestSearch:
    def test_finds_by_ticker_prefix(self, master: Session) -> None:
        found = symbols.search(master, "0059")
        assert [s.ticker for s in found] == ["005930", "005935"]

    def test_finds_by_name_fragment(self, master: Session) -> None:
        found = symbols.search(master, "하이닉스")
        assert [s.ticker for s in found] == ["000660"]

    def test_exact_ticker_comes_first(self, master: Session) -> None:
        """'005930'을 치면 삼성전자가 삼성전자우보다 먼저 나와야 한다."""
        assert symbols.search(master, "005930")[0].ticker == "005930"

    def test_shorter_name_comes_first(self, master: Session) -> None:
        """'삼성'을 쳤을 때 '삼성전자'가 '삼성바이오로직스'보다 먼저 나와야 한다."""
        symbols.upsert(master, ticker="207940", name="삼성바이오로직스", market="KOSPI")
        assert [s.name for s in symbols.search(master, "삼성")] == [
            "삼성전자",
            "삼성전자우",
            "삼성바이오로직스",
        ]

    def test_blank_query_returns_nothing(self, master: Session) -> None:
        assert symbols.search(master, "   ") == []

    def test_delisted_symbols_are_hidden(self, master: Session) -> None:
        master.get(Symbol, "005935").is_active = False
        master.flush()
        assert [s.ticker for s in symbols.search(master, "0059")] == ["005930"]

    def test_limit_is_capped(self, master: Session) -> None:
        assert len(symbols.search(master, "0", limit=999)) <= symbols.MAX_SEARCH_RESULTS


class TestUpsert:
    def test_creates_then_updates(self, db: Session) -> None:
        symbols.upsert(db, ticker="005930", name="옛이름")
        symbols.upsert(db, ticker="005930", name="삼성전자", market="KOSPI")

        assert db.query(Symbol).count() == 1
        assert db.get(Symbol, "005930").name == "삼성전자"
        assert db.get(Symbol, "005930").market == "KOSPI"

    def test_reactivates_a_hidden_symbol(self, db: Session) -> None:
        symbols.upsert(db, ticker="005930", name="삼성전자")
        db.get(Symbol, "005930").is_active = False
        db.flush()

        symbols.upsert(db, ticker="005930", name="삼성전자")
        assert db.get(Symbol, "005930").is_active

    def test_market_is_not_erased_by_a_later_upsert_without_one(self, db: Session) -> None:
        """시세 조회는 시장 구분을 주지 않는다. 있던 값을 지우면 안 된다."""
        symbols.upsert(db, ticker="005930", name="삼성전자", market="KOSPI")
        symbols.upsert(db, ticker="005930", name="삼성전자")
        assert db.get(Symbol, "005930").market == "KOSPI"


class TestLookup:
    def test_quote_lookup_fills_the_master(self, db: Session) -> None:
        """마스터가 비어 있어도 조회할수록 채워진다."""
        broker = MockBroker(names={"005930": "삼성전자"})
        assert symbols.get(db, "005930") is None

        quote = symbols.lookup(db, "005930", broker)

        assert quote.price == Decimal("70000")
        assert symbols.get(db, "005930").name == "삼성전자"

    def test_lookup_corrects_a_stale_name(self, db: Session) -> None:
        """증권사가 준 이름이 항상 옳다. 임포트한 CSV가 낡았어도 조회 한 번이면 교정된다."""
        broker = MockBroker(names={"005930": "삼성전자"})
        symbols.upsert(db, ticker="005930", name="낡은 이름")

        symbols.lookup(db, "005930", broker)

        assert db.get(Symbol, "005930").name == "삼성전자"

    def test_a_broker_without_a_name_does_not_erase_the_known_one(
        self, db: Session, broker: MockBroker
    ) -> None:
        symbols.upsert(db, ticker="005930", name="삼성전자")
        symbols.lookup(db, "005930", broker)
        assert db.get(Symbol, "005930").name == "삼성전자"

    def test_whitespace_is_trimmed(self, db: Session) -> None:
        broker = MockBroker(names={"005930": "삼성전자"})
        symbols.lookup(db, "  005930 ", broker)
        assert symbols.get(db, "005930") is not None


class TestCsvImport:
    def write(self, tmp_path: Path, text: str, *, encoding: str = "utf-8") -> Path:
        path = tmp_path / "symbols.csv"
        path.write_text(text, encoding=encoding)
        return path

    def test_imports_rows(self, db: Session, tmp_path: Path) -> None:
        path = self.write(
            tmp_path, "ticker,name,market\n005930,삼성전자,KOSPI\n000660,SK하이닉스,KOSPI\n"
        )
        result = symbols.import_csv(db, path)

        assert (result.created, result.updated) == (2, 0)
        assert db.get(Symbol, "005930").name == "삼성전자"

    def test_reimport_updates_instead_of_duplicating(self, db: Session, tmp_path: Path) -> None:
        path = self.write(tmp_path, "ticker,name,market\n005930,삼성전자,KOSPI\n")
        symbols.import_csv(db, path)
        result = symbols.import_csv(db, path)

        assert (result.created, result.updated) == (0, 1)
        assert db.query(Symbol).count() == 1

    def test_broken_rows_are_skipped_not_fatal(self, db: Session, tmp_path: Path) -> None:
        """상장 목록은 어디서 받든 빈 줄이 섞여 들어온다."""
        path = self.write(
            tmp_path, "ticker,name,market\n005930,삼성전자,KOSPI\n,이름만,KOSPI\n000660,,KOSPI\n"
        )
        result = symbols.import_csv(db, path)

        assert result.created == 1
        assert result.skipped == 2

    def test_excel_bom_is_tolerated(self, db: Session, tmp_path: Path) -> None:
        """엑셀로 저장한 CSV는 첫 컬럼 이름 앞에 BOM이 붙는다."""
        path = self.write(
            tmp_path, "ticker,name,market\n005930,삼성전자,KOSPI\n", encoding="utf-8-sig"
        )
        assert symbols.import_csv(db, path).created == 1

    def test_missing_columns_are_reported_clearly(self, db: Session, tmp_path: Path) -> None:
        path = self.write(tmp_path, "code,label\n005930,삼성전자\n")
        with pytest.raises(ValueError, match="ticker"):
            symbols.import_csv(db, path)
