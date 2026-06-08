# 현재 상태 (current_status)

**일시:** 2026-06-08 14:34

## 진행한 내용
- 프로젝트 초기 세팅 완료: `CLAUDE.md`(Karpathy 4원칙 verbatim + Commands/Self-Reflection/Project Context), `.gitignore`, `.env.example`(CoinGecko/Binance/Upbit/Anthropic), 보안 hook(`.claude/hooks/protect-files.ps1` + `settings.json`), `git init`.
- `/office-hours` 진행 → 구현 방향 확정.
  - 목표: **아키텍처 학습 우선** (코인 도메인은 핑계, 5개 2026 개념 학습이 핵심).
  - 첫 마일스톤: **수직 슬라이스 1개 완주** ("analyze BTC now").
  - 아키텍처: **B — 서비스 분리, 실제 MCP + 실제 A2A 와이어 프로토콜** (도메인은 stub 유지).
  - 전제 5개 합의 (도메인 stub 우선 / 분해 가능한 쿼리 / orchestrator는 raw context 안 봄 / MCP·A2A 분리 / 메모리 레이어별 트리거).
- 설계 문서 작성 + 독립 리뷰어 적용(7/10, 이슈 수정) → `docs/DESIGN.md` **APPROVED**.
- **`/plan-eng-review` 완료** (2026-06-08) → 결정 10건 + 외부 리뷰어 보정 3건 잠금.
  `docs/DESIGN.md` 의 "Locked Decisions — Eng Review" 섹션 + `TODOS.md` 생성.
  - 핵심 결정: A2A는 직접 짠 JSON-RPC / 분배는 `asyncio.gather`(Send 금지) /
    `WorkerArtifact` Pydantic 검증 + isolation 테스트 / worker별 checkpointer DB.
  - 마일스톤 보정: long-term **READ** 트리거를 M4→**M3**(fan-out)으로 당김.
  - 성공기준 보정: 부분 실패(1/4) 시 리포트에 dimension 커버리지 명시 + 테스트.

## Recommended next item
1. **M0 계약 작성**: A2A 메시지 스키마(직접 짠 JSON-RPC + 정적 Agent Card) /
   MCP 툴 스키마 / `WorkerArtifact`(검증자 포함) / 메모리 인터페이스 + 서비스 와이어링.
   먼저 repo scaffold (`uv init`, pyproject, 패키지 레이아웃, 공유 `contracts/` 패키지).
2. **M1**: market-worker + MCP fixture 서버 직접 호출 (data→reason→distill 증명).
3. 보류 항목은 `TODOS.md` 참조 (Approach C / 공식 SDK·JSON-Schema·in-proc Send 변형).
