"""A2A wire types: hand-rolled JSON-RPC 2.0 + static Agent Card (A1).

[한글 설명]
에이전트 간(A2A) 통신의 wire 포맷(주고받는 봉투 규격)을 정의한 파일.
A2A는 구글이 주도한 에이전트 간 통신 프로토콜이고 전송 형식은 JSON-RPC 2.0이다.
공식 SDK 대신 최소 JSON-RPC를 직접 구현했다(A1). 이유: 학습 목적이라 프로토콜
내부를 블랙박스로 두지 않으려 했고, 실제로 필요한 건 "요청 하나, 응답 하나,
Agent Card 하나"뿐이라 SDK가 끌고 오는 무게(스트리밍, 푸시 등)가 불필요하기 때문.
구분이 핵심: MCP = 에이전트→도구, A2A = 에이전트→에이전트. 두 경계를 절대 섞지 않는다.
"""

from typing import Literal

from pydantic import BaseModel

from crypto_deep_research.contracts.artifact import WorkerArtifact


# 팀장이 담당자에게 보내는 "업무 지시서 양식".
class TaskParams(BaseModel):
    symbol: str  # 분석 대상 코인 (예: "BTC")
    # 한 번의 분석에서 워커 4개에 병렬로 일을 시키므로, 흩어진 로그·메모리·응답을
    # "같은 실행 건"으로 묶을 사건 번호(상관관계 ID)가 필요하다.
    run_id: str
    # 지난 실행 요약을 워커에게 "선택적으로" 동봉하는 통로. None 허용 = 첫 실행/기록 없음.
    # 워커가 직접 메모리 DB를 뒤지지 않고 팀장이 필요한 만큼만 건네줘, 기록 소유권을 팀장에게
    # 집중시키고 워커를 stateless(받은 지시서만으로 일하는 상태)로 유지한다.
    episodic_seed: dict[str, str] | None = None  # last-run summary the orchestrator may pass


# JSON-RPC 2.0 표준 "요청 봉투" 그대로.
class JsonRpcRequest(BaseModel):
    # 타입이 "2.0"만 허용하는 Literal + 기본값 "2.0" → 다른 값은 거부, 안 적으면 자동 채움.
    jsonrpc: Literal["2.0"] = "2.0"
    id: str  # 요청과 응답을 짝짓는 접수 번호
    # 이 시스템의 워커가 할 줄 아는 일은 analyze 하나뿐. 닫힌 Literal로 못 박아
    # 모르는 작업 요청을 양식 검사 단계에서 차단한다(할 일이 늘면 그때 추가 — 미리 일반화 안 함).
    method: Literal["analyze"]
    params: TaskParams  # 위의 업무 지시서


# JSON-RPC 오류 통지 양식: 오류 코드 + 사람이 읽을 메시지.
class JsonRpcError(BaseModel):
    code: int
    message: str


# 워커가 돌려보내는 "회신 봉투 양식".
class JsonRpcResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str  # 요청의 접수 번호를 그대로 돌려줘 어느 요청의 답인지 짝을 맞춘다
    # JSON-RPC 규약상 회신엔 result(성과물) "아니면" error(오류) 중 하나만 채워진다(상호배타).
    # 여기가 A2와 A1이 만나는 지점: result 칸의 타입이 WorkerArtifact라서, 회신 양식 자체가
    # "워커는 증류된 요약 보고서 외엔 반환할 수 없다"를 강제한다(원시 데이터를 넣을 칸이 없음).
    result: WorkerArtifact | None = None
    # "둘 중 하나만"을 별도 검사기로 강제하지 않은 건 의도적 단순화 — 회신 생성 코드가
    # 어차피 둘 중 하나만 채우며, 일어날 수 없는 시나리오용 방어 코드는 안 짠다는 원칙.
    error: JsonRpcError | None = None


# A2A 프로토콜의 "에이전트 명함". 각 워커가 /.well-known/agent.json(웹 표준 "잘 알려진 위치")에서
# 자기소개를 내건다: 나는 누구고, 어디에 있고, 무슨 기술(예: analyze:market)을 제공하는가.
# 이 프로젝트에선 명함 내용이 정적(고정)이다 — 동적 디스커버리는 v1 범위 밖이지만,
# A2A 구성요소를 실제로 갖춰보는 것 자체가 학습 목표라서 만들어 두었다(A1의 static Agent Card).
class AgentCard(BaseModel):  # served at /.well-known/agent.json
    name: str
    description: str
    url: str
    version: str
    skills: list[str]  # e.g. ["analyze:market"]
