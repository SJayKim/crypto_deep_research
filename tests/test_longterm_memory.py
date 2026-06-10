"""O2 storage side: ``add_facts`` dedups so repeated facts don't grow the table unbounded."""

from pathlib import Path

from crypto_deep_research.memory.longterm import SqliteLongTermMemory


def test_add_facts_dedups_across_calls(tmp_path: Path) -> None:
    memory = SqliteLongTermMemory(str(tmp_path / "orchestrator.db"))
    memory.add_facts("BTC", ["onchain outflow", "funding flipped"])
    memory.add_facts("BTC", ["onchain outflow", "funding flipped"])  # same run repeated
    memory.add_facts("BTC", ["onchain outflow", "new distinct fact"])
    assert sorted(memory.facts("BTC")) == sorted(
        ["funding flipped", "new distinct fact", "onchain outflow"]
    )


def test_add_facts_dedups_within_batch(tmp_path: Path) -> None:
    memory = SqliteLongTermMemory(str(tmp_path / "orchestrator.db"))
    memory.add_facts("BTC", ["dup", "dup", "unique"])
    assert sorted(memory.facts("BTC")) == ["dup", "unique"]
