"""O2 storage side: ``add_facts`` dedups so repeated facts don't grow the table unbounded.

[한글 설명] long-term 메모리의 저장 계층(SqliteLongTermMemory) 단위 검증. 매 런 끝마다 fact를
add_facts로 쌓는데, 같은 fact가 반복 저장되면 테이블이 무한히 커지고 plan 신호가 노이즈로
흐려진다. O2는 호출 간/배치 내 중복을 제거(dedup)해 기억이 깔끔하게 유지되는지 보장한다.
"""

from pathlib import Path

from crypto_deep_research.memory.longterm import SqliteLongTermMemory


# 여러 번 호출에 걸쳐 같은 fact가 반복돼도 중복 저장되지 않는지(런마다 같은 사실 반복 시 무한 증식 방지).
def test_add_facts_dedups_across_calls(tmp_path: Path) -> None:
    memory = SqliteLongTermMemory(str(tmp_path / "orchestrator.db"))
    memory.add_facts("BTC", ["onchain outflow", "funding flipped"])
    memory.add_facts("BTC", ["onchain outflow", "funding flipped"])  # same run repeated
    memory.add_facts("BTC", ["onchain outflow", "new distinct fact"])
    assert sorted(memory.facts("BTC")) == sorted(
        ["funding flipped", "new distinct fact", "onchain outflow"]
    )


# 한 번의 배치 안에 중복이 들어와도 한 개로 정리되는지(같은 호출 내 dedup).
def test_add_facts_dedups_within_batch(tmp_path: Path) -> None:
    memory = SqliteLongTermMemory(str(tmp_path / "orchestrator.db"))
    memory.add_facts("BTC", ["dup", "dup", "unique"])
    assert sorted(memory.facts("BTC")) == ["dup", "unique"]
