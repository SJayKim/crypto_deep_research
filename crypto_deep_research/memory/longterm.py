"""Long-term memory: user watchlist + learned coin facts, in the orchestrator-owned SQLite DB.

Read trigger = the planner reads ``watchlist``/``facts`` to choose the worker set (M3); write
trigger = run end appends newly learned facts (``add_facts``). Shares the single orchestrator
DB file with episodic memory (single-writer-per-file, A4).
"""

import sqlite3


class SqliteLongTermMemory:
    """``LongTermMemory`` over SQLite (shares the orchestrator DB file with episodic)."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS facts (symbol TEXT NOT NULL, fact TEXT NOT NULL)"
        )
        self._conn.commit()

    def watchlist(self) -> list[str]:
        rows = self._conn.execute("SELECT symbol FROM watchlist").fetchall()
        return [str(row[0]) for row in rows]

    def facts(self, symbol: str) -> list[str]:
        rows = self._conn.execute("SELECT fact FROM facts WHERE symbol = ?", (symbol,)).fetchall()
        return [str(row[0]) for row in rows]

    def add_facts(self, symbol: str, facts: list[str]) -> None:
        known = set(self.facts(symbol))
        new_facts: list[str] = []
        for fact in facts:
            if fact not in known:
                known.add(fact)
                new_facts.append(fact)
        self._conn.executemany(
            "INSERT INTO facts (symbol, fact) VALUES (?, ?)",
            [(symbol, fact) for fact in new_facts],
        )
        self._conn.commit()
