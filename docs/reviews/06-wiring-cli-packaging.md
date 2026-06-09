# Review 06 — wiring · CLI · packaging

## 대상 파일
- `crypto_deep_research/wiring.py` — `Wiring` + `load_wiring`(env 파싱, 필수 var 검증)
- `crypto_deep_research/__main__.py` — CLI: `parse_symbol`/`render_report`/`exit_code`/`main`
- `crypto_deep_research/serve_worker.py` — worker 프로세스 엔트리(`WORKER_KIND` 분기)
- `Dockerfile`, `docker-compose.yml`, `.env.example`, `pyproject.toml`

## 대조 spec
- `phases/M0.md` AC#5(필수 env 누락 시 명확 에러, WORKER_TIMEOUT_S 기본 30), `phases/M5.md` AC#1·#5(compose 6 프로세스, AC#2 agent 무변경)
- locked decision A3(timeout env), A4(MEMORY_DIR DB), NFR#1–#4(typed, 30줄, 키 .env, 게이트)

## 리뷰 체크리스트

### ① Spec 적합성
- [x] M0 AC#5: `load_wiring`이 `WORKER_URLS`/`MCP_URL` 필수, 미설정 시 명확한 `RuntimeError`(wiring.py:23–27,30–33); `WORKER_TIMEOUT_S` 기본 30(wiring.py:38)
- [x] data-driven registry: `WORKER_URLS` 콤마 분리 → worker 추가 시 orchestrator 무변경 (wiring.py:31)
- [x] A4: `__main__`이 `MEMORY_DIR/orchestrator.db`에 episodic+longterm 결합(`__main__.py:44–45,50–52`)
- [x] A3 CLI: `exit_code`가 `status=="failed"`→1 (`__main__.py:38–39`) — `test_zero_artifact`
- [x] M5 AC#1/#5: compose가 mcp+4 worker(up) + orchestrator(oneshot, profile run) = 6 프로세스 (docker-compose.yml)
- [x] M5 AC#2: `serve_worker.py`가 `workers/` 밖 packaging 계층 — live swap이 agent 코드 무변경 (serve_worker.py docstring)

### ② 정확성/버그
- [x] `load_wiring`이 빈 URL 토큰 제거 후 비면 명확 에러 (wiring.py:31–33)
- [x] `serve_worker._BUILDERS` dict로 `WORKER_KIND`→builder 매핑, 4종 등록 (serve_worker.py:21–31)
- [x] `main`이 인자 없으면 usage + exit 2 (`__main__.py:57–59`)
- [⚠️] `parse_symbol`이 첫 alpha 토큰(stoplist 제외) 반환 → "analyze bitcoin now"→"BITCOIN"(매핑/fixture 없음) → **WC2**
- [△] `serve_worker`가 `os.environ["WORKER_KIND"]` 등 직접 KeyError 의존 — 누락 시 명확한 메시지 없이 KeyError(엔트리라 허용 범위)

### ③ 보안
- [x] 하드코딩 키 없음(grep `sk-ant`/`api_key=` 무매치); 모든 키 `.env`→env (`.env.example`, coingecko.py:49)
- [x] `.env.example`이 키 자리표시자만, "Never commit the real `.env`" 명시; 결정론 worker(orderbook/onchain) compose에 ANTHROPIC 키 미주입(최소권한) (docker-compose.yml)
- [x] Dockerfile `uv sync --frozen --no-dev`(테스트 도구 제외); TLS 가로채기 환경용 opt-in `UV_INSECURE_HOST`(기본 비활성, 정상 검증) (Dockerfile:14–20)
- [⚠️] `serve_worker`가 `0.0.0.0` bind(serve_worker.py:35), MCP도 `MCP_HOST=0.0.0.0`(compose) — A2A/MCP 엔드포인트 **무인증** → **WC3**(epic상 auth out of scope)

### ④ 테스트 커버리지
- [x] `render_report`/`exit_code`는 `test_partial`/`test_zero_artifact`에서 간접 검증
- [❌] `wiring.load_wiring`(특히 M0 AC#5 "missing var raises") 전용 테스트 없음 → **WC1**
- [❌] `parse_symbol`·`serve_worker.build_app` 전용 테스트 없음 → **WC1**

## Findings

| ID | 관점 | 심각도 | 근거 | 해결방안 |
|----|------|--------|------|----------|
| **WC1** | 테스트 커버리지 | Low | M0 AC#5("a missing var raises a clear error")는 명시적 acceptance인데 `load_wiring` 전용 테스트 없음. `parse_symbol`(CLI 핵심 파싱)·`serve_worker._BUILDERS`도 미검증 | `tests/test_wiring.py`: `WORKER_URLS`/`MCP_URL` 미설정 시 `RuntimeError`(monkeypatch.delenv), 빈 `WORKER_URLS` 에러, `WORKER_TIMEOUT_S` 기본 30. `parse_symbol` 정상/실패(`ValueError`) 단위. → verify: 신규 테스트 통과, M0 AC#5가 실제로 검증됨 |
| **WC2** | 견고성 | Low | `__main__.py:22–26` `parse_symbol`이 "bitcoin"→"BITCOIN" 반환 — CoinGecko `_SYMBOL_TO_ID`·fixture 모두 미지원 → 조용한 gap. 슬라이스는 `analyze BTC now`가 DoD라 현행 허용 | 한계 문서화(본 문서) + [02-mcp-server](./02-mcp-server.md) S3와 함께 "BTC/ETH 심볼만 지원" 명시. 코드 변경은 범위 밖. → verify: 리뷰 합의 |
| **WC3** | 보안(posture) | Low | A2A worker·MCP가 무인증으로 `0.0.0.0` 노출(serve_worker.py:35, compose `MCP_HOST`). compose 내부망/loopback 전제로는 의도된 설계이나, 네트워크 노출 시 누구나 `analyze` 호출 가능. epic "Auth ... out of scope" | 슬라이스 범위상 **수정 안 함**. 단 `docs/status/current_status.md`/본 문서에 "엔드포인트 무인증 — 신뢰 네트워크 전제, auth는 deferred"를 명문화해 운영 오해 방지. → verify: 기록 완료 |

## 수정 Todolist
- [ ] **WC1**: `tests/test_wiring.py` 추가 — `load_wiring` 필수 env 누락→RuntimeError, 기본 timeout, `parse_symbol` 정상/ValueError → verify: 신규 테스트 통과(M0 AC#5 실검증)
- [ ] **WC2**: 코드 변경 없음. "BTC/ETH만 지원" 한계 기록(본 문서 + 02) → verify: 리뷰 합의
- [ ] **WC3**: 코드 변경 없음. "엔드포인트 무인증(신뢰 네트워크 전제)" posture 명문화 → verify: 기록 완료
