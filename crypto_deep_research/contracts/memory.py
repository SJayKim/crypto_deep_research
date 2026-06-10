"""Layered-memory protocols + RunRecord (working / episodic / long-term)."""

from typing import Protocol

from pydantic import BaseModel

from crypto_deep_research.contracts.report import SynthesisReport


class RunRecord(BaseModel):
    run_id: str
    symbol: str
    ts: int
    report: SynthesisReport


class WorkingMemory(Protocol):
    """구현은 checkpointer(``memory/working.py``)로 대체 — note/read는 미사용 (C2)."""

    def note(self, run_id: str, key: str, value: str) -> None: ...  # write: worker records notes
    def read(self, run_id: str) -> dict[str, str]: ...  # read: distill node


class EpisodicMemory(Protocol):
    def last_for(self, symbol: str) -> RunRecord | None: ...  # read: run start
    def put(self, record: RunRecord) -> None: ...  # write: run end


class LongTermMemory(Protocol):
    def watchlist(self) -> list[str]: ...  # read: planner
    def facts(self, symbol: str) -> list[str]: ...  # read: planner
    def add_facts(self, symbol: str, facts: list[str]) -> None: ...  # write: run end
