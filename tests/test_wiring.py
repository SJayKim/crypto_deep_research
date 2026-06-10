"""WC1: wiring/CLI/packaging units — ``load_wiring`` env contract (M0 AC#5 "missing var
raises"), default timeout, ``parse_symbol``, and ``serve_worker.build_app``."""

import pytest
from starlette.applications import Starlette

from crypto_deep_research.__main__ import parse_symbol
from crypto_deep_research.serve_worker import build_app
from crypto_deep_research.wiring import DEFAULT_MEMORY_DIR, DEFAULT_WORKER_TIMEOUT_S, load_wiring


def _wiring_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_URLS", "http://w1, http://w2")
    monkeypatch.setenv("MCP_URL", "http://mcp")
    monkeypatch.delenv("WORKER_TIMEOUT_S", raising=False)
    monkeypatch.delenv("MEMORY_DIR", raising=False)


def test_missing_worker_urls_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _wiring_env(monkeypatch)
    monkeypatch.delenv("WORKER_URLS")
    with pytest.raises(RuntimeError, match="WORKER_URLS"):
        load_wiring()


def test_missing_mcp_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _wiring_env(monkeypatch)
    monkeypatch.delenv("MCP_URL")
    with pytest.raises(RuntimeError, match="MCP_URL"):
        load_wiring()


def test_blank_worker_urls_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _wiring_env(monkeypatch)
    monkeypatch.setenv("WORKER_URLS", " , ")
    with pytest.raises(RuntimeError, match="no URLs"):
        load_wiring()


def test_defaults_and_url_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    _wiring_env(monkeypatch)
    wiring = load_wiring()
    assert wiring.worker_urls == ["http://w1", "http://w2"]
    assert wiring.worker_timeout_s == DEFAULT_WORKER_TIMEOUT_S
    assert wiring.memory_dir == DEFAULT_MEMORY_DIR


def test_parse_symbol_skips_filler_and_uppercases() -> None:
    assert parse_symbol("analyze btc now") == "BTC"


def test_parse_symbol_without_symbol_raises() -> None:
    with pytest.raises(ValueError, match="no symbol found"):
        parse_symbol("analyze now please")


def test_build_app_wires_worker_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_KIND", "market")
    monkeypatch.setenv("MCP_URL", "http://mcp")
    monkeypatch.setenv("PUBLIC_URL", "http://public")
    assert isinstance(build_app(checkpointer=None), Starlette)
