# Arena Compare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `/compare`, an Arena-style page that compares `SKILL_round_0.md` against the selected skill's peak distilled round with both deterministic replay logs and real live API runs.

**Architecture:** Add a focused FastAPI compare module with run registries and SSE streams, then add a Next.js client page that consumes those streams. Replay mode reads `summary.json`, `eval_detail.jsonl`, and `api_calls.jsonl`; live mode runs both skill versions through the existing `distillation_v2` student runner and calls the existing OpenRouter judge path.

**Tech Stack:** FastAPI, Pydantic v2, Server-Sent Events, Next.js 16 App Router, React 19, TypeScript, Tailwind v4/global CSS tokens, existing `distillation_v2` runner utilities.

---

## File Structure

Create or modify these files:

- Create `demo-app/backend/app/routes/compare.py`
  - FastAPI endpoints for compare cases, replay run creation/streaming, live run creation/streaming.
- Create `demo-app/backend/app/services/compare.py`
  - Compare run registry, replay stream generation, live student execution wrapper, live judge call, winner logic, fixture validation.
- Modify `demo-app/backend/app/services/data_loader.py`
  - Add public helpers for test-case metadata, single eval lookup, and raw API call lookup by test case.
- Modify `demo-app/backend/app/models.py`
  - Add Pydantic request/response models for compare runs.
- Modify `demo-app/backend/app/main.py`
  - Include the compare router.
- Create `demo-app/backend/tests/test_compare_routes.py`
  - API contract and SSE tests for replay and live validation.
- Modify `demo-app/frontend/lib/types.ts`
  - Add compare case, result, log, and request types.
- Modify `demo-app/frontend/lib/api.ts`
  - Add compare fetch helpers and stream URL builders.
- Create `demo-app/frontend/app/compare/page.tsx`
  - Server shell, fetch initial skill summaries/cases.
- Create `demo-app/frontend/app/compare/compare-client.tsx`
  - Client UI, controls, SSE handling, log console, A/B result columns.
- Modify `demo-app/frontend/components/sidebar.tsx`
  - Add `Compare` navigation item.
- Modify `demo-app/frontend/app/globals.css`
  - Add small layout styles for compare controls, arena columns, and log console.

No existing route should be removed. Existing `/`, `/skills/[skill]`, `/run`, and `/about` behavior must stay unchanged.

---

### Task 1: Backend Data Loader Helpers

**Files:**
- Modify: `demo-app/backend/app/services/data_loader.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Write failing tests for compare case metadata and eval lookup**

Create `demo-app/backend/tests/test_compare_routes.py` with these initial tests:

```python
"""Tests for /api/compare routes and compare data helpers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import STABLE_DIR
from app.services import data_loader

requires_stable = pytest.mark.skipif(
    not STABLE_DIR.exists(),
    reason=f"distillation_v2 stable dir missing at {STABLE_DIR}",
)


@requires_stable
def test_compare_cases_returns_prompt_and_fixtures(client: TestClient) -> None:
    r = client.get("/api/compare/docx/cases")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) > 0
    first = body[0]
    assert {"id", "workflow", "name", "prompt", "expected_behavior", "fixture_files"} <= set(first)
    assert first["id"].startswith("tc_")
    assert isinstance(first["fixture_files"], list)


@requires_stable
def test_data_loader_get_eval_entry_returns_one_case() -> None:
    entry = data_loader.get_eval_entry("docx", round_n=1, test_case_id="tc_a01")
    assert entry["test_case_id"] == "tc_a01"
    assert entry["round"] == 1
    assert 0.0 <= entry["hybrid_score"] <= 1.0


@requires_stable
def test_data_loader_get_eval_entry_missing_case_raises_404() -> None:
    with pytest.raises(Exception) as exc:
        data_loader.get_eval_entry("docx", round_n=1, test_case_id="tc_missing")
    assert getattr(exc.value, "status_code", None) == 404
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py -q
```

Expected:

- `GET /api/compare/docx/cases` returns `404`.
- `data_loader.get_eval_entry` is not defined.

- [ ] **Step 3: Add public data helper functions**

Append these helpers to `demo-app/backend/app/services/data_loader.py`:

```python
def get_test_cases(skill: str) -> list[dict]:
    """Return UI-safe test case metadata for one skill."""
    _skill_dir(skill)  # validates known skill and stable directory
    raw = _get_test_cases(skill)
    out: list[dict] = []
    for tc_id in sorted(raw.keys()):
        tc = raw[tc_id]
        fixture_files: list[str] = []
        if tc.get("fixture_file"):
            fixture_files.append(str(tc["fixture_file"]))
        if tc.get("fixture_files"):
            fixture_files.extend(str(f) for f in tc["fixture_files"])
        out.append(
            {
                "id": tc_id,
                "workflow": tc.get("workflow") or _workflow_from_id(tc_id),
                "name": tc.get("name", tc_id),
                "prompt": tc.get("prompt", ""),
                "expected_behavior": tc.get("expected_behavior", ""),
                "fixture_files": fixture_files,
            }
        )
    return out


def get_test_case(skill: str, test_case_id: str) -> dict:
    """Return one test case metadata object or 404."""
    for tc in get_test_cases(skill):
        if tc["id"] == test_case_id:
            return tc
    raise HTTPException(
        status_code=404, detail=f"test case not found: {skill}/{test_case_id}"
    )


def get_eval_entry(skill: str, round_n: int, test_case_id: str) -> dict:
    """Return the best matching frontend-shaped eval row for one test case."""
    matches = [
        e
        for e in get_eval_detail(skill, round_n)
        if e.get("test_case_id") == test_case_id
    ]
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"eval entry not found: {skill} round {round_n} {test_case_id}",
        )
    return max(matches, key=lambda e: float(e.get("hybrid_score", 0.0)))


def get_api_calls_for_test_case(skill: str, test_case_id: str) -> list[dict]:
    """Return raw api_calls rows related to one test case."""
    rows = get_api_calls(skill)
    return [r for r in rows if r.get("test_case") == test_case_id]
```

- [ ] **Step 4: Run helper tests again**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_data_loader_get_eval_entry_returns_one_case tests/test_compare_routes.py::test_data_loader_get_eval_entry_missing_case_raises_404 -q
```

Expected:

- Both helper tests pass.
- Route test still fails because the compare router does not exist yet.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/services/data_loader.py demo-app/backend/tests/test_compare_routes.py
git commit -m "test: add compare data loader helpers"
```

---

### Task 2: Compare Models and Cases Route

**Files:**
- Modify: `demo-app/backend/app/models.py`
- Create: `demo-app/backend/app/routes/compare.py`
- Modify: `demo-app/backend/app/main.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Add tests for request validation**

Extend `demo-app/backend/tests/test_compare_routes.py` with:

```python
def test_compare_cases_rejects_unknown_skill(client: TestClient) -> None:
    r = client.get("/api/compare/not-a-skill/cases")
    assert r.status_code == 404


def test_compare_replay_rejects_unknown_skill(client: TestClient) -> None:
    r = client.post(
        "/api/compare/replay",
        json={"skill": "not-a-skill", "test_case_id": "tc_a01"},
    )
    assert r.status_code == 422


def test_compare_live_rejects_invalid_prompt_mode(client: TestClient) -> None:
    r = client.post(
        "/api/compare/live",
        json={"skill": "docx", "prompt_mode": "bad-mode", "test_case_id": "tc_a01"},
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests and verify route failures**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py -q
```

Expected:

- Compare route tests fail with 404 for routes that do not exist.

- [ ] **Step 3: Add compare Pydantic models**

Modify `demo-app/backend/app/models.py` by adding:

```python
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
```

- [ ] **Step 4: Add compare router skeleton**

Create `demo-app/backend/app/routes/compare.py`:

```python
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models import CompareLiveRequest, CompareReplayRequest, CompareRunResponse
from app.services import compare, data_loader

router = APIRouter()


@router.get("/api/compare/{skill}/cases")
def list_compare_cases(skill: str) -> list[dict]:
    return data_loader.get_test_cases(skill)


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
```

- [ ] **Step 5: Add temporary compare service skeleton**

Create `demo-app/backend/app/services/compare.py`:

```python
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
    run = CompareRun(run_id=_new_run_id(), kind="live", skill=req.skill, live_request=req)
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
```

- [ ] **Step 6: Include compare router in app**

Modify `demo-app/backend/app/main.py`:

```python
from app.routes import compare as compare_route
from app.routes import run as run_route
from app.routes import skills as skills_route
```

Then add after the existing router includes:

```python
app.include_router(compare_route.router)
```

- [ ] **Step 7: Run compare route tests**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py -q
```

Expected:

- Case metadata and validation tests pass.
- Replay stream behavior is still minimal and will be expanded in Task 3.

- [ ] **Step 8: Commit Task 2**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/models.py demo-app/backend/app/routes/compare.py demo-app/backend/app/main.py demo-app/backend/app/services/compare.py demo-app/backend/tests/test_compare_routes.py
git commit -m "feat: add compare route skeleton"
```

---

### Task 3: Replay Compare SSE

**Files:**
- Modify: `demo-app/backend/app/services/compare.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Add replay SSE contract test**

Append to `demo-app/backend/tests/test_compare_routes.py`:

```python
import json
import re


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    blocks = [b for b in raw.strip().split("\n\n") if b.strip()]
    parsed: list[tuple[str, dict]] = []
    for block in blocks:
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            if line.startswith("data: "):
                data = line[len("data: ") :]
        if event and data:
            parsed.append((event, json.loads(data)))
    return parsed


@requires_stable
def test_compare_replay_returns_run_id(client: TestClient) -> None:
    r = client.post("/api/compare/replay", json={"skill": "docx", "test_case_id": "tc_a01"})
    assert r.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{12}", r.json()["run_id"])


@requires_stable
def test_compare_replay_stream_emits_jsonl_and_result(client: TestClient) -> None:
    created = client.post(
        "/api/compare/replay",
        json={"skill": "docx", "test_case_id": "tc_a01"},
    )
    run_id = created.json()["run_id"]

    with client.stream("GET", f"/api/compare/replay/{run_id}/stream") as r:
        assert r.status_code == 200
        raw = "".join(chunk for chunk in r.iter_text())

    parsed = _parse_sse(raw)
    events = [e for e, _ in parsed]
    assert events[0] == "status"
    assert "jsonl" in events
    assert "result" in events
    assert events[-1] == "complete"

    statuses = [d["phase"] for e, d in parsed if e == "status"]
    assert statuses == ["queued", "run_original", "run_peak", "judge", "done"]

    result = next(d for e, d in parsed if e == "result")
    assert result["skill"] == "docx"
    assert result["test_case_id"] == "tc_a01"
    assert result["winner"] in {"original", "peak", "tie"}
    assert result["original"]["round"] == 1
    assert result["peak"]["round"] >= 1
```

- [ ] **Step 2: Run test and verify replay stream is incomplete**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_compare_replay_stream_emits_jsonl_and_result -q
```

Expected:

- Test fails because only `status: done` and `complete` are emitted.

- [ ] **Step 3: Implement replay result building and winner logic**

In `demo-app/backend/app/services/compare.py`, add:

```python
WIN_THRESHOLD = 0.02


def _winner(original_score: float, peak_score: float) -> str:
    if peak_score - original_score >= WIN_THRESHOLD:
        return "peak"
    if original_score - peak_score >= WIN_THRESHOLD:
        return "original"
    return "tie"


def _side_payload(label: str, round_n: int, skill_md_round: int, eval_entry: dict) -> dict:
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
```

- [ ] **Step 4: Implement replay event stream**

Replace `stream_replay` in `demo-app/backend/app/services/compare.py` with:

```python
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
            yield _event("jsonl", {"source": "api_calls", "side": "judge", "record": row})
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
```

- [ ] **Step 5: Run replay SSE tests**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py -q
```

Expected:

- All compare route tests pass.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/services/compare.py demo-app/backend/tests/test_compare_routes.py
git commit -m "feat: stream compare replay logs"
```

---

### Task 4: Live Compare Run Validation and Fixture Resolution

**Files:**
- Modify: `demo-app/backend/app/services/compare.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Add live validation tests**

Append to `demo-app/backend/tests/test_compare_routes.py`:

```python
def test_compare_live_requires_api_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = client.post(
        "/api/compare/live",
        json={"skill": "docx", "prompt_mode": "test_case", "test_case_id": "tc_a01"},
    )
    assert r.status_code == 400
    assert "OPENROUTER_API_KEY" in r.json()["detail"]


def test_compare_live_custom_requires_prompt(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    r = client.post(
        "/api/compare/live",
        json={"skill": "docx", "prompt_mode": "custom", "custom_prompt": "   "},
    )
    assert r.status_code == 422


@requires_stable
def test_compare_live_rejects_unknown_fixture(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    r = client.post(
        "/api/compare/live",
        json={
            "skill": "docx",
            "prompt_mode": "custom",
            "custom_prompt": "Read the file.",
            "fixture_file": "fixtures/does-not-exist.docx",
        },
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run validation tests and verify missing API behavior fails**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_compare_live_requires_api_key tests/test_compare_routes.py::test_compare_live_custom_requires_prompt tests/test_compare_routes.py::test_compare_live_rejects_unknown_fixture -q
```

Expected:

- Missing API key test fails because `create_live_run` does not check the environment.
- Unknown fixture test fails because fixture validation does not exist.

- [ ] **Step 3: Add fixture and environment validation**

Modify imports in `demo-app/backend/app/services/compare.py`:

```python
import os
from pathlib import Path

from app.config import DISTILL_REPO_ROOT, TEST_CASES_DIR
```

Add these helpers:

```python
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
        raise HTTPException(status_code=400, detail="fixture path escapes test_cases") from e
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"fixture file missing: {fixture_file}")
    return path


def _live_prompt(req: CompareLiveRequest) -> tuple[str, Path | None]:
    if req.prompt_mode == "test_case":
        if not req.test_case_id:
            raise HTTPException(status_code=422, detail="test_case_id is required")
        tc = data_loader.get_test_case(req.skill, req.test_case_id)
        fixture = tc["fixture_files"][0] if tc["fixture_files"] else None
        return tc["prompt"], _resolve_fixture_path(req.skill, req.fixture_file or fixture)

    prompt = (req.custom_prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="custom_prompt is required")
    return prompt, _resolve_fixture_path(req.skill, req.fixture_file)
```

Replace `create_live_run` with:

```python
def create_live_run(req: CompareLiveRequest) -> CompareRun:
    if not os.getenv("OPENROUTER_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="OPENROUTER_API_KEY is required for live compare mode",
        )
    _live_prompt(req)
    run = CompareRun(run_id=_new_run_id(), kind="live", skill=req.skill, live_request=req)
    _runs[run.run_id] = run
    return run
```

- [ ] **Step 4: Run validation tests**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_compare_live_requires_api_key tests/test_compare_routes.py::test_compare_live_custom_requires_prompt tests/test_compare_routes.py::test_compare_live_rejects_unknown_fixture -q
```

Expected:

- All three tests pass.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/services/compare.py demo-app/backend/tests/test_compare_routes.py
git commit -m "feat: validate live compare requests"
```

---

### Task 5: Live Student Runner Wrapper

**Files:**
- Modify: `demo-app/backend/app/services/compare.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Add live stream test with monkeypatched side runner**

Append to `demo-app/backend/tests/test_compare_routes.py`:

```python
@requires_stable
def test_compare_live_stream_uses_runner_and_judge(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import compare as compare_module

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    def fake_run_side(*, run_id: str, side: str, skill: str, skill_round: int, prompt: str, fixture_path):
        return {
            "side": side,
            "skill_round": skill_round,
            "stop_reason": "end_turn",
            "iterations": 2,
            "duration_seconds": 1.2,
            "token_usage": {"prompt": 100, "completion": 20},
            "output_files": [f"/tmp/{side}/agent_final.md"],
            "log_records": [
                {"event": "start", "skill": skill, "model": "google/gemma-4-26b-a4b-it", "prompt": prompt},
                {"event": "end", "stop_reason": "end_turn", "tokens": {"prompt": 100, "completion": 20}},
            ],
        }

    def fake_judge(*, skill: str, prompt: str, original: dict, peak: dict, student_model: str):
        return {
            "winner": "peak",
            "score_original": 0.6,
            "score_peak": 0.9,
            "rationale": "Peak output is more complete.",
            "judge_model": "anthropic/claude-haiku-4-5",
            "student_model": student_model,
            "elapsed_s": 0.5,
            "original_output_files": original["output_files"],
            "peak_output_files": peak["output_files"],
        }

    monkeypatch.setattr(compare_module, "_run_student_side", fake_run_side)
    monkeypatch.setattr(compare_module, "_judge_live", fake_judge)

    created = client.post(
        "/api/compare/live",
        json={"skill": "docx", "prompt_mode": "test_case", "test_case_id": "tc_a01"},
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    with client.stream("GET", f"/api/compare/live/{run_id}/stream") as r:
        raw = "".join(chunk for chunk in r.iter_text())

    parsed = _parse_sse(raw)
    events = [e for e, _ in parsed]
    assert events[0] == "status"
    assert "jsonl" in events
    assert "result" in events
    assert events[-1] == "complete"
    result = next(d for e, d in parsed if e == "result")
    assert result["winner"] == "peak"
    assert result["score_peak"] == 0.9
```

- [ ] **Step 2: Run test and verify live stream is incomplete**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_compare_live_stream_uses_runner_and_judge -q
```

Expected:

- Test fails because `stream_live` does not call `_run_student_side` or `_judge_live`.

- [ ] **Step 3: Add import path helper for distillation_v2 modules**

Add to `demo-app/backend/app/services/compare.py`:

```python
import shutil
import sys
import tempfile
import time


def _ensure_distillation_imports() -> None:
    root = DISTILL_REPO_ROOT / "distillation_v2"
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
```

- [ ] **Step 4: Add skill version materialization and log reading**

Add:

```python
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
```

- [ ] **Step 5: Add synchronous student side runner**

Add:

```python
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
```

- [ ] **Step 6: Add live stream using runner output and monkeypatch seams**

Replace `stream_live` with:

```python
async def stream_live(run_id: str) -> AsyncIterator[str]:
    run = _get_run(run_id, "live")
    req = run.live_request
    if req is None:
        yield _event("status", {"phase": "error"})
        yield _event("log", {"side": "system", "tag": "error", "line": "live request missing"})
        yield _event("complete", {"run_id": run_id})
        return

    start = time.time()
    try:
        prompt, fixture_path = _live_prompt(req)
        summary = data_loader.get_summary(req.skill)
        best_round = int(summary["best_round"])
        student_model = summary.get("student_model", "google/gemma-4-26b-a4b-it")

        yield _event("status", {"phase": "queued"})
        yield _event("log", {"side": "system", "tag": "system", "line": "live compare accepted"})

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
            yield _event("jsonl", {"source": "runner", "side": "original", "record": record})

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
            yield _event("jsonl", {"source": "runner", "side": "peak", "record": record})

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
```

- [ ] **Step 7: Run live stream monkeypatch test**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_compare_live_stream_uses_runner_and_judge -q
```

Expected:

- Test now fails because `_judge_live` is not defined.

- [ ] **Step 8: Commit partial runner wrapper only if tests are isolated**

Do not commit until Task 6 defines `_judge_live` and the live stream test passes.

---

### Task 6: Live Judge Call

**Files:**
- Modify: `demo-app/backend/app/services/compare.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Add judge parsing unit test**

Append to `demo-app/backend/tests/test_compare_routes.py`:

```python
def test_parse_judge_json_extracts_result() -> None:
    from app.services.compare import _parse_judge_json

    raw = '{"winner":"peak","score_original":0.4,"score_peak":0.9,"rationale":"Peak follows the prompt."}'
    parsed = _parse_judge_json(raw)
    assert parsed["winner"] == "peak"
    assert parsed["score_original"] == 0.4
    assert parsed["score_peak"] == 0.9
    assert parsed["rationale"] == "Peak follows the prompt."


def test_parse_judge_json_falls_back_to_tie_for_bad_json() -> None:
    from app.services.compare import _parse_judge_json

    parsed = _parse_judge_json("not json")
    assert parsed["winner"] == "tie"
    assert parsed["score_original"] == 0.0
    assert parsed["score_peak"] == 0.0
    assert "not json" in parsed["rationale"]
```

- [ ] **Step 2: Run judge parsing tests and verify failure**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_parse_judge_json_extracts_result tests/test_compare_routes.py::test_parse_judge_json_falls_back_to_tie_for_bad_json -q
```

Expected:

- Tests fail because `_parse_judge_json` is not defined.

- [ ] **Step 3: Implement judge JSON parser**

Add to `demo-app/backend/app/services/compare.py`:

```python
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
```

- [ ] **Step 4: Add output preview and live judge implementation**

Add:

```python
def _preview_output_files(files: list[str]) -> list[dict]:
    previews: list[dict] = []
    for f in files:
        path = Path(f)
        item = {"path": str(path), "exists": path.exists(), "size": 0, "preview": ""}
        if path.exists():
            item["size"] = path.stat().st_size
            if path.suffix.lower() in {".txt", ".md", ".json", ".csv"}:
                item["preview"] = path.read_text(encoding="utf-8", errors="replace")[:4000]
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
```

- [ ] **Step 5: Run live tests**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py -q
```

Expected:

- All compare tests pass.

- [ ] **Step 6: Run backend suite**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest -q
```

Expected:

- Existing backend tests and new compare tests pass.

- [ ] **Step 7: Commit Tasks 5 and 6 together**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/services/compare.py demo-app/backend/tests/test_compare_routes.py
git commit -m "feat: add live compare runner and judge"
```

---

### Task 7: Frontend Compare Types and API Helpers

**Files:**
- Modify: `demo-app/frontend/lib/types.ts`
- Modify: `demo-app/frontend/lib/api.ts`

- [ ] **Step 1: Add compare types**

Append to `demo-app/frontend/lib/types.ts`:

```ts
export type CompareWinner = "original" | "peak" | "tie";
export type ComparePhase = "idle" | "queued" | "run_original" | "run_peak" | "judge" | "done" | "error";

export type CompareCase = {
  id: string;
  workflow: string;
  name: string;
  prompt: string;
  expected_behavior: string;
  fixture_files: string[];
};

export type CompareSideResult = {
  label: string;
  round: number;
  skill_md_round: number;
  hybrid_score?: number;
  rule_score?: number;
  llm_judge_score?: number | null;
  rule_checks?: { name: string; passed: boolean; score?: number | null; reason: string }[];
  judge_rationale?: string;
  output?: string;
};

export type CompareResult = {
  skill?: string;
  test_case_id?: string;
  winner: CompareWinner;
  best_round?: number;
  original?: CompareSideResult;
  peak?: CompareSideResult;
  score_original?: number;
  score_peak?: number;
  rationale?: string;
  judge_model?: string;
  student_model?: string;
  elapsed_s?: number;
  original_output_files?: string[];
  peak_output_files?: string[];
};

export type CompareLogEntry =
  | { kind: "log"; side: string; tag: string; line: string }
  | { kind: "jsonl"; source: string; side: string; record: unknown };
```

- [ ] **Step 2: Add compare API helpers**

Modify `demo-app/frontend/lib/api.ts`:

```ts
import type { CompareCase } from "./types";
```

Append:

```ts
export type CompareRunResponse = { run_id: string };

export function fetchCompareCases(skill: string): Promise<CompareCase[]> {
  return get<CompareCase[]>(`/api/compare/${encodeURIComponent(skill)}/cases`);
}

export async function createCompareReplayRun(
  skill: string,
  testCaseId: string
): Promise<CompareRunResponse> {
  const res = await fetch(`${BACKEND_URL}/api/compare/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skill, test_case_id: testCaseId }),
  });
  if (!res.ok) throw new Error(`compare replay → ${res.status} ${res.statusText}`);
  return (await res.json()) as CompareRunResponse;
}

export async function createCompareLiveRun(body: {
  skill: string;
  prompt_mode: "test_case" | "custom";
  test_case_id?: string;
  custom_prompt?: string;
  fixture_file?: string;
}): Promise<CompareRunResponse> {
  const res = await fetch(`${BACKEND_URL}/api/compare/live`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`compare live → ${res.status} ${detail}`);
  }
  return (await res.json()) as CompareRunResponse;
}

export function compareReplayStreamUrl(runId: string): string {
  return `${BACKEND_URL}/api/compare/replay/${encodeURIComponent(runId)}/stream`;
}

export function compareLiveStreamUrl(runId: string): string {
  return `${BACKEND_URL}/api/compare/live/${encodeURIComponent(runId)}/stream`;
}
```

- [ ] **Step 3: Run TypeScript check**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
```

Expected:

- TypeScript passes.

- [ ] **Step 4: Commit Task 7**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/frontend/lib/types.ts demo-app/frontend/lib/api.ts
git commit -m "feat: add compare frontend API types"
```

---

### Task 8: Compare Page and Client UI

**Files:**
- Create: `demo-app/frontend/app/compare/page.tsx`
- Create: `demo-app/frontend/app/compare/compare-client.tsx`

- [ ] **Step 1: Create server page**

Create `demo-app/frontend/app/compare/page.tsx`:

```tsx
import { Bi } from "@/components/bi";
import { TopBar } from "@/components/topbar";
import { fetchCompareCases, fetchSummary } from "@/lib/api";
import { CompareClient } from "./compare-client";

const SKILLS = ["docx", "internal-comms", "slack-gif-creator"] as const;

export default async function ComparePage() {
  const [summaries, casesBySkillEntries] = await Promise.all([
    Promise.all(SKILLS.map(fetchSummary)),
    Promise.all(SKILLS.map(async (skill) => [skill, await fetchCompareCases(skill)] as const)),
  ]);
  const casesBySkill = Object.fromEntries(casesBySkillEntries);

  return (
    <>
      <TopBar
        crumbs={[
          { label: <Bi vi="Tổng quan" en="Overview" />, href: "/" },
          { label: <Bi vi="So sánh" en="Compare" /> },
        ]}
      />
      <CompareClient summaries={summaries} casesBySkill={casesBySkill} />
    </>
  );
}
```

- [ ] **Step 2: Create client component imports and helpers**

Create `demo-app/frontend/app/compare/compare-client.tsx` with:

```tsx
"use client";

import { useMemo, useRef, useState } from "react";
import { Bi } from "@/components/bi";
import { Icon } from "@/components/icon";
import {
  compareLiveStreamUrl,
  compareReplayStreamUrl,
  createCompareLiveRun,
  createCompareReplayRun,
  type RealSummary,
} from "@/lib/api";
import type {
  CompareCase,
  CompareLogEntry,
  ComparePhase,
  CompareResult,
  CompareSideResult,
} from "@/lib/types";

type Props = {
  summaries: RealSummary[];
  casesBySkill: Record<string, CompareCase[]>;
};

const SKILLS = ["docx", "internal-comms", "slack-gif-creator"] as const;

function fmtScore(v: number | null | undefined): string {
  return typeof v === "number" ? v.toFixed(3) : "n/a";
}

function winnerLabel(winner?: string): string {
  if (winner === "peak") return "Peak wins";
  if (winner === "original") return "Original wins";
  if (winner === "tie") return "Tie";
  return "No result";
}
```

- [ ] **Step 3: Add component state and SSE handling**

Continue `compare-client.tsx` with:

```tsx
export function CompareClient({ summaries, casesBySkill }: Props) {
  const [skill, setSkill] = useState<string>("docx");
  const [mode, setMode] = useState<"replay" | "live">("replay");
  const [promptMode, setPromptMode] = useState<"test_case" | "custom">("test_case");
  const [testCaseId, setTestCaseId] = useState<string>(casesBySkill.docx?.[0]?.id || "");
  const [customPrompt, setCustomPrompt] = useState("");
  const [fixtureFile, setFixtureFile] = useState("");
  const [phase, setPhase] = useState<ComparePhase>("idle");
  const [logs, setLogs] = useState<CompareLogEntry[]>([]);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);

  const summary = summaries.find((s) => s.skill === skill) || summaries[0];
  const cases = casesBySkill[skill] || [];
  const activeCase = cases.find((c) => c.id === testCaseId) || cases[0];
  const fixtures = useMemo(() => {
    const seen = new Set<string>();
    for (const c of cases) for (const f of c.fixture_files) seen.add(f);
    return [...seen].sort();
  }, [cases]);

  function resetRun() {
    setLogs([]);
    setResult(null);
    setError("");
    setPhase("idle");
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }

  function attachStream(url: string) {
    const es = new EventSource(url);
    eventSourceRef.current = es;
    es.addEventListener("status", (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { phase: ComparePhase };
      setPhase(data.phase);
      if (data.phase === "done" || data.phase === "error") es.close();
    });
    es.addEventListener("log", (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { side: string; tag: string; line: string };
      setLogs((prev) => [...prev, { kind: "log", ...data }]);
    });
    es.addEventListener("jsonl", (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { source: string; side: string; record: unknown };
      setLogs((prev) => [...prev, { kind: "jsonl", ...data }]);
    });
    es.addEventListener("result", (e) => {
      setResult(JSON.parse((e as MessageEvent).data) as CompareResult);
    });
    es.addEventListener("complete", () => es.close());
    es.onerror = () => {
      setError("Stream closed. Check that the backend is still running.");
      es.close();
    };
  }

  async function runCompare() {
    resetRun();
    try {
      if (mode === "replay") {
        const created = await createCompareReplayRun(skill, activeCase.id);
        attachStream(compareReplayStreamUrl(created.run_id));
        return;
      }
      const created = await createCompareLiveRun({
        skill,
        prompt_mode: promptMode,
        test_case_id: promptMode === "test_case" ? activeCase.id : undefined,
        custom_prompt: promptMode === "custom" ? customPrompt : undefined,
        fixture_file: fixtureFile || undefined,
      });
      attachStream(compareLiveStreamUrl(created.run_id));
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }
```

- [ ] **Step 4: Add JSX layout**

Continue `compare-client.tsx` with:

```tsx
  const canRun =
    mode === "replay" ||
    promptMode === "test_case" ||
    customPrompt.trim().length > 0;

  return (
    <div className="page stack-lg">
      <section className="compare-header">
        <div>
          <div className="eyebrow">Arena Compare</div>
          <h1 className="h1">
            <Bi vi="So sánh skill original với skill peak." en="Compare original skill against peak skill." />
          </h1>
          <p className="muted" style={{ maxWidth: 760 }}>
            <Bi
              vi="Replay dùng log JSONL có sẵn; Live chạy thật hai version skill rồi gọi judge."
              en="Replay uses existing JSONL logs; Live runs both skill versions and calls the judge."
            />
          </p>
        </div>
        <div className="compare-status">
          <span className="badge">{phase}</span>
          {result && <span className="badge badge-success">{winnerLabel(result.winner)}</span>}
        </div>
      </section>

      <section className="compare-controls">
        <label>
          Skill
          <select
            className="select"
            value={skill}
            onChange={(e) => {
              const next = e.target.value;
              setSkill(next);
              setTestCaseId(casesBySkill[next]?.[0]?.id || "");
              resetRun();
            }}
          >
            {SKILLS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>

        <div className="segmented">
          <button className={mode === "replay" ? "active" : ""} onClick={() => setMode("replay")}>Replay</button>
          <button className={mode === "live" ? "active" : ""} onClick={() => setMode("live")}>Live judge</button>
        </div>

        <label>
          Test case
          <select className="select" value={activeCase?.id || ""} onChange={(e) => setTestCaseId(e.target.value)}>
            {cases.map((c) => (
              <option key={c.id} value={c.id}>{c.id} · {c.name}</option>
            ))}
          </select>
        </label>

        <button className="btn btn-primary" disabled={!canRun || phase === "queued"} onClick={runCompare}>
          <Icon name="play" size={16} />
          {mode === "replay" ? "Replay comparison" : "Run live arena"}
        </button>
      </section>

      {mode === "live" && (
        <section className="compare-live-controls">
          <div className="segmented">
            <button className={promptMode === "test_case" ? "active" : ""} onClick={() => setPromptMode("test_case")}>Existing test case</button>
            <button className={promptMode === "custom" ? "active" : ""} onClick={() => setPromptMode("custom")}>Custom prompt</button>
          </div>
          {promptMode === "custom" && (
            <textarea
              className="textarea"
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              aria-label="Custom prompt for both skill versions"
            />
          )}
          <label>
            Fixture
            <select className="select" value={fixtureFile} onChange={(e) => setFixtureFile(e.target.value)}>
              <option value="">No fixture / auto from test case</option>
              {fixtures.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </label>
        </section>
      )}

      <section className="compare-prompt panel">
        <div className="panel-header">
          <h3 className="panel-title">Prompt</h3>
          <span className="badge">best R{summary.best_round}</span>
        </div>
        <div className="panel-body">
          <p>{promptMode === "custom" && customPrompt.trim() ? customPrompt : activeCase?.prompt}</p>
        </div>
      </section>

      {error && <div className="compare-error">{error}</div>}

      <section className="arena-grid">
        <CompareSide title="A · Original Skill" result={result?.original} liveScore={result?.score_original} files={result?.original_output_files} />
        <CompareSide title={`B · Peak Skill R${summary.best_round}`} result={result?.peak} liveScore={result?.score_peak} files={result?.peak_output_files} />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h3 className="panel-title">JSONL log</h3>
          <span className="badge">{logs.length} events</span>
        </div>
        <div className="compare-log">
          {logs.map((entry, idx) =>
            entry.kind === "log" ? (
              <div key={idx} className="log-line"><span>{entry.side}</span><span>{entry.tag}</span><code>{entry.line}</code></div>
            ) : (
              <details key={idx} className="log-json">
                <summary>{entry.side} · {entry.source}</summary>
                <pre>{JSON.stringify(entry.record, null, 2)}</pre>
              </details>
            )
          )}
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 5: Add side result component**

Append to `compare-client.tsx`:

```tsx
function CompareSide({
  title,
  result,
  liveScore,
  files,
}: {
  title: string;
  result?: CompareSideResult;
  liveScore?: number;
  files?: string[];
}) {
  return (
    <article className="arena-side panel">
      <div className="panel-header">
        <h3 className="panel-title">{title}</h3>
        <span className="badge">{result ? `R${result.skill_md_round}` : "waiting"}</span>
      </div>
      <div className="panel-body stack">
        <div className="grid-3">
          <div className="stat"><div className="stat-label">Hybrid</div><div className="stat-value">{fmtScore(result?.hybrid_score ?? liveScore)}</div></div>
          <div className="stat"><div className="stat-label">Rule</div><div className="stat-value">{fmtScore(result?.rule_score)}</div></div>
          <div className="stat"><div className="stat-label">Judge</div><div className="stat-value">{fmtScore(result?.llm_judge_score)}</div></div>
        </div>
        {result?.judge_rationale && <p className="muted">{result.judge_rationale}</p>}
        {result?.rule_checks && (
          <div className="rule-list">
            {result.rule_checks.slice(0, 8).map((c) => (
              <div key={c.name} className="rule-row">
                <span className={c.passed ? "dot dot-ok" : "dot dot-bad"} />
                <span>{c.name}</span>
                <span>{fmtScore(c.score)}</span>
              </div>
            ))}
          </div>
        )}
        {result?.output && <code className="output-path">{result.output}</code>}
        {files && files.length > 0 && (
          <div className="stack-sm">
            {files.map((f) => <code key={f} className="output-path">{f}</code>)}
          </div>
        )}
      </div>
    </article>
  );
}
```

- [ ] **Step 6: Run TypeScript check**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
```

Expected:

- No TypeScript errors remain.

- [ ] **Step 7: Commit Task 8**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/frontend/app/compare/page.tsx demo-app/frontend/app/compare/compare-client.tsx
git commit -m "feat: add compare arena page"
```

---

### Task 9: Navigation and Styling

**Files:**
- Modify: `demo-app/frontend/components/sidebar.tsx`
- Modify: `demo-app/frontend/app/globals.css`

- [ ] **Step 1: Add sidebar link**

In `demo-app/frontend/components/sidebar.tsx`, insert this link after the `/run` link and before `/about`:

```tsx
<Link
  className={"nav-item" + (isActive("/compare") ? " active" : "")}
  href="/compare"
  aria-current={isActive("/compare") ? "page" : undefined}
>
  <Icon name="layers" />
  <Bi vi="So sánh" en="Compare" />
</Link>
```

- [ ] **Step 2: Add compare CSS**

Append to `demo-app/frontend/app/globals.css`:

```css
.compare-header,
.compare-controls,
.compare-live-controls {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.compare-controls,
.compare-live-controls {
  padding: 14px;
  border: 1px solid var(--border);
  background: var(--surface);
}

.compare-controls label,
.compare-live-controls label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 180px;
  font-size: 12px;
  color: var(--fg-subtle);
}

.segmented {
  display: inline-flex;
  border: 1px solid var(--border);
  background: var(--surface-muted);
}

.segmented button {
  min-height: 34px;
  padding: 0 12px;
  border: 0;
  background: transparent;
  color: var(--fg-subtle);
  cursor: pointer;
}

.segmented button.active {
  background: var(--primary);
  color: var(--primary-fg);
}

.textarea {
  width: min(100%, 720px);
  min-height: 120px;
  resize: vertical;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--fg);
  padding: 10px 12px;
  font: inherit;
}

.arena-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.arena-side {
  min-width: 0;
}

.compare-log {
  max-height: 360px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 12px;
}

.log-line {
  display: grid;
  grid-template-columns: 92px 80px minmax(0, 1fr);
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--border);
  background: var(--surface-muted);
}

.log-line code,
.output-path {
  white-space: pre-wrap;
  word-break: break-word;
}

.log-json {
  border: 1px solid var(--border);
  background: var(--surface-muted);
  padding: 8px;
}

.log-json pre {
  overflow: auto;
  margin: 8px 0 0;
  white-space: pre-wrap;
}

.rule-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rule-row {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) 56px;
  gap: 8px;
  align-items: center;
  font-size: 12px;
}

.dot-ok {
  background: var(--success);
}

.dot-bad {
  background: var(--danger);
}

.compare-error {
  padding: 12px;
  border: 1px solid var(--danger);
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
}

@media (max-width: 900px) {
  .arena-grid {
    grid-template-columns: 1fr;
  }

  .log-line {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 3: Run lint/type-check**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
pnpm lint
```

Expected:

- TypeScript passes.
- ESLint passes.

- [ ] **Step 4: Commit Task 9**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/frontend/components/sidebar.tsx demo-app/frontend/app/globals.css
git commit -m "feat: add compare navigation and styles"
```

---

### Task 10: End-to-End Verification

**Files:**
- No source files should be changed unless verification finds a defect.

- [ ] **Step 1: Run backend tests**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest -q
```

Expected:

- All backend tests pass.

- [ ] **Step 2: Run frontend checks**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
pnpm lint
```

Expected:

- TypeScript passes.
- ESLint passes.

- [ ] **Step 3: Run app locally**

Run:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app
make dev
```

Expected:

- Backend starts at `http://127.0.0.1:8000`.
- Frontend starts at `http://localhost:3000`.

- [ ] **Step 4: Smoke test replay endpoints**

In another terminal, run:

```bash
RUN_ID=$(curl -s -X POST http://127.0.0.1:8000/api/compare/replay \
  -H 'Content-Type: application/json' \
  -d '{"skill":"docx","test_case_id":"tc_a01"}' | python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')
curl -N "http://127.0.0.1:8000/api/compare/replay/$RUN_ID/stream" | sed -n '1,80p'
```

Expected:

- Output contains `event: status`, `event: jsonl`, `event: result`, and `event: complete`.

- [ ] **Step 5: Browser smoke test**

Open:

```txt
http://localhost:3000/compare
```

Verify:

- Page loads with `docx`.
- Replay button streams JSONL log rows.
- Result banner appears.
- Switching skill updates test-case choices.
- Live mode shows textarea and fixture dropdown.
- Live run button rejects missing prompt for custom mode.

- [ ] **Step 6: Optional real live run**

Only run this when API credit and Claude CLI are available:

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app
OPENROUTER_API_KEY="$OPENROUTER_API_KEY" make dev
```

Then in the browser:

- Open `/compare`.
- Select Live mode.
- Select an existing short test case.
- Click `Run live arena`.

Expected:

- Logs appear for original side, then peak side, then judge.
- Final result includes winner and rationale.

- [ ] **Step 7: Final commit if verification fixes were needed**

If verification required edits:

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend demo-app/frontend
git commit -m "fix: polish compare arena verification"
```

If no edits were needed, do not create an empty commit.
