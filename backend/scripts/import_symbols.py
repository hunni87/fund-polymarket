"""종목 마스터 임포트.

    python -m scripts.import_symbols symbols.csv

CSV 형식(헤더 필수):

    ticker,name,market
    005930,삼성전자,KOSPI
    000660,SK하이닉스,KOSPI

목록을 어디서 구하나:

- **KRX 정보데이터시스템**(data.krx.co.kr) → 상장회사 목록을 엑셀로 받아
  종목코드/종목명/시장구분 세 컬럼만 남기고 위 헤더로 저장한다.
- **KIS 종목정보 마스터**(`kospi_code.mst`, `kosdaq_code.mst`) — 고정폭 텍스트라
  파싱이 따로 필요하다. KIS 개발자센터 예제 스크립트가 CSV로 떨궈준다.
- 이미 쓰는 파이썬 패키지(pykrx 등)에서 뽑아 써도 된다.

엑셀을 거친 CSV는 BOM이 붙기 때문에 기본 인코딩을 utf-8-sig 로 읽는다.

굳이 임포트하지 않아도 서비스는 돌아간다. 관리자가 마켓 개설 화면에서 티커를
조회할 때마다 그 종목이 마스터에 쌓인다 — 다만 처음 한 번은 티커를 알아야 한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.db.session import session_scope
from app.services import symbols


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="종목 마스터 CSV 임포트")
    parser.add_argument("path", type=Path, help="ticker,name,market 헤더를 가진 CSV 경로")
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV 인코딩 (기본: utf-8-sig. 엑셀에서 저장한 CP949 파일이면 cp949)",
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"파일을 찾을 수 없습니다: {args.path}", file=sys.stderr)
        return 1

    with session_scope() as db:
        try:
            result = symbols.import_csv(db, args.path, encoding=args.encoding)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except UnicodeDecodeError:
            print(
                f"{args.encoding} 로 읽지 못했습니다. --encoding cp949 를 시도해 보세요.",
                file=sys.stderr,
            )
            return 1

    print(
        f"완료: 신규 {result.created}건, 갱신 {result.updated}건"
        + (f", 건너뜀 {result.skipped}건" if result.skipped else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
