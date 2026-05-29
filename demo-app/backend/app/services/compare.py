from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.config import DISTILL_REPO_ROOT, TEST_CASES_DIR
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


def _known_fixture_files(skill: str) -> set[str]:
    fixtures: set[str] = set()
    for tc in data_loader.get_test_cases(skill):
        fixtures.update(tc["fixture_files"])
    return fixtures


def _resolve_fixture_path(skill: str, fixture_file: str | None) -> Path | None:
    if not fixture_file:
        return None
    known = _known_fixture_files(skill)
    if fixture_file not in known:
        raise HTTPException(status_code=404, detail=f"unknown fixture: {fixture_file}")
    path = TEST_CASES_DIR / fixture_file
    try:
        path.relative_to(TEST_CASES_DIR)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="fixture path escapes test_cases"
        ) from e
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=404, detail=f"fixture file missing: {fixture_file}"
        )
    return path


def _live_prompt(req: CompareLiveRequest) -> tuple[str, Path | None]:
    if req.prompt_mode == "test_case":
        if not req.test_case_id:
            raise HTTPException(status_code=422, detail="test_case_id is required")
        tc = data_loader.get_test_case(req.skill, req.test_case_id)
        fixture = tc["fixture_files"][0] if tc["fixture_files"] else None
        return tc["prompt"], _resolve_fixture_path(
            req.skill, req.fixture_file or fixture
        )

    prompt = (req.custom_prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="custom_prompt is required")
    return prompt, _resolve_fixture_path(req.skill, req.fixture_file)


def create_live_run(req: CompareLiveRequest) -> CompareRun:
    if not os.getenv("OPENROUTER_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="OPENROUTER_API_KEY is required for live compare mode",
        )
    _live_prompt(req)
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


def _ensure_distillation_imports() -> None:
    root = DISTILL_REPO_ROOT / "distillation_v2"
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _materialize_skill_version(skill: str, skill_round: int, parent: Path) -> Path:
    src = DISTILL_REPO_ROOT / "distillation_v2" / "skills" / skill
    if not src.is_dir():
        raise HTTPException(status_code=502, detail=f"skill source missing: {src}")
    dst = parent / f"{skill}-round-{skill_round}"
    shutil.copytree(src, dst)
    _, skill_md = data_loader.get_skill_md(skill, skill_round)
    (dst / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return dst


def _read_jsonl(path: str | Path | None) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    records: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"event": "raw", "line": line})
    return records


def _run_student_side(
    *,
    run_id: str,
    side: str,
    skill: str,
    skill_round: int,
    prompt: str,
    fixture_path: Path | None,
) -> dict:
    _ensure_distillation_imports()
    from runner.config import RunConfigV2
    from stages.student import run_student

    summary = data_loader.get_summary(skill)
    student_model = summary.get("student_model", "google/gemma-4-26b-a4b-it")
    work_root = Path(tempfile.mkdtemp(prefix=f"compare-{run_id}-{side}-"))
    skill_dir = _materialize_skill_version(skill, skill_round, work_root)
    output_dir = work_root / "outputs"
    log_dir = work_root / "logs"

    config = RunConfigV2(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_base_url="https://openrouter.ai/api",
        skills_dir=str(work_root),
        log_dir=str(log_dir),
        output_dir=str(output_dir),
        input_files=[fixture_path] if fixture_path else [],
    )
    result = run_student(
        user_prompt=prompt,
        skill_name=skill,
        skill_dir=skill_dir,
        model=student_model,
        config=config,
        max_retries=1,
    )
    return {
        "side": side,
        "skill_round": skill_round,
        "stop_reason": result.get("stop_reason", "unknown"),
        "iterations": result.get("iterations", 0),
        "duration_seconds": result.get("duration_seconds", 0.0),
        "token_usage": result.get("token_usage", {"prompt": 0, "completion": 0}),
        "output_files": result.get("output_files", []),
        "log_file": str(result.get("log_file", "")),
        "log_records": _read_jsonl(result.get("log_file")),
    }


JUDGE_MODEL = "anthropic/claude-haiku-4-5"


def _parse_judge_json(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "winner": "tie",
            "score_original": 0.0,
            "score_peak": 0.0,
            "rationale": raw[:1000],
        }
    winner = data.get("winner")
    if winner not in {"original", "peak", "tie"}:
        winner = "tie"
    return {
        "winner": winner,
        "score_original": max(0.0, min(1.0, float(data.get("score_original", 0.0)))),
        "score_peak": max(0.0, min(1.0, float(data.get("score_peak", 0.0)))),
        "rationale": str(data.get("rationale", ""))[:2000],
    }


def _preview_output_files(files: list[str]) -> list[dict]:
    previews: list[dict] = []
    for f in files:
        path = Path(f)
        item = {"path": str(path), "exists": path.exists(), "size": 0, "preview": ""}
        if path.exists():
            item["size"] = path.stat().st_size
            if path.suffix.lower() in {".txt", ".md", ".json", ".csv"}:
                item["preview"] = path.read_text(encoding="utf-8", errors="replace")[
                    :4000
                ]
        previews.append(item)
    return previews


def _judge_live(
    *,
    skill: str,
    prompt: str,
    original: dict,
    peak: dict,
    student_model: str,
) -> dict:
    _ensure_distillation_imports()
    from utils.llm_call import OPENROUTER_BASE_URL, call_llm

    system = (
        "You are judging an Arena comparison between two versions of the same agent skill. "
        "Return only JSON with keys winner, score_original, score_peak, rationale. "
        "winner must be original, peak, or tie. Scores must be numbers from 0 to 1."
    )
    user = json.dumps(
        {
            "skill": skill,
            "prompt": prompt,
            "original": {
                "skill_round": original.get("skill_round"),
                "stop_reason": original.get("stop_reason"),
                "output_files": _preview_output_files(original.get("output_files", [])),
                "token_usage": original.get("token_usage", {}),
            },
            "peak": {
                "skill_round": peak.get("skill_round"),
                "stop_reason": peak.get("stop_reason"),
                "output_files": _preview_output_files(peak.get("output_files", [])),
                "token_usage": peak.get("token_usage", {}),
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    start = time.time()
    raw, usage = call_llm(
        system=system,
        user=user,
        model=JUDGE_MODEL,
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=OPENROUTER_BASE_URL,
        max_tokens=1200,
        temperature=0,
    )
    parsed = _parse_judge_json(raw)
    parsed.update(
        {
            "judge_model": JUDGE_MODEL,
            "student_model": student_model,
            "elapsed_s": round(time.time() - start, 2),
            "judge_usage": usage,
            "original_output_files": original.get("output_files", []),
            "peak_output_files": peak.get("output_files", []),
        }
    )
    return parsed


async def stream_live(run_id: str) -> AsyncIterator[str]:
    run = _get_run(run_id, "live")
    req = run.live_request
    if req is None:
        yield _event("status", {"phase": "error"})
        yield _event(
            "log", {"side": "system", "tag": "error", "line": "live request missing"}
        )
        yield _event("complete", {"run_id": run_id})
        return

    start = time.time()
    try:
        prompt, fixture_path = _live_prompt(req)
        summary = data_loader.get_summary(req.skill)
        best_round = int(summary["best_round"])
        student_model = summary.get("student_model", "google/gemma-4-26b-a4b-it")

        yield _event("status", {"phase": "queued"})
        yield _event(
            "log", {"side": "system", "tag": "system", "line": "live compare accepted"}
        )

        yield _event("status", {"phase": "run_original"})
        original = _run_student_side(
            run_id=run_id,
            side="original",
            skill=req.skill,
            skill_round=0,
            prompt=prompt,
            fixture_path=fixture_path,
        )
        for record in original["log_records"]:
            yield _event(
                "jsonl", {"source": "runner", "side": "original", "record": record}
            )

        yield _event("status", {"phase": "run_peak"})
        peak = _run_student_side(
            run_id=run_id,
            side="peak",
            skill=req.skill,
            skill_round=best_round,
            prompt=prompt,
            fixture_path=fixture_path,
        )
        for record in peak["log_records"]:
            yield _event(
                "jsonl", {"source": "runner", "side": "peak", "record": record}
            )

        yield _event("status", {"phase": "judge"})
        result = _judge_live(
            skill=req.skill,
            prompt=prompt,
            original=original,
            peak=peak,
            student_model=student_model,
        )
        result["elapsed_s"] = round(time.time() - start, 2)
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
