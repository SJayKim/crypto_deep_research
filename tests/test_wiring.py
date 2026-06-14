"""WC1: wiring/CLI/packaging units — ``load_wiring`` env contract (M0 AC#5 "missing var
raises"), default timeout, ``parse_symbol``, and ``serve_worker.build_app``.

[한글 설명] 배선(wiring)·CLI·패키징 단위 검증. 시스템은 env 기반 정적 배선(워커 URL 목록·MCP
URL·타임아웃)으로 6개 프로세스를 연결한다(데이터 주도 레지스트리). 핵심: 필수 env가 빠지면
조용히 잘못 도는 게 아니라 즉시 RuntimeError로 '크게 실패'한다(M0 AC#5). 또 기본값 적용,
"analyze btc now"→"BTC" 같은 심볼 파싱, WORKER_KIND로 워커 프로세스를 골라 빌드하는 진입점을 확인.
설정 실수를 일찍 잡아 잘못된 구성으로 도는 사고를 막는 게 목표.
"""

import pytest
from starlette.applications import Starlette

from crypto_deep_research.__main__ import parse_symbol
from crypto_deep_research.serve_worker import build_app
from crypto_deep_research.wiring import DEFAULT_MEMORY_DIR, DEFAULT_WORKER_TIMEOUT_S, load_wiring


# 정상 배선 env를 깔아두는 헬퍼. 각 테스트는 여기서 한 변수만 지워/바꿔 그 변수의 효과를 격리 검증.
def _wiring_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_URLS", "http://w1, http://w2")
    monkeypatch.setenv("MCP_URL", "http://mcp")
    monkeypatch.delenv("WORKER_TIMEOUT_S", raising=False)
    monkeypatch.delenv("MEMORY_DIR", raising=False)


# WORKER_URLS 없으면 RuntimeError로 즉시 실패(조용한 오작동 금지, M0 AC#5).
def test_missing_worker_urls_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _wiring_env(monkeypatch)
    monkeypatch.delenv("WORKER_URLS")
    with pytest.raises(RuntimeError, match="WORKER_URLS"):
        load_wiring()


# MCP_URL 없으면 RuntimeError(필수 의존이 빠진 채 뜨지 않게).
def test_missing_mcp_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _wiring_env(monkeypatch)
    monkeypatch.delenv("MCP_URL")
    with pytest.raises(RuntimeError, match="MCP_URL"):
        load_wiring()


# 값이 공백/콤마뿐이라 실제 URL이 0개여도 실패(빈 워커 집합으로 도는 것 방지).
def test_blank_worker_urls_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _wiring_env(monkeypatch)
    monkeypatch.setenv("WORKER_URLS", " , ")
    with pytest.raises(RuntimeError, match="no URLs"):
        load_wiring()


# 콤마 구분 URL 목록을 공백 제거해 파싱하고, 미지정 시 타임아웃/메모리 경로 기본값이 적용되는지.
def test_defaults_and_url_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    _wiring_env(monkeypatch)
    wiring = load_wiring()
    assert wiring.worker_urls == ["http://w1", "http://w2"]
    assert wiring.worker_timeout_s == DEFAULT_WORKER_TIMEOUT_S
    assert wiring.memory_dir == DEFAULT_MEMORY_DIR


# "analyze btc now"에서 채움말을 건너뛰고 심볼만 골라 대문자화("BTC")하는지(CLI 입력 파싱).
def test_parse_symbol_skips_filler_and_uppercases() -> None:
    assert parse_symbol("analyze btc now") == "BTC"


# 심볼이 없는 쿼리는 ValueError로 거부(분석 대상 없이 런이 시작되지 않게).
def test_parse_symbol_without_symbol_raises() -> None:
    with pytest.raises(ValueError, match="no symbol found"):
        parse_symbol("analyze now please")


# 워커 프로세스 진입점이 WORKER_KIND env로 어떤 워커를 띄울지 골라 ASGI 앱을 만드는지(M5 패키징).
def test_build_app_wires_worker_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_KIND", "market")
    monkeypatch.setenv("MCP_URL", "http://mcp")
    monkeypatch.setenv("PUBLIC_URL", "http://public")
    assert isinstance(build_app(checkpointer=None), Starlette)
