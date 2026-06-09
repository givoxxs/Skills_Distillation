"""compare.py — replay + live side-by-side arena compare service.

exports: create_replay_run, create_live_run, stream_replay, stream_live,
         serve_replay_artifact, serve_live_artifact
used_by: app/routes/compare.py -> all endpoints
rules:   OPENROUTER_API_KEY must be set in env for live mode (checked in
         create_live_run); student subprocess uses ANTHROPIC_API_KEY=<or_key>
         + ANTHROPIC_BASE_URL=https://openrouter.ai/api (Anthropic SDK appends /v1)
agent:   claude-sonnet-4-6 | anthropic | 2026-06-09 | feat/arena-compare | add server-level logging for student/judge failures
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.config import DISTILL_REPO_ROOT, TEST_CASES_DIR
from app.models import CompareLiveRequest
from app.services import data_loader

_log = logging.getLogger("app.compare")


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


_SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _safe_file(name: str) -> str:
    if not name or not _SAFE_FILE.match(name) or ".." in name:
        raise HTTPException(status_code=400, detail=f"bad file name: {name}")
    return name


def _serve_file(path: Path, *, download: bool = False):
    from fastapi.responses import FileResponse

    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {path.name}")
    suffix = path.suffix.lower()
    media = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json",
        ".csv": "text/csv; charset=utf-8",
        ".html": "text/html; charset=utf-8",
    }.get(suffix, "application/octet-stream")
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type=media,
        headers={"Content-Disposition": f'{disposition}; filename="{path.name}"'},
    )


# Serialize soffice (LibreOffice) conversions. When the result renders, BOTH
# arena columns' PDF iframes request document.pdf at once → two concurrent
# soffice processes race on LibreOffice's shared state and one fails. A single
# lock makes conversions one-at-a-time (each is ~1s, so latency is fine).
_SOFFICE_LOCK = threading.Lock()


def _pdf_cache_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "compare-pdf-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_replay_pdf(skill: str, round_n: int, batch: int, test_case_id: str) -> Path:
    """Convert the stable .docx for one replay side to PDF, cached OUTSIDE stable.

    Conversion runs in a temp dir so soffice never writes into the read-only
    STABLE_DIR (it emits the intermediate .pdf next to its input).
    """
    _ensure_distillation_imports()
    from utils.converter import docx_to_pdf, find_docx

    cache = _pdf_cache_dir() / f"{skill}_r{round_n}_b{batch}_{test_case_id}.pdf"
    if cache.is_file():
        return cache
    art_dir = data_loader.get_artifact_dir(skill, round_n, batch, test_case_id)
    docx = find_docx(art_dir)
    if docx is None:
        raise HTTPException(status_code=404, detail="no .docx to render for this case")
    with _SOFFICE_LOCK:
        if cache.is_file():  # a concurrent request just produced it
            return cache
        with tempfile.TemporaryDirectory(prefix="compare-pdf-") as tmp:
            tmp_docx = Path(tmp) / docx.name
            shutil.copy2(docx, tmp_docx)
            pdf = docx_to_pdf(tmp_docx)
            if pdf is None:
                raise HTTPException(
                    status_code=502, detail="docx→pdf conversion failed"
                )
            shutil.copyfile(pdf, cache)
    return cache


def serve_replay_artifact(
    skill: str, round_n: int, batch: int, test_case_id: str, file: str
):
    fname = _safe_file(file)  # blocks "/" and ".." → 400 before any disk access
    if fname == "document.pdf":
        return _serve_file(_ensure_replay_pdf(skill, round_n, batch, test_case_id))
    art_dir = data_loader.get_artifact_dir(skill, round_n, batch, test_case_id)
    target = (art_dir / fname).resolve()
    try:
        target.relative_to(art_dir.resolve())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path escapes artifact dir") from e
    return _serve_file(target, download=fname.lower().endswith(".docx"))


def _ensure_live_pdf(out_dir: Path) -> Path:
    """Render the live side's output .docx → PDF on demand, cached as
    out_dir/_compare_view.pdf.

    Converts in an ISOLATED temp dir and caches under a DEDICATED name so it
    never collides with the judge's transient PDF: the judge renders the docx
    via docx_to_images, which writes <docx_stem>.pdf next to the docx and then
    DELETES it. If the view served a <docx_stem>.pdf in the same dir, that
    delete could remove the file mid-response (FileNotFoundError → 500).
    """
    _ensure_distillation_imports()
    from utils.converter import docx_to_pdf, find_docx

    docx = find_docx(out_dir)
    if docx is None:
        raise HTTPException(status_code=404, detail="no .docx to render for this side")
    cached = out_dir / "_compare_view.pdf"
    if cached.is_file():
        return cached
    with _SOFFICE_LOCK:
        if cached.is_file():  # a concurrent request just produced it
            return cached
        with tempfile.TemporaryDirectory(prefix="compare-livepdf-") as tmp:
            tmp_docx = Path(tmp) / docx.name
            shutil.copy2(docx, tmp_docx)
            pdf = docx_to_pdf(tmp_docx)
            if pdf is None:
                raise HTTPException(
                    status_code=502, detail="docx→pdf conversion failed"
                )
            shutil.copyfile(pdf, cached)
    return cached


def serve_live_artifact(run_id: str, side: str, file: str):
    # Resolve from the deterministic on-disk path (live_runs/<run_id>/<side>/outputs)
    # rather than the in-memory run registry, so artifacts stay viewable even after
    # the backend reloads/restarts (e.g. uvicorn --reload), which clears _runs.
    if side not in {"original", "peak"} or not re.fullmatch(
        r"[0-9A-Za-z]+", run_id or ""
    ):
        raise HTTPException(status_code=404, detail="run not found")
    base = (_LIVE_RUNS_DIR / run_id / side / "outputs").resolve()
    if not base.is_dir():
        raise HTTPException(status_code=404, detail="run outputs not found")
    fname = _safe_file(file)
    if fname == "document.pdf":
        return _serve_file(_ensure_live_pdf(base))
    target = (base / fname).resolve()
    try:
        target.relative_to(base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path escapes output dir") from e
    return _serve_file(target, download=fname.lower().endswith(".docx"))


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


_VIEW_TEXT_EXT = {".md", ".txt", ".json", ".csv", ".html", ".xml", ".log"}
_VIEW_IMG_EXT = {".png", ".gif", ".jpg", ".jpeg", ".webp"}


def _list_artifacts(side: str, files_dir: Path, base_url: str) -> list[dict]:
    """List every viewable file in files_dir as an artifact (shared by replay +
    live). `base_url` is the artifact-endpoint prefix; `&file=<name>` is appended.

    - .docx → a PDF iframe (document.pdf sentinel) + a download link
    - images (.png/.gif/.jpg/...) → inline
    - text (.md/.txt/.json/.csv/.html/...) → inline content

    Skips dirs (e.g. venv/) and byproducts (page_*.png judge renders,
    _compare_view.pdf). The real deliverable (output.*) sorts before
    agent_final.md (the agent's closing note)."""
    if not files_dir.is_dir():
        return []
    _ensure_distillation_imports()
    from utils.converter import find_docx

    out: list[dict] = []
    docx = find_docx(files_dir)
    if docx is not None:
        out.append(
            {
                "side": side,
                "kind": "pdf",
                "label": docx.name,
                "url": f"{base_url}&file=document.pdf",
            }
        )
    files = sorted(
        (p for p in files_dir.iterdir() if p.is_file()),
        key=lambda p: (p.name == "agent_final.md", p.name),
    )
    for p in files:
        name, ext = p.name, p.suffix.lower()
        if name == "_compare_view.pdf" or (ext == ".png" and name.startswith("page_")):
            continue
        if ext == ".docx":
            out.append(
                {
                    "side": side,
                    "kind": "docx",
                    "label": name,
                    "url": f"{base_url}&file={name}",
                }
            )
        elif ext in _VIEW_IMG_EXT:
            out.append(
                {
                    "side": side,
                    "kind": "image",
                    "label": name,
                    "url": f"{base_url}&file={name}",
                }
            )
        elif ext in _VIEW_TEXT_EXT:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")[:8000]
            except OSError:
                continue
            out.append({"side": side, "kind": "text", "label": name, "text": text})
    return out


def _replay_artifacts(
    skill: str, side: str, round_n: int, batch: int, test_case_id: str
) -> list[dict]:
    """List artifacts for one replay side from its stable files."""
    try:
        art_dir = data_loader.get_artifact_dir(skill, round_n, batch, test_case_id)
    except HTTPException:
        return []
    base = (
        f"/api/compare/{skill}/artifact?round={round_n}&batch={batch}&tc={test_case_id}"
    )
    return _list_artifacts(side, art_dir, base)


async def stream_replay(run_id: str) -> AsyncIterator[str]:
    run = _get_run(run_id, "replay")
    try:
        result = _replay_result(run)
        assert run.test_case_id is not None
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
                "line": f"loaded replay {run.skill}/{run.test_case_id}",
            },
        )

        yield _event("status", {"phase": "run_original"})
        for art in _replay_artifacts(
            run.skill, "original", 1, int(original_eval["batch"]), run.test_case_id
        ):
            yield _event("artifact", art)

        yield _event("status", {"phase": "run_peak"})
        for art in _replay_artifacts(
            run.skill,
            "peak",
            int(result["best_round"]),
            int(peak_eval["batch"]),
            run.test_case_id,
        ):
            yield _event("artifact", art)

        yield _event("status", {"phase": "judge"})
        yield _event(
            "log",
            {
                "side": "judge",
                "tag": "judge",
                "line": f"winner={result['winner']} "
                f"original={result['original']['hybrid_score']} "
                f"peak={result['peak']['hybrid_score']}",
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


def _newest_jsonl(log_dir: Path) -> Path | None:
    files = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _norm_step(side: str, ev: dict) -> dict:
    return {
        "side": side,
        "kind": ev.get("event", "log"),
        "iteration": ev.get("iteration"),
        "tool": ev.get("tool"),
        "args": ev.get("args"),
        "result": ev.get("result"),
        "text": ev.get("text"),
        "stop_reason": ev.get("stop_reason"),
        "duration_seconds": ev.get("duration_seconds"),
        "tokens": ev.get("tokens"),
        "ts": ev.get("ts"),
    }


# Live runs persist here (logs + outputs) so they can be inspected manually:
#   demo-app/live_runs/<run_id>/<side>/{logs,outputs}/
# MUST live OUTSIDE demo-app/backend/ — uvicorn --reload watches that dir, and
# materialising a skill copies its scripts/*.py here, which would otherwise
# trigger a reload mid-run and wipe the in-memory run registry (run_id not found).
_LIVE_RUNS_DIR = Path(__file__).resolve().parents[3] / "live_runs"

# Cached compare rubrics (one teacher-generated rubric per skill+workflow). Kept
# outside backend/ for the same reason as live_runs. First live run per
# (skill, workflow) generates it; later runs hit the cache.
_RUBRIC_CACHE_DIR = Path(__file__).resolve().parents[3] / ".rubric_cache"


async def _run_student_side_streaming(
    *,
    run_id: str,
    side: str,
    skill: str,
    skill_round: int,
    prompt: str,
    fixture_path: Path | None,
):
    """Async generator. Yields raw student log-event dicts as they are written,
    then finally yields {"__result__": <side summary>}."""
    _ensure_distillation_imports()
    from runner.config import RunConfigV2
    from stages.student import run_student

    summary = data_loader.get_summary(skill)
    student_model = summary.get("student_model", "google/gemma-4-26b-a4b-it")
    work_root = _LIVE_RUNS_DIR / run_id / side
    work_root.mkdir(parents=True, exist_ok=True)
    skill_dir = _materialize_skill_version(skill, skill_round, work_root)
    output_dir = work_root / "outputs"
    log_dir = work_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    config = RunConfigV2(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_base_url="https://openrouter.ai/api",
        skills_dir=str(work_root),
        log_dir=str(log_dir),
        output_dir=str(output_dir),
        input_files=[fixture_path] if fixture_path else [],
    )

    box: dict = {}

    def _worker():
        try:
            box["result"] = run_student(
                user_prompt=prompt,
                skill_name=skill,
                skill_dir=skill_dir,
                model=student_model,
                config=config,
                max_retries=1,
            )
        except Exception as e:  # noqa: BLE001
            box["result"] = {"stop_reason": f"runner_error: {type(e).__name__}"}

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    log_path: Path | None = None
    emitted = 0
    while True:
        if log_path is None:
            log_path = _newest_jsonl(log_dir)
        if log_path and log_path.exists():
            complete = log_path.read_text(encoding="utf-8").split("\n")[:-1]
            while emitted < len(complete):
                raw = complete[emitted].strip()
                emitted += 1
                if raw:
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        pass
        if not thread.is_alive():
            if log_path and log_path.exists():
                for raw in log_path.read_text(encoding="utf-8").split("\n")[emitted:]:
                    raw = raw.strip()
                    if raw:
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            pass
            break
        await asyncio.sleep(0.3)

    result = box.get("result", {})
    yield {
        "__result__": {
            "side": side,
            "skill_round": skill_round,
            "stop_reason": result.get("stop_reason", "unknown"),
            "iterations": result.get("iterations", 0),
            "duration_seconds": result.get("duration_seconds", 0.0),
            "token_usage": result.get("token_usage", {"prompt": 0, "completion": 0}),
            "output_files": result.get("output_files", []),
            "output_dir": str(output_dir),
            "log_file": str(result.get("log_file", "")),
        }
    }


def _live_artifacts(run_id: str, side: str, summ: dict) -> list[dict]:
    """List all viewable output files this live side produced (shared logic)."""
    out_dir = Path(summ["output_dir"])
    base = f"/api/compare/artifact?run_id={run_id}&side={side}"
    return _list_artifacts(side, out_dir, base)


JUDGE_MODEL = "anthropic/claude-haiku-4-5"


def _parse_judge_json(raw: str) -> dict:
    def _coerce(s: str) -> dict | None:
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None

    # Models often wrap the JSON in ```json ... ``` fences or surrounding prose.
    data = _coerce(raw)
    if data is None:
        text = raw.strip()
        if text.startswith("```"):
            inner = text[3:]
            if inner[:4].lower() == "json":
                inner = inner[4:]
            data = _coerce(inner.rsplit("```", 1)[0].strip())
    if data is None:
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            data = _coerce(raw[start : end + 1])
    if data is None:
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


def _render_side_images(summ: dict) -> list[Path]:
    """Render the side's output .docx → PNG pages (empty list on any failure)."""
    out_dir = summ.get("output_dir")
    if not out_dir:
        return []
    _ensure_distillation_imports()
    from utils.converter import docx_to_images, find_docx

    docx = find_docx(Path(out_dir)) if Path(out_dir).is_dir() else None
    if docx is None:
        return []
    return docx_to_images(docx, max_pages=3)


def _image_block(png: Path) -> dict | None:
    try:
        data = base64.standard_b64encode(png.read_bytes()).decode()
    except OSError:
        return None
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": data},
    }


def _side_text_summary(label: str, summ: dict) -> str:
    return (
        f"### {label}\n"
        f"skill_round={summ.get('skill_round')} stop_reason={summ.get('stop_reason')} "
        f"output_files={summ.get('output_files', [])}\n"
    )


def _build_judge_content(
    *, skill: str, prompt: str, original: dict, peak: dict
) -> list[dict]:
    """Build the judge `user` content blocks: text instructions + (images | text preview)."""
    blocks: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Skill: {skill}\nTask prompt:\n{prompt}\n\n"
                "Compare side A (original) vs side B (peak). "
                "Below are each side's rendered output pages (or text summary)."
            ),
        }
    ]
    for label, summ in [("A · original", original), ("B · peak", peak)]:
        blocks.append({"type": "text", "text": _side_text_summary(label, summ)})
        images = _render_side_images(summ)
        if images:
            for png in images:
                b = _image_block(png)
                if b:
                    blocks.append(b)
        else:
            for f in summ.get("output_files", []):
                p = Path(f)
                if p.suffix.lower() in {".txt", ".json", ".md", ".csv"} and p.is_file():
                    blocks.append(
                        {
                            "type": "text",
                            "text": f"{label} output {p.name}:\n"
                            f"{p.read_text(encoding='utf-8', errors='replace')[:3000]}",
                        }
                    )
    return blocks


def _judge_live_headtohead(
    *, skill: str, prompt: str, original: dict, peak: dict, student_model: str
) -> dict:
    """Quick single-call head-to-head judge (used for custom prompts that have
    no rubric, and as a fallback if rubric scoring fails)."""
    _ensure_distillation_imports()
    from utils.llm_call import OPENROUTER_BASE_URL, call_llm

    system = (
        "You are judging an Arena comparison between two versions of the same agent skill. "
        "Return ONLY JSON with keys winner, score_original, score_peak, rationale. "
        "winner is original|peak|tie; scores are numbers 0..1."
    )
    content = _build_judge_content(
        skill=skill, prompt=prompt, original=original, peak=peak
    )
    start = time.time()
    raw, usage = call_llm(
        system=system,
        user=content,
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


def _rubric_side_payload(
    label: str, round_n: int, skill_md_round: int, er, output_dir: str
) -> dict:
    """Build a replay-shaped side payload from a pipeline EvalResult so the
    frontend ArenaColumn renders per-rubric checks identically to replay."""
    checks = [
        {
            "name": c.name,
            "passed": bool(c.passed),
            "score": round(float(c.score), 3),
            "reason": c.reason,
        }
        for c in er.checks
    ]
    rule = sum(float(c.score) for c in er.checks) / len(er.checks) if er.checks else 0.0
    judge = (
        float(er.llm_judge_score)
        if er.llm_judge_score is not None and er.llm_judge_score >= 0
        else None
    )
    hybrid = rule if judge is None else 0.8 * rule + 0.2 * judge
    return {
        "label": label,
        "round": round_n,
        "skill_md_round": skill_md_round,
        "hybrid_score": round(hybrid, 4),
        "rule_score": round(rule, 4),
        "llm_judge_score": None if judge is None else round(judge, 4),
        "rule_checks": checks,
        "judge_rationale": er.llm_judge_reasoning,
        "output": output_dir,
    }


def _load_compare_rubric(
    skill: str, best_round: int, workflow: str, wf_tcs: list[dict]
) -> dict:
    """Load/generate the shared rubric for one skill+workflow (cached). Uses the
    peak SKILL.md so both sides are judged by the same task-focused rubric."""
    _ensure_distillation_imports()
    from stages.rubric_gen import generate_rubric
    from utils.llm_call import OPENROUTER_BASE_URL

    with tempfile.TemporaryDirectory(prefix="compare-rubric-") as tmp:
        skill_dir = _materialize_skill_version(skill, best_round, Path(tmp))
        return generate_rubric(
            skill_name=skill,
            skill_dir=skill_dir,
            test_cases=wf_tcs,
            workflow=workflow,
            cache_dir=str(_RUBRIC_CACHE_DIR),
            model=JUDGE_MODEL,
            anthropic_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            base_url=OPENROUTER_BASE_URL,
        )


def _judge_live_rubric(
    *,
    req: CompareLiveRequest,
    best_round: int,
    student_model: str,
    side_summaries: dict,
) -> dict:
    """Score each side independently with the pipeline rubric Judge → per-side
    checks (like replay). Raises on any failure so the caller can fall back."""
    _ensure_distillation_imports()
    from stages.judge import Judge
    from utils.llm_call import OPENROUTER_BASE_URL

    raw_cases = data_loader._get_test_cases(req.skill)
    tc = raw_cases.get(req.test_case_id or "")
    if not tc:
        raise RuntimeError(f"test case not found: {req.test_case_id}")
    workflow = tc.get("workflow") or "create"
    wf_tcs = [
        t for t in raw_cases.values() if (t.get("workflow") or "create") == workflow
    ]
    rubric = _load_compare_rubric(req.skill, best_round, workflow, wf_tcs)

    judge = Judge(
        rubric=rubric,
        model=JUDGE_MODEL,
        ensemble_n=1,
        anthropic_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=OPENROUTER_BASE_URL,
        temperature=0.0,  # deterministic live judging
    )
    tc_with_skill = {**tc, "skill": req.skill}
    fixture = _live_prompt(req)[1] if workflow == "read" else None
    input_files = [fixture] if fixture else None

    start = time.time()
    sides: dict[str, dict] = {}
    for side, skill_round in [("original", 0), ("peak", best_round)]:
        out_dir = side_summaries.get(side, {}).get("output_dir", "")
        er = judge.score(
            output_dir=out_dir,
            test_case=tc_with_skill,
            model=student_model,
            round_n=skill_round,
            input_files=input_files,
        )
        label = "Original Skill" if side == "original" else "Peak Skill"
        sides[side] = _rubric_side_payload(label, skill_round, skill_round, er, out_dir)

    o, p = sides["original"], sides["peak"]
    return {
        "skill": req.skill,
        "test_case_id": req.test_case_id,
        "best_round": best_round,
        "winner": _winner(float(o["hybrid_score"]), float(p["hybrid_score"])),
        "original": o,
        "peak": p,
        "judge_model": JUDGE_MODEL,
        "student_model": student_model,
        "elapsed_s": round(time.time() - start, 2),
        "original_output_files": side_summaries.get("original", {}).get(
            "output_files", []
        ),
        "peak_output_files": side_summaries.get("peak", {}).get("output_files", []),
    }


def _judge_live(
    *,
    req: CompareLiveRequest,
    prompt: str,
    side_summaries: dict,
    best_round: int,
    student_model: str,
) -> dict:
    # Existing test cases → rubric per-side scoring (per-criterion checks like
    # replay). Custom prompts (no rubric) or any failure → quick head-to-head.
    if req.prompt_mode == "test_case" and req.test_case_id:
        try:
            return _judge_live_rubric(
                req=req,
                best_round=best_round,
                student_model=student_model,
                side_summaries=side_summaries,
            )
        except Exception:  # noqa: BLE001
            pass
    return _judge_live_headtohead(
        skill=req.skill,
        prompt=prompt,
        original=side_summaries.get("original", {}),
        peak=side_summaries.get("peak", {}),
        student_model=student_model,
    )


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

        # Run both sides CONCURRENTLY and interleave their events as they arrive,
        # so the two arena columns fill side-by-side (not original-then-peak).
        yield _event("status", {"phase": "running"})
        yield _event("side_status", {"side": "original", "status": "running"})
        yield _event("side_status", {"side": "peak", "status": "running"})

        queue: asyncio.Queue = asyncio.Queue()

        async def _drain(side: str, skill_round: int) -> None:
            try:
                async for ev in _run_student_side_streaming(
                    run_id=run_id,
                    side=side,
                    skill=req.skill,
                    skill_round=skill_round,
                    prompt=prompt,
                    fixture_path=fixture_path,
                ):
                    await queue.put((side, ev))
            except Exception as e:  # noqa: BLE001
                await queue.put((side, {"__error__": f"{type(e).__name__}: {e}"}))
            await queue.put((side, None))

        tasks = [
            asyncio.create_task(_drain("original", 0)),
            asyncio.create_task(_drain("peak", best_round)),
        ]
        side_summaries: dict[str, dict] = {}
        try:
            remaining = len(tasks)
            while remaining > 0:
                side, ev = await queue.get()
                if ev is None:
                    remaining -= 1
                    continue
                if "__error__" in ev:
                    yield _event(
                        "log", {"side": side, "tag": "error", "line": ev["__error__"]}
                    )
                    yield _event("side_status", {"side": side, "status": "error"})
                elif "__result__" in ev:
                    summ = ev["__result__"]
                    side_summaries[side] = summ
                    for art in _live_artifacts(run_id, side, summ):
                        yield _event("artifact", art)
                    yield _event(
                        "log",
                        {
                            "side": side,
                            "tag": "system",
                            "line": f"saved to {summ['output_dir']}",
                        },
                    )
                    yield _event(
                        "side_status",
                        {
                            "side": side,
                            "status": "done",
                            "output_dir": summ["output_dir"],
                        },
                    )
                else:
                    yield _event("step", _norm_step(side, ev))
        finally:
            for t in tasks:
                t.cancel()

        for _side, _summ in side_summaries.items():
            _stop = _summ.get("stop_reason", "")
            if not _stop.startswith("end_turn"):
                _log.warning("live/%s student[%s] failed: %s", run_id[:8], _side, _stop)

        yield _event("status", {"phase": "judge"})
        try:
            result = _judge_live(
                req=req,
                prompt=prompt,
                side_summaries=side_summaries,
                best_round=best_round,
                student_model=student_model,
            )
        except Exception as judge_exc:  # noqa: BLE001
            _log.error(
                "live/%s judge failed: %s: %s",
                run_id[:8],
                type(judge_exc).__name__,
                judge_exc,
            )
            raise
        result["elapsed_s"] = round(time.time() - start, 2)
        yield _event("result", result)
        yield _event("status", {"phase": "done"})
        yield _event("complete", {"run_id": run_id})
    except Exception as e:  # noqa: BLE001
        _log.error("live/%s stream failed: %s: %s", run_id[:8], type(e).__name__, e)
        yield _event("status", {"phase": "error"})
        yield _event(
            "log",
            {"side": "system", "tag": "error", "line": f"{type(e).__name__}: {e}"},
        )
        yield _event("complete", {"run_id": run_id})
