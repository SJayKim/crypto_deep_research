"""Episodic memory: past analyses per coin, in the orchestrator-owned SQLite DB.

Read trigger = run start retrieves the most recent run for a symbol (``last_for``); write
trigger = run end stores this run (``put``). One row per run; ``last_for`` orders by ts then
insertion order so same-second runs still resolve deterministically.
"""

import sqlite3

from crypto_deep_research.contracts.memory import RunRecord
from crypto_deep_research.contracts.report import SynthesisReport


class SqliteEpisodicMemory:
    """``EpisodicMemory`` over SQLite (shares the orchestrator DB file with long-term)."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS runs "
            "(symbol TEXT NOT NULL, ts INTEGER NOT NULL, run_id TEXT NOT NULL, "
            "report TEXT NOT NULL)"
        )
        self._conn.commit()

    def last_for(self, symbol: str) -> RunRecord | None:
        row = self._conn.execute(
            "SELECT run_id, symbol, ts, report FROM runs "
            "WHERE symbol = ? ORDER BY ts DESC, rowid DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if row is None:
            return None
        return RunRecord(
            run_id=str(row[0]),
            symbol=str(row[1]),
            ts=int(row[2]),
            report=SynthesisReport.model_validate_json(str(row[3])),
        )

    def put(self, record: RunRecord) -> None:
        self._conn.execute(
            "INSERT INTO runs (symbol, ts, run_id, report) VALUES (?, ?, ?, ?)",
            (record.symbol, record.ts, record.run_id, record.report.model_dump_json()),
        )
        self._conn.commit()
