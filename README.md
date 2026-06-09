# crypto_deep_research

코인 데이터를 수집·분석해 리포트를 만드는 **멀티에이전트 딥리서치 시스템**.
코인 분석은 **핑계이고**, 진짜 목적은 2026 멀티에이전트 핵심 개념 5개를 한 프로젝트에서
실제 와이어로 부딪혀 학습하는 것이다.

- **Orchestrator-Worker** — 오케스트레이터가 계획하고, 워커가 실제 일을 한다
- **Context Isolation** — 워커는 독립 프로세스 + 독립 LLM 컨텍스트
- **Distillation** — 워커는 raw 데이터가 아니라 bounded artifact만 위로 올린다
- **Layered Memory** — working / episodic / long-term 3계층
- **MCP vs A2A 분리** — 도구 경계(MCP)와 에이전트 경계(A2A)를 다른 프로토콜로

> 설계 의도는 [`docs/DESIGN.md`](docs/DESIGN.md), 코드까지 내려가는 구조도는
> [`docs/ARCHITECTURE-MAP.md`](docs/ARCHITECTURE-MAP.md)에 있다.

---

## 아키텍처 — 6개 프로세스

```
            CLI: python -m crypto_deep_research "analyze BTC now"
                              │
                    ┌─────────▼──────────┐        ┌──────────────────────┐
                    │   ORCHESTRATOR (1)  │◀──────▶│  orchestrator.db      │
                    │ plan→dispatch→synth │ memory │ episodic · long-term  │
                    └─────────┬──────────┘ (in-proc)└──────────────────────┘
                              │ A2A · JSON-RPC 2.0 · asyncio.gather fan-out
        ┌──────────┬──────────┼──────────┬──────────┐
        ▼          ▼          ▼          ▼
   market:8101  orderbook  sentiment  onchain:8104   ← WORKER (4)
    (LLM)      :8102(det)  :8103(LLM)  (det)
        └──────────┴────────── MCP · streamable HTTP ──────────┘
                              │
                    ┌─────────▼──────────┐
                    │   MCP SERVER (1)    │  :8000
                    │ get_ohlcv · orderbook
                    │ get_news · onchain  │
                    │ DataSource: Fixture | CoinGecko
                    └────────────────────┘

  orchestrator(1) + worker(4) + MCP 서버(1) = 6 프로세스
```

- **A2A** (보라 경계): 오케스트레이터 → 워커. 직접 짠 JSON-RPC 2.0 + 정적 Agent Card.
- **MCP** (초록 경계): 워커 → 코인데이터 서버. streamable HTTP.
- **핵심 불변식**: 오케스트레이터 상태에는 **증류된 artifact만** 올라온다. 워커의 raw
  OHLCV 배열은 절대 넘어오지 않는다 (Context Isolation).

---

## 요구사항

- **Python ≥ 3.12**
- **[uv](https://github.com/astral-sh/uv)** (의존성·실행 관리)
- (선택) **Docker + Compose** — 6개 프로세스를 실제 OS 경계로 띄울 때
- (선택) `ANTHROPIC_API_KEY` — LLM 워커(market, sentiment)용. 없으면 결정적 워커만 동작
- (선택) `COINGECKO_API_KEY` — `get_ohlcv`를 라이브로 쓸 때

## 설치

```bash
uv sync
```

## 설정 (.env)

```bash
cp .env.example .env   # 값 채우기
```

| 변수 | 필수 | 설명 |
|---|---|---|
| `WORKER_URLS` | ✅ | 워커 A2A URL 콤마 구분 목록. 워커 추가 = 이 목록에 URL 한 줄 (코드 수정 없음) |
| `MCP_URL` | ✅ | MCP 서버 base URL (예: `http://127.0.0.1:8000/mcp`) |
| `WORKER_TIMEOUT_S` | — | 워커별 dispatch 타임아웃, 기본 30초 |
| `MEMORY_DIR` | — | SQLite 메모리 DB 디렉터리, 기본 `.memory` |
| `COIN_DATA_SOURCE` | — | `coingecko`면 `get_ohlcv` 라이브, 그 외(기본 `fixture`)는 4툴 전부 픽스처 |
| `COINGECKO_API_KEY` | — | CoinGecko Demo/Pro 키 |
| `ANTHROPIC_API_KEY` | — | LLM 워커용 |

> ⚠️ **`.env`는 docker-compose만 자동으로 읽는다.** 로컬에서 파이썬을 직접 돌릴 때는
> 코드에 dotenv 로더가 없으므로 셸 환경변수로 직접 export 해야 한다.

`BINANCE_*`, `UPBIT_*` 키도 `.env.example`에 자리만 잡혀 있지만 **아직 코드에 연결돼
있지 않다** (현재 라이브 소스는 CoinGecko의 `get_ohlcv` 하나뿐).

---

## 실행

### A. Docker Compose — 6개 프로세스 한 번에 (권장)

```bash
docker compose up -d                      # mcp + 워커 4개 (5 서비스)
docker compose run --rm orchestrator      # 오케스트레이터 oneshot (6번째 프로세스)
docker compose down
```

Compose가 `.env`에서 `COINGECKO_API_KEY` / `ANTHROPIC_API_KEY`를 읽어 주입한다.
MCP 서버는 `COIN_DATA_SOURCE=coingecko`로 떠서 `get_ohlcv`만 라이브, 나머지 3툴은 픽스처.

> 이 머신처럼 회사 네트워크가 TLS를 가로채는 환경에서는 빌드 시 한정 escape hatch:
> ```bash
> docker compose build --build-arg UV_INSECURE_HOST="pypi.org files.pythonhosted.org"
> ```
> 기본값은 비어 있어 다른 곳에서는 정상적으로 인증서를 검증한다.

### B. 로컬 — 프로세스 개별 실행

각 프로세스를 별도 터미널에서 띄운다. 워커는 `WORKER_KIND`로 종류를 고른다.

```bash
# 1) MCP 서버 (:8000)  — 라이브로 쓰려면 COIN_DATA_SOURCE=coingecko
uv run python -m crypto_deep_research.mcp_server

# 2) 워커 4개 — 종류/포트별로 1개씩 (예: market)
WORKER_KIND=market \
MCP_URL=http://127.0.0.1:8000/mcp \
PUBLIC_URL=http://127.0.0.1:8101 \
PORT=8101 \
  uv run python -m crypto_deep_research.serve_worker
#   → orderbook:8102 / sentiment:8103 / onchain:8104 도 같은 식으로

# 3) 오케스트레이터 (CLI) — WORKER_URLS, MCP_URL 필요
WORKER_URLS=http://127.0.0.1:8101,http://127.0.0.1:8102,http://127.0.0.1:8103,http://127.0.0.1:8104 \
MCP_URL=http://127.0.0.1:8000/mcp \
  uv run python -m crypto_deep_research "analyze BTC now"
```

PowerShell이면 `VAR=값 cmd` 대신 `$env:VAR="값"`로 먼저 설정한 뒤 실행한다.

| 워커 | 포트 | 종류 |
|---|---|---|
| market | 8101 | LLM |
| orderbook | 8102 | 결정적 |
| sentiment | 8103 | LLM |
| onchain | 8104 | 결정적 |

오케스트레이터는 분석 불가 차원을 `Unavailable`로 표시하고, **어떤 차원도 분석 못 하면
exit code 1**로 끝난다 (A3).

---

## 개발

```bash
uv run pytest             # 테스트 (라이브 API 호출 없음 — 외부 응답은 mock)
uv run ruff check .       # lint
uv run ruff format .      # format
uv run mypy .             # 타입 (strict)
```

규칙: 에이전트 상태는 타입 스키마(Pydantic/TypedDict)만 사용, 테스트에서 라이브 API
호출 금지(CoinGecko/Binance/Upbit는 mock), API 키는 `.env`에서만 로드. 자세한 내용은
[`CLAUDE.md`](CLAUDE.md).

## 프로젝트 구조

```
crypto_deep_research/
  __main__.py          CLI 진입점
  wiring.py            env 기반 정적 배선 (worker URL 목록, MCP URL, 타임아웃)
  contracts/           6개 서비스가 공유하는 타입 계약 (로직 없음)
  mcp_server/          MCP 경계: 코인데이터 4툴을 streamable-HTTP로 노출
    sources/           fixture.py(JSON) · coingecko.py(라이브)
  workers/             4개 워커 에이전트. base.py = 공통 하네스
  orchestrator/        A2A 경계: plan → dispatch → synthesize
  memory/              3계층 메모리 (working / episodic / longterm)
  serve_worker.py      워커 1개 프로세스 진입점 (WORKER_KIND)
tests/                 개념별 검증 (격리/타임아웃/부분실패/메모리/소스스왑)
docs/                  DESIGN.md · ARCHITECTURE-MAP.md · specs/ · status/
Dockerfile             모든 서비스가 공유하는 단일 이미지
docker-compose.yml     6개 프로세스 패키징
```

## 알려진 한계

- **라이브 소스는 CoinGecko `get_ohlcv` 하나뿐.** orderbook/news/onchain은 픽스처.
  Binance/Upbit는 `.env.example` 자리만 있고 미연결.
- **working 메모리 계층은 구현·테스트는 됐지만 실제 런에는 미연결** (checkpointer seam은
  준비됨). `episodic_seed`도 A2A 경계까지만 도달하고 워커 추론엔 아직 미반영.
  ([ARCHITECTURE-MAP §8](docs/ARCHITECTURE-MAP.md) 참고)
- 콜드 long-term DB에서 첫 런은 market 차원만 계획한다(워치리스트/팩트가 비어 있어 정상).
  팬아웃을 넓히려면 두 번 돌리거나 워치리스트를 시드한다.
