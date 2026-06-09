from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models import CompareLiveRequest, CompareReplayRequest, CompareRunResponse
from app.services import compare, data_loader

router = APIRouter()


@router.get("/api/compare/{skill}/cases")
def list_compare_cases(skill: str) -> list[dict]:
    return data_loader.get_test_cases(skill)


@router.get("/api/compare/{skill}/suggestions")
def list_compare_suggestions(skill: str, limit: int = 5) -> list[dict]:
    return data_loader.get_compare_suggestions(skill, limit)


@router.get("/api/compare/artifact")
def get_live_artifact(run_id: str, side: str, file: str):
    return compare.serve_live_artifact(run_id, side, file)


@router.get("/api/compare/{skill}/artifact")
def get_replay_artifact(skill: str, round: int, batch: int, tc: str, file: str):
    return compare.serve_replay_artifact(skill, round, batch, tc, file)


@router.post("/api/compare/replay", response_model=CompareRunResponse)
async def start_replay(req: CompareReplayRequest) -> CompareRunResponse:
    run = compare.create_replay_run(req.skill, req.test_case_id)
    return CompareRunResponse(run_id=run.run_id)


@router.get("/api/compare/replay/{run_id}/stream")
async def stream_replay(run_id: str):
    return StreamingResponse(
        compare.stream_replay(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/compare/live", response_model=CompareRunResponse)
async def start_live(req: CompareLiveRequest) -> CompareRunResponse:
    run = compare.create_live_run(req)
    return CompareRunResponse(run_id=run.run_id)


@router.get("/api/compare/live/{run_id}/stream")
async def stream_live(run_id: str):
    return StreamingResponse(
        compare.stream_live(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
