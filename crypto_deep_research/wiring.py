"""Static service wiring read from the environment.

Service URLs are required (no silent default); WORKER_TIMEOUT_S defaults to 30 (A3).
The worker registry is a data-driven, comma-separated URL list so adding a worker
never edits orchestrator/ code.
"""

import os

from pydantic import BaseModel

DEFAULT_WORKER_TIMEOUT_S = 30
DEFAULT_MEMORY_DIR = ".memory"


class Wiring(BaseModel):
    worker_urls: list[str]
    mcp_url: str
    worker_timeout_s: int
    memory_dir: str


def _require(var: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise RuntimeError(f"required env var {var} is unset; set it in .env (see .env.example)")
    return value


def load_wiring() -> Wiring:
    worker_urls = [u.strip() for u in _require("WORKER_URLS").split(",") if u.strip()]
    if not worker_urls:
        raise RuntimeError("WORKER_URLS is set but contains no URLs")
    timeout_raw = os.environ.get("WORKER_TIMEOUT_S")
    return Wiring(
        worker_urls=worker_urls,
        mcp_url=_require("MCP_URL"),
        worker_timeout_s=int(timeout_raw) if timeout_raw else DEFAULT_WORKER_TIMEOUT_S,
        memory_dir=os.environ.get("MEMORY_DIR") or DEFAULT_MEMORY_DIR,
    )
