"""CLI entry: ``python -m crypto_deep_research "analyze BTC now"``.

Parses the symbol, runs the orchestrator over the configured worker URLs, prints the
``SynthesisReport`` (surfacing any unavailable dimensions, TENSION-C), and exits non-zero
when no dimension could be analyzed (A3). Episodic + long-term memory are persisted in the
orchestrator-owned SQLite DB under ``MEMORY_DIR`` (A4), so later runs get richer.

[한글 설명]
사용자용 정문(CLI 진입점). 검은 창에 python -m crypto_deep_research "analyze BTC now"라고 치면:
질문에서 코인 심볼 뽑기 → 배선 메모 읽기 + 메모리 준비 → 오케스트레이터 1회 호출 → 결과를 화면용
글로 바꿔 출력 → 성적표(exit code) 반환. 실제 분석 로직은 전부 orchestrator/ 안에 있고, 이 파일은
의도적으로 '얇다'(정문은 안내만, 일은 건물 안에서).
- TENSION-C: 일부 차원만 성공한 실행을 화면에 [partial]/Unavailable로 드러낸다(실패가 보이게).
- A3: 4개 차원이 전부 실패하면(zero-artifact) exit code 1로 끝낸다.
- A4: episodic+long-term을 MEMORY_DIR 아래 orchestrator.db 한 파일에 저장(쓰는 사람=오케스트레이터 하나).
"""

import asyncio
import sys
from pathlib import Path

from crypto_deep_research.contracts.report import SynthesisReport
from crypto_deep_research.memory.episodic import SqliteEpisodicMemory
from crypto_deep_research.memory.longterm import SqliteLongTermMemory
from crypto_deep_research.orchestrator.app import run_orchestrator
from crypto_deep_research.wiring import load_wiring

# [한글] 자연어 질문에서 건너뛸 군말 목록. "analyze BTC now"의 analyze/now 같은 단어들.
_IGNORE = {"analyze", "now", "please", "the", "for", "me"}


# [한글] 자연어 질문에서 코인 심볼만 골라내는 '초미니 골라내기'.
#   단어로 쪼개고 → 군말 목록을 건너뛰고 → 처음 만나는 알파벳 단어를 대문자로 바꿔 "BTC"로 돌려준다.
#   왜 AI나 제대로 된 문장 분석기가 아니라 군말 목록 하나? 이번 단계 완료 기준이 "analyze BTC now"
#   한 문장이라, 이를 처리하는 최소 코드가 이것이고 그 이상은 요청받지 않은 기능이다.
#   알려진 한계(리뷰 WC2): "analyze bitcoin now" → "BITCOIN"이 되어 버린다(이름→심볼 변환표 없음).
#   MCP 샘플 데이터·CoinGecko 변환표가 BTC/ETH만 지원 → 코드 수정은 범위 밖, 한계를 문서로 남김.
#   심볼을 못 찾으면 ValueError로 멈춘다 — 빈 결과나 임의 기본 심볼로 슬그머니 진행하지 않음(조용한 실패 금지).
def parse_symbol(query: str) -> str:
    for token in query.replace(",", " ").split():
        if token.isalpha() and token.lower() not in _IGNORE:
            return token.upper()
    raise ValueError(f"no symbol found in query: {query!r}")


# [한글] 보고서 데이터를 사람이 읽는 글로 바꾼다(화면 출력 없이 글자만 돌려주는 '순수 함수' →
#   출력을 가로채는 장치 없이도 테스트 가능). 첫 줄에 헤드라인과 상태 [{status}]를 '반드시' 붙여,
#   일부만 성공했으면 [partial]이 제목 옆에 바로 보인다.
#   Unavailable: 블록(실패한 차원과 이유 나열) = 결정 TENSION-C의 CLI 쪽 구현 — 양식(contracts)에
#   실패를 적어도 화면이 안 보여주면 사용자 입장에선 여전히 조용한 실패다. 4개 중 1개만 성공한 실행이
#   눈에 띄게 partial로 표시되는지 테스트가 확인한다.
def render_report(report: SynthesisReport) -> str:
    lines = [f"{report.headline}  [{report.status}]"]
    lines += [f"  - {point}" for point in report.key_points]
    if report.dimensions_unavailable:
        lines.append("Unavailable:")
        lines += [f"  ! {gap.dimension}: {gap.reason}" for gap in report.dimensions_unavailable]
    return "\n".join(lines)


# [한글] 성적표(exit code) 점수 규칙 — 결정 A3의 마지막 조각: 결과물이 하나도 없으면(status=failed)
#   CLI가 0이 아닌 값(1)을 남긴다. 4개 차원이 전부 실패해야 1이고, 일부 성공(partial)은 0이다 —
#   부분 성공은 (화면엔 표시하되) 실패로 취급하지 않는다. 한 줄인데 함수로 뽑은 이유: 이 규칙 자체가
#   합격 조건의 대상이라 이름이 붙고 테스트가 달리는 독립 단위여야 해서.
def exit_code(report: SynthesisReport) -> int:
    return 1 if report.status == "failed" else 0


# [한글] 여기가 '조립(composition root)' — 부품(구체 구현)을 실제로 꺼내 조립하는 유일한 작업대.
#   env 메모에서 배선을 읽고, 실제 부품(SqliteEpisodicMemory/SqliteLongTermMemory)을 만들어
#   오케스트레이터에 '건네준다(주입)'. run_orchestrator는 메모리 규격(Protocol)만 알 뿐 부품이
#   SQLite제인지는 모른다 → 테스트에선 가짜 부품을 꽂을 수 있다(의존성 주입의 교과서적 배치).
async def _run(query: str) -> SynthesisReport:
    wiring = load_wiring()
    # 첫 실행 시 .memory/ 폴더가 없으면 알아서 만들고, 있으면 넘어간다(exist_ok) → 몇 번 재실행해도 안전(멱등).
    Path(wiring.memory_dir).mkdir(parents=True, exist_ok=True)
    # A4: episodic(일지)와 long-term(장기) 두 메모리가 '같은 파일' orchestrator.db를 써도 되는 이유 —
    #   "공책 한 권에 펜 잡는 사람 한 명" 규칙에서 둘의 펜잡이가 모두 오케스트레이터(같은 프로세스)다.
    #   (워커들의 체크포인터 DB는 각자 별도 파일.)
    db_path = str(Path(wiring.memory_dir) / "orchestrator.db")  # episodic + long-term (A4)
    return await run_orchestrator(
        symbol=parse_symbol(query),
        run_id="cli",
        worker_urls=wiring.worker_urls,
        longterm=SqliteLongTermMemory(db_path),
        timeout_s=float(wiring.worker_timeout_s),
        episodic=SqliteEpisodicMemory(db_path),
        # run_id="cli": CLI는 한 번에 한 건만 실행하므로 실행 번호표는 고정 글자 "cli"면 충분.
        #   고유 번호 생성기는 필요해지는 날 만든다.
    )


# [한글] 운영체제와 닿는 바깥 껍데기. 성적표(exit code) 어휘가 셋으로 갈린다:
#   2 = 사용법 오류(질문을 아예 안 줌, Unix의 오랜 관례), 1 = 분석 전체 실패(A3),
#   0 = 성공 또는 부분 성공. 사용법 안내는 stderr(오류 전용 출구)로 — stdout은 보고서만 나가는
#   통로라, 출력을 다른 프로그램에 파이프로 이어도 안내문이 섞이지 않는다.
def main(argv: list[str]) -> int:
    if not argv:
        print('usage: python -m crypto_deep_research "analyze BTC now"', file=sys.stderr)
        return 2
    # " ".join(argv): 따옴표 없이 친 세 단어(analyze BTC now)를 셸이 쪼개 넘겨도 다시 한 문장으로 합친다.
    # asyncio.run: 오케스트레이터 내부는 비동기(워커 4개에 동시에 일을 시켜야 해서)지만 CLI 자체는
    #   순서대로 도는 동기 세계 → 그 경계에서 딱 한 번 비동기 엔진(이벤트 루프)을 돌린다.
    report = asyncio.run(_run(" ".join(argv)))
    print(render_report(report))
    return exit_code(report)


# [한글] main(argv)->int를 sys.argv/sys.exit에서 분리한 덕에, 테스트는 단어 목록을 넣고 숫자만 받으면
#   끝 — 프로그램을 진짜로 띄울 필요가 없다. 이 블록은 실제 명령 실행 시에만 돈다.
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
