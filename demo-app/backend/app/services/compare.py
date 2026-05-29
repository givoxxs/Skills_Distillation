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


WIN_THRESHOLD = 0.02


def _winner(original_score: float, peak_score: float) -> str:
    if peak_score - original_score >= WIN_THRESHOLD:
        return "peak"
    if original_score - peak_score >= WIN_THRESHOLD:
        return "original"
    return "tie"


def _side_payload(
    label: str, round_n: int, skill_md_round: int, eval_entry: dict
) -> dict:
    return {
        "label": label,
        "round": round_n,
        "skill_md_round": skill_md_round,
        "hybrid_score": eval_entry["hybrid_score"],
        "rule_score": eval_entry["rule_score"],
        "llm_judge_score": eval_entry["llm_judge_score"],
        "rule_checks": eval_entry["rule_checks"],
        "judge_rationale": eval_entry["judge_rationale"],
        "output": eval_entry["output"],
    }


def _replay_result(run: CompareRun) -> dict:
    if not run.test_case_id:
        raise HTTPException(status_code=500, detail="replay run missing test_case_id")
    summary = data_loader.get_summary(run.skill)
    best_round = int(summary["best_round"])
    original = data_loader.get_eval_entry(run.skill, 1, run.test_case_id)
    peak = data_loader.get_eval_entry(run.skill, best_round, run.test_case_id)
    original_score = float(original["hybrid_score"])
    peak_score = float(peak["hybrid_score"])
    return {
        "skill": run.skill,
        "test_case_id": run.test_case_id,
        "best_round": best_round,
        "winner": _winner(original_score, peak_score),
        "original": _side_payload("Original Skill", 1, 0, original),
        "peak": _side_payload("Peak Skill", best_round, best_round, peak),
    }


async def stream_replay(run_id: str) -> AsyncIterator[str]:
    run = _get_run(run_id, "replay")
    try:
        result = _replay_result(run)
        assert run.test_case_id is not None
        api_calls = data_loader.get_api_calls_for_test_case(run.skill, run.test_case_id)
        original_eval = data_loader.get_eval_entry(run.skill, 1, run.test_case_id)
        peak_eval = data_loader.get_eval_entry(
            run.skill, int(result["best_round"]), run.test_case_id
        )

        yield _event("status", {"phase": "queued"})
        yield _event(
            "log",
            {
                "side": "system",
                "tag": "system",
                "line": f"loaded compare replay for {run.skill}/{run.test_case_id}",
            },
        )

        yield _event("status", {"phase": "run_original"})
        yield _event(
            "jsonl",
            {"source": "eval_detail", "side": "original", "record": original_eval},
        )
        yield _event(
            "log",
            {
                "side": "original",
                "tag": "student",
                "line": f"round 1 output_dir={original_eval.get('output', '')}",
            },
        )

        yield _event("status", {"phase": "run_peak"})
        yield _event(
            "jsonl",
            {"source": "eval_detail", "side": "peak", "record": peak_eval},
        )
        yield _event(
            "log",
            {
                "side": "peak",
                "tag": "student",
                "line": f"round {result['best_round']} output_dir={peak_eval.get('output', '')}",
            },
        )

        yield _event("status", {"phase": "judge"})
        for row in api_calls:
            yield _event(
                "jsonl", {"source": "api_calls", "side": "judge", "record": row}
            )
        yield _event(
            "log",
            {
                "side": "judge",
                "tag": "judge",
                "line": f"winner={result['winner']} original={result['original']['hybrid_score']} peak={result['peak']['hybrid_score']}",
            },
        )
        yield _event("result", result)
        yield _event("status", {"phase": "done"})
        yield _event("complete", {"run_id": run_id})
    except Exception as e:  # noqa: BLE001
        yield _event("status", {"phase": "error"})
        yield _event(
            "log",
            {"side": "system", "tag": "error", "line": f"{type(e).__name__}: {e}"},
        )
        yield _event("complete", {"run_id": run_id})


async def stream_live(run_id: str) -> AsyncIterator[str]:
    _get_run(run_id, "live")
    yield _event("status", {"phase": "done"})
    yield _event("complete", {"run_id": run_id})
