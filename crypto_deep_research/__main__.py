"""CLI entry: ``python -m crypto_deep_research "analyze BTC now"``.

Parses the symbol, runs the orchestrator over the configured worker URLs, prints the
``SynthesisReport`` (surfacing any unavailable dimensions, TENSION-C), and exits non-zero
when no dimension could be analyzed (A3). Episodic + long-term memory are persisted in the
orchestrator-owned SQLite DB under ``MEMORY_DIR`` (A4), so later runs get richer.
"""

import asyncio
import sys
from pathlib import Path

from crypto_deep_research.contracts.report import SynthesisReport
from crypto_deep_research.memory.episodic import SqliteEpisodicMemory
from crypto_deep_research.memory.longterm import SqliteLongTermMemory
from crypto_deep_research.orchestrator.app import run_orchestrator
from crypto_deep_research.wiring import load_wiring

_IGNORE = {"analyze", "now", "please", "the", "for", "me"}


def parse_symbol(query: str) -> str:
    for token in query.replace(",", " ").split():
        if token.isalpha() and token.lower() not in _IGNORE:
            return token.upper()
    raise ValueError(f"no symbol found in query: {query!r}")


def render_report(report: SynthesisReport) -> str:
    lines = [f"{report.headline}  [{report.status}]"]
    lines += [f"  - {point}" for point in report.key_points]
    if report.dimensions_unavailable:
        lines.append("Unavailable:")
        lines += [f"  ! {gap.dimension}: {gap.reason}" for gap in report.dimensions_unavailable]
    return "\n".join(lines)


def exit_code(report: SynthesisReport) -> int:
    return 1 if report.status == "failed" else 0


async def _run(query: str) -> SynthesisReport:
    wiring = load_wiring()
    Path(wiring.memory_dir).mkdir(parents=True, exist_ok=True)
    db_path = str(Path(wiring.memory_dir) / "orchestrator.db")  # episodic + long-term (A4)
    return await run_orchestrator(
        symbol=parse_symbol(query),
        run_id="cli",
        worker_urls=wiring.worker_urls,
        longterm=SqliteLongTermMemory(db_path),
        timeout_s=float(wiring.worker_timeout_s),
        episodic=SqliteEpisodicMemory(db_path),
    )


def main(argv: list[str]) -> int:
    if not argv:
        print('usage: python -m crypto_deep_research "analyze BTC now"', file=sys.stderr)
        return 2
    report = asyncio.run(_run(" ".join(argv)))
    print(render_report(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
