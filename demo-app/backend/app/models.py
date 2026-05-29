"""Pydantic schemas matching the frontend types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    skill: Literal["docx", "internal-comms", "slack-gif-creator"]


class RunResponse(BaseModel):
    run_id: str


class HealthResponse(BaseModel):
    status: str = Field(default="ok")


class CompareReplayRequest(BaseModel):
    skill: Literal["docx", "internal-comms", "slack-gif-creator"]
    test_case_id: str


class CompareLiveRequest(BaseModel):
    skill: Literal["docx", "internal-comms", "slack-gif-creator"]
    prompt_mode: Literal["test_case", "custom"]
    test_case_id: str | None = None
    custom_prompt: str | None = None
    fixture_file: str | None = None


class CompareRunResponse(BaseModel):
    run_id: str
