# Review 01 — contracts

## 대상 파일
- `crypto_deep_research/contracts/artifact.py` — `Dimension`, `Evidence`, `WorkerArtifact`(+ validator)
- `crypto_deep_research/contracts/report.py` — `DimensionGap`, `SynthesisReport`
- `crypto_deep_research/contracts/a2a.py` — `TaskParams`, `JsonRpc{Request,Response,Error}`, `AgentCard`
- `crypto_deep_research/contracts/mcp_tools.py` — OHLCV/Orderbook/News/OnchainMetrics I/O
- `crypto_deep_research/contracts/memory.py` — `RunRecord` + Working/Episodic/LongTerm protocols

## 대조 spec
- `M0-M5-vertical-slice-epic.md` lines 115–228 (**normative** Pydantic 스케치) — "Caps are normative."
- `phases/M0.md` AC#3·#4·#6, locked decisions C5/A2/TENSION-C, NFR#1(typed schema)

## 리뷰 체크리스트

### ① Spec 적합성
- [x] artifact/report/a2a/mcp_tools/memory 5개 모델이 epic normative 스케치와 **필드·캡까지 1:1 일치** (artifact.py:15–27, report.py:15–22, a2a.py:10–40, mcp_tools.py 전체, memory.py:10–30)
- [x] `WorkerArtifact` 캡: headline≤200, key_points≤5, evidence≤10, key_point당≤200 (A2) — 정확히 구현 (artifact.py:18–26)
- [x] `SynthesisReport`가 `dimensions_ok`/`dimensions_unavailable` 보유 (TENSION-C) (report.py:21–22)
- [x] C5: 단일 `contracts/` 패키지를 6개 서비스가 import — 중복 스키마 없음
- [⚠️] `WorkingMemory` protocol(note/read) 정의되나 구현체 없음 → **C2**

### ② 정확성/버그
- [x] `Evidence.value: float | str` — self-contained, 포인터 아님 (artifact.py:12)
- [x] 모든 모델 typed (NFR#1: untyped `dict` 없음). 단 `TaskParams.episodic_seed: dict[str,str] | None`는 타입 명시됨 (a2a.py:13)
- [⚠️] `SynthesisReport.evidence`에 `max_length` 캡 없음 → **C1** (단, epic line 154 스케치도 캡 없음 = spec 부합)

### ③ 보안
- [x] 계약 계층엔 외부 입력·키 없음 — 해당 위험 없음
- [x] `episodic_seed`가 `dict[str,str]`로 제한되어 임의 객체 주입 불가

### ④ 테스트 커버리지
- [x] `test_contracts.py`: `WorkerArtifact` 6-key_points/overlong-key_point/overlong-headline 거부 (M0 AC#3), `SynthesisReport` ok/partial/failed round-trip (M0 AC#4)
- [⚠️] `a2a.py`/`mcp_tools.py`/`memory.py`는 전용 테스트 없음(타 테스트에서 간접 사용). M0 AC는 artifact/report만 요구하므로 spec상 충족

## Findings

| ID | 관점 | 심각도 | 근거 | 해결방안 |
|----|------|--------|------|----------|
| **C1** | 정확성/distillation | Low | `report.py:20` `evidence: list[Evidence] = Field(default_factory=list)` — 캡 없음. `synthesize`가 worker별 evidence(최대 4×10=40)를 무제한 concat(`synthesize.py:43`). A2 distillation 정신과 약한 불일치. **단 epic normative 스케치(line 154)도 캡 미지정 → 현재 코드는 spec 부합** | spec 자체를 개선 대상으로 볼 때만 `Field(max_length=N)` 추가. 보수적으로는 **수정 안 함**(spec 일치). synthesize 쪽에서 `[:N]` 슬라이스로 방어하는 편이 surgical |
| **C2** | 정합성(dead interface) | Low | `memory.py:17–19` `WorkingMemory.note/read` protocol 정의되나 이를 구현하는 클래스 없음. 실제 working memory는 `memory/working.py`의 checkpointer 메커니즘 사용(note/read 아님). DESIGN("graph state IS the scratchpad")과는 일관되나 계약이 아무도 구현 안 하는 인터페이스를 광고 | 두 방향: (a) checkpointer 방식이 확정이면 `WorkingMemory` protocol을 제거하거나 docstring으로 "checkpointer로 대체됨" 명시, (b) note/read 의미를 살릴 거면 [05-memory](./05-memory.md) W2 수정 시 구현체 추가. **C5(계약 불변) 원칙상 M0 이후 계약 변경은 신중히** — 본 리뷰에선 docstring 명시를 권장 |

## 수정 Todolist
- [ ] **C2**: `contracts/memory.py`의 `WorkingMemory` protocol에 "구현은 checkpointer(`memory/working.py`)로 대체 — note/read는 미사용" 주석 추가 → verify: mypy clean 유지, 동작 변화 없음
- [ ] **C1**: 결정 보류 항목. [03-orchestrator](./03-orchestrator.md)의 synthesize 리뷰에서 evidence 슬라이스 방어와 함께 처리 → verify: 만약 캡 도입 시 `test_contracts.py`에 `SynthesisReport` evidence 경계 테스트 추가 후 통과
- [ ] (확인용) `a2a`/`mcp_tools` 스키마가 현재 코드와 epic 스케치에서 drift 없는지 최종 diff → verify: 육안 대조 완료(현재 일치)
