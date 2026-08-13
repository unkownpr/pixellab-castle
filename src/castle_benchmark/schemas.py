from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = "basic-survival-v1"
    seed: int = 17
    colony_count: int = Field(default=4, ge=1, le=8)


class CreateMatchResponse(BaseModel):
    match_id: str
    scenario_id: str
    controller_tokens: dict[str, str]
    admin_token: str


class SubmitActionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn: int = Field(ge=0)
    actions: list[dict[str, Any]] = Field(min_length=1, max_length=16)


class SubmissionResponse(BaseModel):
    status: Literal["pending", "resolved"]
    turn: int
    waiting_for: tuple[str, ...] = ()
    events: tuple[dict[str, Any], ...] = ()


class MatchStatusResponse(BaseModel):
    match_id: str
    scenario_id: str
    turn: int
    terminal: bool
    termination_reason: str | None
    pending_colonies: tuple[str, ...]

