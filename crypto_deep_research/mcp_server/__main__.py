"""Process entry for the MCP server: ``python -m crypto_deep_research.mcp_server``.

Env-driven for packaging (M5): ``COIN_DATA_SOURCE=coingecko`` serves ``get_ohlcv`` live,
anything else keeps all 4 tools on fixtures; ``MCP_HOST`` (e.g. ``0.0.0.0`` under compose)
sets the bind address. The fixture->live swap stays env-only (AC#2).
"""

import os

from crypto_deep_research.mcp_server.server import build_server
from crypto_deep_research.mcp_server.sources.coingecko import source_from_env

if __name__ == "__main__":
    server = build_server(source_from_env(), host=os.environ.get("MCP_HOST"))
    server.run(transport="streamable-http")
