"""Concrete layered-memory stores (M4) behind the M0 protocols.

``episodic`` + ``longterm`` are SQLite stores that share the single orchestrator-owned DB
file (single-writer-per-file, A4). ``working`` is the per-worker LangGraph checkpointer:
each worker owns its own DB file (A4), distinct from the orchestrator's.

[한글 설명]
이 패키지는 사람의 기억처럼 3층으로 나뉜 메모리의 "실제 저장 구현체"들을 모아 둔다.
- working = 워커가 일하는 동안만 쓰는 연습장(워커별 checkpointer DB, 워커당 파일 1개).
- episodic = "지난번 이 코인 분석" 일기장(오케스트레이터 DB).
- longterm = 관심목록 + 알게 된 사실 수첩(episodic과 같은 오케스트레이터 DB 동거).
핵심 규칙 A4: "공책 한 권당 펜을 쥔 사람은 한 명"(single-writer-per-file). 공책을 나누는
기준은 '기억의 층'이 아니라 '누가 쓰는가(writer)'다 — episodic·longterm은 쓰는 사람(오케스트레이터)이
같아 한 파일에 동거하고, working은 쓰는 사람(워커)이 4명이라 파일이 4개다. SQLite의
"여럿이 한 파일에 동시에 쓰면 충돌(database is locked)" 문제를, 규칙이 아니라 자리 배치로 제거한 것.
"""
