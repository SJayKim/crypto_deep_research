"""A2A wire types: hand-rolled JSON-RPC 2.0 + static Agent Card (A1)."""

from typing import Literal

from pydantic import BaseModel

from crypto_deep_research.contracts.artifact import WorkerArtifact


class TaskParams(BaseModel):
    symbol: str
    run_id: str
    episodic_seed: dict[str, str] | None = None  # last-run summary the orchestrator may pass


class JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    method: Literal["analyze"]
    params: TaskParams


class JsonRpcError(BaseModel):
    code: int
    message: str


class JsonRpcResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: WorkerArtifact | None = None
    error: JsonRpcError | None = None


class AgentCard(BaseModel):  # served at /.well-known/agent.json
    name: str
    description: str
    url: str
    version: str
    skills: list[str]  # e.g. ["analyze:market"]
