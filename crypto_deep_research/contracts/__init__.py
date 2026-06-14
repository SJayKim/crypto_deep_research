"""Shared contract schemas imported by all six services (C5).

Import from the submodules directly, e.g.
``from crypto_deep_research.contracts.artifact import WorkerArtifact``.

[한글 설명]
이 패키지는 6개 서비스(오케스트레이터 1 + 워커 4 + MCP 서버 1)가 서로
주고받는 메시지의 "양식(스키마)"을 한 곳에 모아둔 단일 진실 공급원이다.
따로 돌아가는 프로그램끼리는 서로의 메모리를 볼 수 없으므로, 정해진
양식대로 포장한 메시지로만 소통하며 그 양식이 곧 시스템의 계약(contract)이 된다.
이 ``__init__.py``에는 일부러 재수출(지름길 import)을 두지 않았다.
가져오는 경로를 항상 서브모듈로 단일화해, grep 한 번으로 사용처를
빠짐없이 찾을 수 있게 하기 위함이다 (Simplicity First — 요청 없는 편의 금지).
"""
