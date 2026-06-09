"""Concrete layered-memory stores (M4) behind the M0 protocols.

``episodic`` + ``longterm`` are SQLite stores that share the single orchestrator-owned DB
file (single-writer-per-file, A4). ``working`` is the per-worker LangGraph checkpointer:
each worker owns its own DB file (A4), distinct from the orchestrator's.
"""
