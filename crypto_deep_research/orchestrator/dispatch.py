"""A2A dispatch + fan-out: call workers' ``analyze`` over JSON-RPC, return artifacts.

``dispatch_one`` is the M2 single-worker call. ``fan_out`` runs the chosen worker set
concurrently with ``asyncio.gather`` over A2A (P9 -- NOT LangGraph ``Send``, which cannot
cross the process boundary). Each worker runs under a single per-worker wall-clock deadline
(A3) enforced by ``asyncio.wait_for``: a slow or unreachable worker becomes a ``DimensionGap``
instead of blocking the gather or raising. The orchestrator receives only the
``WorkerArtifact`` -- never the worker's internal context.

[한글 설명]
이 파일은 "팀장이 선택된 팀원들에게 일을 동시에 시키고 결과를 받는" 분배(dispatch) 단계다.
- dispatch_one: 워커 한 명에게 정해진 양식(JSON-RPC)으로 업무요청서를 보내고 답장을 받는다.
- fan_out: 선택된 워커들에게 asyncio.gather로 "동시에" 전화를 건다. 이것이 이 프로젝트의 핵심
  결정 P9 — LangGraph의 Send를 쓰지 않는 이유는, Send는 같은 프로세스(건물) 안에서만 일을 나눠
  주므로 별도 프로세스 + 실제 A2A 통신이라는 설계(Approach B)가 조용히 단일 사무실(Approach A)로
  붕괴하기 때문이다.
- 핵심 불변식 A3 "실패는 데이터": 느리거나 연락 안 되는 워커는 예외(비상벨)로 전체를 멈추지 않고
  DimensionGap(결손 메모)으로 바뀐다.
- 격리(A2): 팀장에게는 워커의 요약 보고(WorkerArtifact)만 올라오고, 워커 내부의 원자료는 절대
  넘어오지 않는다.
"""

import asyncio

import httpx

from crypto_deep_research.contracts.a2a import JsonRpcRequest, JsonRpcResponse, TaskParams
from crypto_deep_research.contracts.artifact import Dimension, WorkerArtifact
from crypto_deep_research.contracts.report import DimensionGap

# 기본 제한시간 30초. 타임아웃 = 답을 기다려주는 최대 시간(전화 걸고 30초 안 받으면 끊기).
# A3 결정의 "per-worker 30s timeout (env-configurable)"의 기본값 — 호출 쪽이 값을 안 주면 이게 적용된다.
DEFAULT_TIMEOUT_S = 30.0


# [기능] 워커 한 명에게 보낼 업무요청서(JSON-RPC)를 만들어 보내고, 답장(요약 보고)을 받아 돌려준다.
# [왜] M2(워커 한 명만 있던 시절)부터 있던 가장 낮은 층의 "통화 한 건" 함수. fan_out은 이걸
#      여러 개 동시에 띄우는 것뿐이다. 여기서는 실패를 예외(비상벨)로 알리고, 그 번역은 윗층이 맡는다.
async def dispatch_one(
    worker_url: str,
    symbol: str,
    run_id: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    episodic_seed: dict[str, str] | None = None,
) -> WorkerArtifact:
    # id=run_id: 요청서와 답장을 짝지을 일련번호 칸에 "이번 실행 ID"를 그대로 재사용(워커당 요청 1장이라 충분).
    # episodic_seed: 팀장이 읽어 둔 "지난 실행 요약"을 워커에게 첨부하는 쪽지 통로.
    request = JsonRpcRequest(
        id=run_id,
        method="analyze",
        params=TaskParams(symbol=symbol, run_id=run_id, episodic_seed=episodic_seed),
    )
    # 요청서를 인터넷으로 보내고 답장을 받는다. timeout은 통신 단계별(연결/읽기/쓰기) 제한시간이다.
    # 주의: 이것만으로는 "전체 30초 안에 끝"을 보장하지 못한다(O1 — 윗층 _dispatch_or_gap의 wait_for가 보완).
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        http_response = await client.post(worker_url, json=request.model_dump())
    # model_dump/model_validate = Pydantic 양식 검사기. 워커가 이상한 답을 보내도 양식에 맞는 데이터만 통과한다
    # (악의적 worker 응답도 스키마 경계 통과분만 수용 — 보안 경계).
    response = JsonRpcResponse.model_validate(http_response.json())
    # 답장은 "결과(result)" 아니면 "오류(error)" 둘 중 하나. 오류이거나 결과가 비면 예외(비상벨)를 울린다.
    # 여기서 비상벨을 울리는 건 의도된 역할 분담 — "못 받음" 메모(gap)로 번역하는 일은 윗층 _dispatch_or_gap이 맡는다.
    if response.error is not None or response.result is None:
        message = response.error.message if response.error else "empty result"
        raise RuntimeError(f"worker {worker_url} returned a JSON-RPC error: {message}")
    # 돌려주는 값은 WorkerArtifact(요약 보고). 답장 양식 자체가 모양을 보장하므로 추가 검사가 없다.
    return response.result


# [기능] dispatch_one을 감싸서, 결과를 "요약 보고(artifact) 아니면 결손 메모(gap)"로만 돌려준다.
#        함수 머리의 반환 타입 표기(WorkerArtifact | DimensionGap)가 "비상벨은 절대 바깥으로 안 샌다"는 약속을 글로 박은 것.
# [왜] 이 함수가 A3(실패 모델)의 구현체. dispatch_one은 자기가 거는 주소만 알지 그게 무슨 담당(dimension)인지
#      모르므로, "어느 항목이 빠졌는지" 메모를 쓰려면 담당 정보가 필요한 이 한 층 위에서 dimension을 들고 다닌다.
async def _dispatch_or_gap(
    dimension: Dimension,
    worker_url: str,
    symbol: str,
    run_id: str,
    timeout_s: float,
    episodic_seed: dict[str, str] | None,
) -> WorkerArtifact | DimensionGap:
    try:
        # wait_for(..., timeout_s): 리뷰 O1의 수정 결과. 통신 단계별 제한(httpx)만으로는 29초마다 한 글자씩
        # 흘리는 워커가 통화를 한없이 끌 수 있어 "워커당 30초" 약속이 깨진다. 그래서 손목시계로 재는
        # 통화 전체 마감(wall-clock deadline)을 이중으로 건다.
        return await asyncio.wait_for(
            dispatch_one(worker_url, symbol, run_id, timeout_s, episodic_seed),
            timeout_s,
        )
    # 시간 초과 계열(두 제한장치 각각의 비상벨)은 reason="timeout" 메모로 번역.
    except (TimeoutError, httpx.TimeoutException):  # wall-clock (A3) or HTTP-op timeout -> gap
        return DimensionGap(dimension=dimension, reason="timeout")
    # 그 외 모든 사고(연결 거부/답장 깨짐/양식 위반/RuntimeError...)는 reason="unreachable: <사고종류>" 메모로 번역.
    # except Exception(모든 사고 잡기)은 보통 나쁜 습관이지만 여기선 의도된 설계 — 한 워커의 비상벨이 그대로
    # 울리면 asyncio.gather가 전체를 중단시키므로, 그 가능성을 이 자리에서 원천 차단한다(never raise).
    except Exception as exc:  # unreachable / transport / bad envelope -> a gap, never raise
        return DimensionGap(dimension=dimension, reason=f"unreachable: {type(exc).__name__}")


# [기능] 계획표(담당→주소)에 적힌 워커 전부에게 동시에 전화를 건다. P9의 실체.
# [왜] 한 명씩 차례로 시키면 4명×5초=20초지만, 동시에 걸면 총 시간 ≈ 가장 느린 한 명(~5초).
#      4명 고정이 아니라 계획표에 적힌 만큼만 — 플래너가 2명을 골랐으면 2명에게만 건다.
async def fan_out(
    plan: dict[Dimension, str],
    symbol: str,
    run_id: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    episodic_seed: dict[str, str] | None = None,
) -> list[WorkerArtifact | DimensionGap]:
    """Dispatch every (dimension, url) in ``plan`` concurrently; total latency ~ slowest."""
    # 걸어야 할 통화 목록을 만들고 gather로 전부 동시에 건다. gather에 return_exceptions=True가 없는 이유:
    # 아래층 _dispatch_or_gap이 이미 모든 사고를 메모로 바꿔놨으므로 여기까지 비상벨이 올라올 일이 없다.
    tasks = [
        _dispatch_or_gap(dimension, url, symbol, run_id, timeout_s, episodic_seed)
        for dimension, url in plan.items()
    ]
    return list(await asyncio.gather(*tasks))
