# KIS 공식 툴킷과 MCP 연동

[koreainvestment/kis-ai-extensions](https://github.com/koreainvestment/kis-ai-extensions)를
어떻게 쓰고, 어디까지만 쓰는지에 대한 문서다.

## 결론부터: 두 층은 대체재가 아니다

| | KIS 툴킷 (MCP) | 이 프로젝트 백엔드 |
|---|---|---|
| 실행 주체 | 사람이 띄운 Claude Code 세션 | 24시간 도는 웹 서비스 |
| 하는 일 | 전략 백테스팅, 계좌 조회, 대화형 주문 | 마켓 운영, 합의 집계, 주문 집행, 포인트 정산 |
| 의존성 | Docker + Lean 엔진 + 에이전트 CLI | PostgreSQL만 |
| 언제 쓰나 | **마켓 주제를 정할 때** | **마켓이 마감될 때** |

MCP 서버(`kis-backtest`)는 **백테스팅 전용**이다. 노출하는 툴은
`run_backtest`, `optimize_params`, `get_report`, `list_strategies` 넷뿐이고
주문 API는 없다(레포 전체에 `order-cash` 문자열이 없다 — 주문은 레포에 포함되지 않은
별도 `strategy_builder` 백엔드로 위임된다).

그래서 우리 백엔드의 집행 경로를 MCP로 대체할 수 없다. 장 마감 시각에 자동으로 도는
서비스가 에이전트 세션과 Docker에 의존하면 안 된다. 대신 **마켓을 열기 전에 그 아이디어가
과거에 통했는지 확인하는 용도**로 쓴다.

## 설정

`.mcp.json`이 저장소 루트에 있다. Claude Code가 이 디렉터리에서 열리면 자동으로 잡는다.

```json
{
  "mcpServers": {
    "kis-backtest": { "type": "http", "url": "http://127.0.0.1:3846/mcp" }
  }
}
```

백테스터 서버는 별도로 띄워야 한다:

```bash
npx @koreainvestment/kis-quant-plugin init --agent claude   # 최초 1회
bash backtester/scripts/start_mcp.sh                        # 서버 기동
```

인증은 툴킷 쪽 `/auth vps`(모의) 또는 `/auth prod`(실전)로 하며, 자격증명은
`~/KIS/config/kis_devlp.yaml`에 저장된다.

> **포트 충돌 주의.** 툴킷의 `strategy_builder` 백엔드도 **8000번**을 쓴다. 우리 백엔드와
> 같다. 둘을 동시에 띄우려면 한쪽을 옮겨라 —
> `make dev-backend` 대신 `cd backend && .venv/bin/uvicorn app.main:app --reload --port 8001`,
> 그리고 `frontend/vite.config.ts`의 프록시 target도 함께 바꾼다.

## 자격증명을 공유하지 마라

툴킷은 `~/KIS/config/kis_devlp.yaml`을 읽고, 우리 백엔드는 `.env`를 읽는다.
**같은 앱키를 양쪽에 넣지 않는 것을 권한다.** KIS는 접근토큰 발급에 유량 제한이 있어서,
두 프로세스가 같은 앱키로 각자 토큰을 받으면 서로의 토큰을 무효화하거나 발급이 막힐 수
있다. 모의투자용 앱키를 툴킷에, 운영용 앱키를 백엔드에 두는 편이 안전하다.

## 이 툴킷에서 우리 코드로 가져온 것

### 1. 거래ID 파생 규칙 (`brokers/kis/constants.py`)

`shared/scripts/api_client.py`의 `_convert_tr_id`가 공식 규칙을 담고 있다:

```python
# 모의투자 시 TR_ID 첫 글자 T/J/C → V 변환
```

원래 실전/모의 거래ID를 각각 상수로 들고 있었는데(값은 맞았다), 규칙으로 바꿨다.
이제 실전 값 하나만 관리하면 모의 값이 자동으로 따라온다. 한쪽만 고쳐서 어긋나는
사고가 구조적으로 불가능하다. 시세 조회(`FHKST01010100`)는 `F`로 시작해 변환 대상이
아니며, 이것도 규칙에 그대로 담겼다.

검증: `tests/test_kis_constants.py`

### 2. 잔고 응답 필드명 확인

`dnca_tot_amt`(예수금), `output1[].pdno / prdt_name / hldg_qty / pchs_avg_pric / prpr`.
우리 `KISBroker.get_balance` 구현과 일치함을 대조 확인했다.

### 3. 토큰 만료 필드 (`brokers/kis/client.py`)

툴킷은 `access_token_token_expired`(KST 문자열)를 쓰고, 우리는 `expires_in`(초)을 썼다.
KIS는 둘 다 준다. 이제 `expires_in`을 우선하되 없으면 KST 문자열을 파싱한다 —
타임존 해석 여지가 없는 쪽을 먼저 본다.

검증: `tests/test_kis_client.py::TestParseTokenExpiry`

### 4. 장 운영시간 (`services/market_hours.py`)

`kis-order-executor` 스킬의 표를 그대로 따랐다.

| 시간대 (KST) | 주문 유형 |
|---|---|
| 08:00 ~ 09:00 | 장 전 시간외 — 지정가만 |
| 09:00 ~ 15:30 | 정규장 — 시장가·지정가 |
| 15:40 ~ 18:00 | 장 후 시간외 — 지정가만 |

KIS API가 장외 주문을 어차피 거부하는데도 우리 쪽에서 먼저 거르는 이유는, 거부된
주문도 `orders` 행을 남기고 일일 주문 건수 한도를 갉아먹기 때문이다. 실패 로그에서
"리스크 한도"와 "장 마감"이 구분되지 않는 것도 문제다.

**휴장일(공휴일)은 판단하지 못한다.** 주말만 거른다. 최종 판단은 KIS API가 한다.
끄려면 `ENFORCE_MARKET_HOURS=false`.

검증: `tests/test_market_hours.py`

## 가져오지 않은 것

- **`kis-prod-guard.sh` 훅** — 에이전트가 `/api/orders`를 호출할 때 실전 모드를 차단하는
  PreToolUse 훅이다. 우리는 승인 API 자체가 관리자 인증 + 리스크 가드 뒤에 있어서
  같은 역할을 서버 쪽에서 이미 한다.
- **신호 강도(0~1) 기반 주문 유형 선택** — 툴킷은 강도 0.8 이상이면 시장가, 0.5~0.8이면
  지정가를 쓴다. 우리는 합의 확률이 그 역할을 하지만, 현재는 항상 지정가다.
  확률에 따라 시장가로 올리는 것은 검토해볼 만하다(`market_service.build_decision`).

## 백테스터를 실제로 쓰는 법

마켓을 열기 전에 이런 식으로 쓸 수 있다.

1. 스터디에서 "삼성전자 골든크로스 전략이 통할까?" 논의가 나온다.
2. Claude Code에서 `run_backtest`로 과거 성과를 확인한다.
3. 결과를 마켓 `description`에 붙여서 개설한다 — 스터디원이 근거를 보고 베팅한다.
4. 마감 후 합의대로 집행한다.

백테스트 결과를 마켓에 자동으로 첨부하는 연동은 아직 없다. 필요해지면
`markets.description`에 넣거나 별도 컬럼을 두면 된다.
