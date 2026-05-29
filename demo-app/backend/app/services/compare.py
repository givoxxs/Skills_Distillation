from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import HTTPException

from app.models import CompareLiveRequest
from app.services import data_loader


@dataclass
class CompareRun:
    run_id: str
    kind: str
    skill: str
    test_case_id: str | None = None
    live_request: CompareLiveRequest | None = None


_runs: dict[str, CompareRun] = {}


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_replay_run(skill: str, test_case_id: str) -> CompareRun:
    data_loader.get_test_case(skill, test_case_id)
    run = CompareRun(
        run_id=_new_run_id(),
        kind="replay",
        skill=skill,
        test_case_id=test_case_id,
    )
    _runs[run.run_id] = run
    return run


def create_live_run(req: CompareLiveRequest) -> CompareRun:
    if req.prompt_mode == "test_case" and not req.test_case_id:
        raise HTTPException(status_code=422, detail="test_case_id is required")
    if req.prompt_mode == "custom" and not (req.custom_prompt or "").strip():
        raise HTTPException(status_code=422, detail="custom_prompt is required")
    if req.test_case_id:
        data_loader.get_test_case(req.skill, req.test_case_id)
    run = CompareRun(
        run_id=_new_run_id(), kind="live", skill=req.skill, live_request=req
    )
    _runs[run.run_id] = run
    return run


def _get_run(run_id: str, kind: str) -> CompareRun:
    run = _runs.get(run_id)
    if not run or run.kind != kind:
        raise HTTPException(status_code=404, detail="run_id not found")
    return run


async def stream_replay(run_id: str) -> AsyncIterator[str]:
    _get_run(run_id, "replay")
    yield _event("status", {"phase": "done"})
    yield _event("complete", {"run_id": run_id})


async def stream_live(run_id: str) -> AsyncIterator[str]:
    _get_run(run_id, "live")
    yield _event("status", {"phase": "done"})
    yield _event("complete", {"run_id": run_id})
