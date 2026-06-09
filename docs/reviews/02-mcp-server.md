# Review 02 — mcp-server

## 대상 파일
- `crypto_deep_research/mcp_server/server.py` — FastMCP 4-tool 서버(`build_server`)
- `crypto_deep_research/mcp_server/__main__.py` — 프로세스 엔트리(env로 source/host 선택)
- `crypto_deep_research/mcp_server/sources/base.py` — `DataSource` Protocol
- `crypto_deep_research/mcp_server/sources/fixture.py` — `FixtureSource`(JSON fixture)
- `crypto_deep_research/mcp_server/sources/coingecko.py` — `CoinGeckoSource`(live get_ohlcv + 429 backoff)

## 대조 spec
- `phases/M1.md`(MCP 서버 4 tool, stateless read-only), `phases/M5.md` AC#1–#4(live swap, 429 처리, 키 .env, 6 프로세스)
- locked decision A4(MCP stateless), MCP/A2A 경계 분리, NFR#3(키 .env)

## 리뷰 체크리스트

### ① Spec 적합성
- [x] 4 tool(get_ohlcv/get_orderbook/get_news/get_onchain) 모두 등록·streamable HTTP (server.py:21–39)
- [x] stateless read-only(A4): 호출마다 source 읽고 반환, 공유 가변상태 없음 → 동시 호출 동일 결과 (`test_mcp_server::test_concurrent_calls_return_identical_data`)
- [x] M5 AC#2 live swap이 `coingecko.py` + env(`COIN_DATA_SOURCE`/`MCP_HOST`)로 국한 — `workers/`·`orchestrator/` 무변경 (`test_source_swap::test_source_from_env_swaps`)
- [x] M5 AC#4 429 → backoff 재시도 후 raise → worker data 노드가 dimension gap으로 전환 (coingecko.py:71–80, `test_persistent_429_raises_clean_error`/`test_429_surfaces_as_dimension_gap`)
- [x] DataSource Protocol로 fixture↔coingecko 치환(다형성) (base.py:12–19)

### ② 정확성/버그
- [x] `source_from_env`: `COIN_DATA_SOURCE=coingecko`만 live, 그 외 fixture (coingecko.py:83–87)
- [x] `_get_json` 재시도 로직: 비-429는 즉시 `raise_for_status`, 429만 `Retry-After`/지수백오프 후 재시도 (coingecko.py:71–80)
- [⚠️] `get_ohlcv`가 `volume=0.0` 하드코딩 — CoinGecko `/ohlc` 엔드포인트에 volume 없음(문서화됨) → **S2**
- [⚠️] `_SYMBOL_TO_ID`가 BTC/ETH만; 그 외는 `symbol.lower()` fallback → 404 가능 → **S3**

### ③ 보안
- [x] API 키 `os.environ`에서만 로드, 하드코딩 없음(grep `sk-ant`/`api_key=` 무매치) (coingecko.py:49)
- [x] 키는 demo 헤더(`x-cg-demo-api-key`)로 전송, URL 쿼리 미노출 (coingecko.py:54)
- [x] MCP는 외부 데이터를 **구조화 모델로만** 반환 → injection은 worker LLM 단계 문제(=> [04-workers](./04-workers.md) W4), MCP 자체는 read-only라 표면 적음
- [△] `MCP_HOST=0.0.0.0` 시 FastMCP의 localhost DNS-rebinding 가드 우회(server.py:17–19, 의도된 in-cluster 접근). 무인증이나 epic상 auth는 out of scope → **WC3과 동일 posture, 정보성**

### ④ 테스트 커버리지
- [x] `test_mcp_server.py`(3): 4 tool 노출·스키마·동시성
- [x] `test_source_swap.py`(5): coingecko payload 파싱, 나머지 fixture 위임, 429×2 경로, env swap
- [⚠️] `mcp_server/__main__.py`(엔트리)·`sources/base.py`(Protocol)는 전용 테스트 없음 — 엔트리/추상이라 spec상 무방

## Findings

| ID | 관점 | 심각도 | 근거 | 해결방안 |
|----|------|--------|------|----------|
| **S2** | 정확성(데이터 품질) | Low | `coingecko.py:57` `volume=0.0` 하드코딩. 현재 market `_work`은 `ts:close`만 사용(`workers/market/agent.py:32)`이라 무해하나, 향후 volume 기반 신호가 생기면 조용히 0으로 오작동 | docstring에 이미 한계 명시됨(유지). 개선 시 `/market_chart`(volume 포함) 엔드포인트로 교체하거나 volume 부재를 Evidence에 표기. **슬라이스 범위상 현행 유지 + 주석 충분** |
| **S3** | 견고성 | Low | `coingecko.py:27` `_SYMBOL_TO_ID = {"BTC","ETH"}`; 그 외 심볼은 `symbol.lower()`를 coin_id로 사용→404 가능. FixtureSource도 `btc_*.json`만 존재(다른 심볼 파일 없음→FileNotFoundError→gap) | 슬라이스는 BTC 단일(`analyze BTC now`)이 DoD라 현행 허용. 개선: 미지원 심볼에 명시적 `ValueError`로 조기 실패시켜 gap 사유를 "unknown symbol"로 분명히. **권장: 현행 유지, [06](./06-wiring-cli-packaging.md) WC2와 함께 한계 문서화** |

> S2/S3는 모두 "BTC 단일 슬라이스" DoD 안에서 의도된 한계. **코드 수정보다 한계 명문화**가 surgical.

## 수정 Todolist
- [ ] **S2/S3**: 코드 변경 없음. 한계를 `docs/status/current_status.md` 또는 본 문서로 충분히 기록(완료) → verify: 리뷰 합의
- [ ] (선택) **S3** 견고성: `CoinGeckoSource.get_ohlcv`에서 미지원 심볼 → `ValueError("unsupported symbol")` 조기 발생 시 `test_source_swap`에 단위 테스트 1개 추가 → verify: 신규 테스트 통과, gap 사유가 명확해짐
- [ ] (확인) `MCP_HOST` 바인딩/무인증 posture를 [06](./06-wiring-cli-packaging.md) WC3과 함께 "out of scope(auth)"로 일관 기록 → verify: 두 문서 일관성
