# fund-polymarket

스터디 펀드 예측시장 — 스터디원 9명의 의견을 폴리마켓식 예측시장으로 모아 **매수 / 매도 /
홀딩**을 결정하고, 한국투자증권(KIS) Open API로 주문을 집행한다.

## 어떻게 동작하나

1. **주제 개설** — 운영자가 종목과 마감/판정 시각을 정해 마켓을 연다.
   (예: "삼성전자 — 이번 주 액션은?")
2. **베팅** — 스터디원 각자가 보유 포인트를 `매수/매도/홀딩`에 배분한다. 확신하면
   몰아서, 애매하면 나눠서 건다. 마감 전에는 몇 번이든 다시 낼 수 있고, 마감 전까지는
   **남의 베팅 내역이 보이지 않는다**(집계 확률만 공개).
3. **합의 확률** — 지분 비율이 그대로 확률로 표시된다. BUY에 620, SELL에 110,
   HOLD에 270이 걸리면 `BUY 62%`.
4. **매매 결정** — 마감되면 1등 결과가 매매 액션이 된다. 단 **정족수**(9명 중 6명 이상
   참여)와 **집행 기준 확률**(1등이 55% 이상)을 넘어야 하고, 못 넘으면 SKIP한다.
5. **승인 · 집행** — 리스크 가드를 통과한 주문만 브로커로 나간다. 승인은 **항상 사람이**
   누른다. 자동 집행은 없다. 접수된 주문은 증권사에 체결 여부를 다시 물어서
   체결 수량과 평균가를 채운다 — "냈다"와 "체결됐다"는 다른 사건이다.
6. **판정 · 정산** — 판정 시각의 가격을 기준가와 비교해 정답을 가린다
   (기본: +3% 이상 → 매수 정답, −3% 이하 → 매도 정답, 그 사이 → 홀딩 정답).
   정답에 건 사람들이 전체 포인트 풀을 지분대로 나눠 갖는다(파리뮤추얼).

정산이 쌓이면 스터디원별 **적중률**과 **Brier score**(확신 정도까지 반영한 정확도)가
순위표에 남는다. 몰빵해서 맞힌 것과 신중하게 맞힌 것이 구분된다.

## 빠른 시작

```bash
make setup          # venv + npm install + .env 생성
make db-up          # PostgreSQL 컨테이너
make migrate        # 스키마 적용
make seed           # 관리자 1명 + 스터디원 9명 + 예시 마켓

make dev-backend    # http://localhost:8000/docs
make dev-frontend   # http://localhost:5173
```

시드 계정은 `admin@study.local` / `member1~9@study.local`, 비밀번호는 모두
`changeme123`이다. 기본 브로커는 `mock`이라 **실제 주문이 나가지 않는다**.

## 안전장치

돈이 걸린 시스템이라 기본값은 전부 "아무 일도 일어나지 않는" 쪽이다.

| 장치 | 기본값 | 설명 |
|---|---|---|
| `BROKER_BACKEND` | `mock` | 네트워크 호출 없이 체결만 시뮬레이션 |
| `KIS_ENV` | `paper` | 모의투자 도메인 |
| `ALLOW_LIVE_TRADING` | `false` | 실계좌 마스터 스위치. `KIS_ENV=live`와 **둘 다** 참이어야 실전 접속 |
| `KILL_SWITCH` | `false` | 켜면 어떤 주문도 브로커로 나가지 않음 |
| `MAX_ORDER_AMOUNT_KRW` | 100만원 | 1회 주문금액 상한 |
| `MAX_DAILY_ORDERS` | 10 | 24시간 주문 건수 상한 |
| `MAX_POSITION_WEIGHT` | 0.30 | 단일 종목 최대 비중 |
| `ENFORCE_MARKET_HOURS` | `true` | 장 운영시간 밖 주문 사전 차단 (휴장일은 판단 못함) |
| 사람 승인 | 필수 | 스케줄러는 마감/판정/정산만 자동화하고, 주문 승인은 안 한다 |

매도 주문은 보유 수량을 넘을 수 없고, 매수는 잔고 조회가 실패하면 **차단**된다
(잔고를 모른 채로 주문을 내지 않는다).

## 실계좌로 전환하기

절대 한 번에 넘어가지 말 것. 순서대로:

1. `BROKER_BACKEND=kis`, `KIS_ENV=paper`로 모의투자에서 한 사이클(개설→베팅→집행→정산)을
   끝까지 돌려본다.
2. `backend/app/brokers/kis/constants.py`의 **실전** `tr_id` 값을 KIS 개발자센터 문서와
   대조한다. KIS는 거래ID를 종종 개편하며, 틀리면 주문이 거부된다. 필요하면
   `KIS_TR_ID_*` 환경변수로 덮어쓴다. 모의 값은 실전 값에서 규칙으로 파생되므로
   따로 확인할 필요가 없다.
3. `MAX_ORDER_AMOUNT_KRW`를 아주 작게(예: 1만원) 잡는다.
4. `KIS_ENV=live` + `ALLOW_LIVE_TRADING=true`로 **정규장 시간에** 소액 1주 주문을 내본다.
5. 확인되면 한도를 실제 운용 규모로 올린다.

UI 상단에는 현재 모드가 항상 배너로 표시된다.

## KIS 공식 툴킷 / MCP

[koreainvestment/kis-ai-extensions](https://github.com/koreainvestment/kis-ai-extensions)의
백테스팅 MCP 서버를 개발용으로 붙여뒀다(`.mcp.json`). 마켓을 열기 전에 그 아이디어가
과거에 통했는지 확인하는 용도다. **주문 집행 경로는 아니다** — 자세한 이유와 설정,
포트 충돌 주의사항은 [docs/KIS-MCP.md](docs/KIS-MCP.md) 참고.

## 구조

```
backend/
  app/
    core/       설정, 열거형, 보안, 예외
    db/         세션, Base, UTC datetime 타입
    models/     Member, Fund, Position, Market, Bet, LedgerEntry, TradeDecision, Order
    schemas/    요청/응답 스키마
    api/v1/     auth, members, markets, trading
    services/   consensus(순수 로직), market_service, execution, fills, settlement,
                risk, scoring, notifications
    brokers/    base(Protocol), mock, kis/(client, broker, constants), factory
    notifiers/  base(Protocol), noop, slack, factory
    scheduler.py
frontend/
  src/          React + TypeScript (마켓, 베팅 UI, 순위, 주문 내역)
docs/
  ARCHITECTURE.md   설계 결정과 확장 지점
```

자세한 설계 배경과 "다음에 손댈 곳"은 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 참고.

## 개발

```bash
make test    # 백엔드 테스트
make lint    # ruff + tsc
make revision m="변경 설명"   # 모델 변경 후 마이그레이션 생성
```

테스트는 SQLite로 돌아서 DB 없이 실행된다. 운영은 PostgreSQL 기준이다.
