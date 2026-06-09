# Arena Compare v2 — Side-by-Side Step Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/compare` into an arena-style page that streams each student step (tool call / result / assistant text) live per side, renders the produced `.docx` in-browser (PDF), and runs an image-based live judge — and fix the live-mode `OPENROUTER_API_KEY` 400.

**Architecture:** Backend keeps the existing replay/live SSE runs but swaps the raw `jsonl` event for a typed, side-tagged `step` event plus an `artifact` event; live runs tail the student JSONL log (written incrementally by `AgentLogger`) from a worker thread to stream steps in real time, then convert output `.docx`→PDF (reusing `utils/converter.py`) and judge with rendered images. Frontend splits `compare-client.tsx` into focused components rendering two arena columns (live step timeline or replay artifacts) plus a judge verdict.

**Tech Stack:** FastAPI, Pydantic v2, SSE, asyncio + threading (log tailing), LibreOffice via `distillation_v2/utils/converter.py`, Next.js 16 App Router, React 19, TypeScript.

**Spec:** `docs/superpowers/specs/2026-05-29-arena-compare-v2-design.md`

---

## File Structure

Backend (`demo-app/backend/`):
- Modify `app/config.py` — load repo-root `.env`.
- Modify `app/services/data_loader.py` — add `batch` to eval rows; add `get_artifact_dir`.
- Modify `app/services/compare.py` — `CompareRun.output_dirs`; artifact helpers; replay artifact events; live streaming generator + step events; image judge.
- Modify `app/routes/compare.py` — replay + live artifact endpoints.
- Modify `distillation_v2/utils/converter.py` — add public `docx_to_pdf`.
- Modify `tests/test_compare_routes.py` — update replay/live tests; add artifact + judge-image tests.

Frontend (`demo-app/frontend/`):
- Modify `lib/types.ts` — `CompareStep`, `CompareArtifact`, `CompareSideState`.
- Modify `lib/api.ts` — `compareArtifactUrl` builders.
- Create `app/compare/step-card.tsx`, `app/compare/artifact-view.tsx`, `app/compare/judge-verdict.tsx`, `app/compare/arena-column.tsx`.
- Modify `app/compare/compare-client.tsx` — route `step`/`artifact` to sides; render columns.
- Modify `app/globals.css` — timeline / step-card / arena styles.

`app/compare/page.tsx` is unchanged.

---

### Task 1: Fix live-mode env (load `.env`)

**Files:**
- Modify: `demo-app/backend/app/config.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_compare_routes.py`:

```python
def test_backend_loads_repo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # config.py must call load_dotenv on the repo-root .env at import time.
    import importlib

    import app.config as config_mod

    importlib.reload(config_mod)
    # The repo .env carries OPENROUTER_API_KEY; after import it must be visible.
    import os

    assert os.getenv("OPENROUTER_API_KEY"), "config import should load repo-root .env"
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_backend_loads_repo_env -q
```
Expected: FAIL (env not loaded) — unless the shell already exported the key. If it passes spuriously, run with `env -u OPENROUTER_API_KEY` prefixed to prove it fails without the fix.

- [ ] **Step 3: Load `.env` in config**

In `demo-app/backend/app/config.py`, add after the imports (after `from pathlib import Path`):

```python
from dotenv import load_dotenv
```

and after `DISTILL_REPO_ROOT = Path(...)` is defined, add:

```python
# Load the same .env the pipeline uses so live-compare can read OPENROUTER_API_KEY.
load_dotenv(DISTILL_REPO_ROOT / ".env")
```

- [ ] **Step 4: Run test, verify it passes**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_backend_loads_repo_env -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/config.py demo-app/backend/tests/test_compare_routes.py
git commit -m "fix: load repo .env in backend for live compare"
```

---

### Task 2: Public `docx_to_pdf` converter

**Files:**
- Modify: `distillation_v2/utils/converter.py`
- Test: `distillation_v2/tests/test_converter.py`

- [ ] **Step 1: Write failing test**

Append to `distillation_v2/tests/test_converter.py`:

```python
def test_docx_to_pdf_exposed_public_wrapper():
    # docx_to_pdf must exist and return None for a missing file (no soffice needed).
    from pathlib import Path

    from utils.converter import docx_to_pdf

    assert docx_to_pdf(Path("/nonexistent/file.docx")) is None
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/distillation_v2
/opt/anaconda3/envs/skills/bin/pytest tests/test_converter.py::test_docx_to_pdf_exposed_public_wrapper -q
```
Expected: FAIL — `ImportError: cannot import name 'docx_to_pdf'`.

- [ ] **Step 3: Add the public wrapper**

In `distillation_v2/utils/converter.py`, add after `find_docx` (before the `# ── Internal ──` divider):

```python
def docx_to_pdf(docx_path: Path) -> Path | None:
    """Convert a .docx to .pdf (kept on disk, unlike docx_to_images which deletes it).

    Returns the PDF path next to the source, or None on any failure.
    """
    if not docx_path.is_file():
        _log.warning("converter: file not found: %s", docx_path)
        return None
    return _convert_to_pdf_with_retry(docx_path)
```

- [ ] **Step 4: Run test, verify it passes**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_converter.py::test_docx_to_pdf_exposed_public_wrapper -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add distillation_v2/utils/converter.py distillation_v2/tests/test_converter.py
git commit -m "feat: add public docx_to_pdf converter wrapper"
```

---

### Task 3: Data loader artifact mapping

**Files:**
- Modify: `demo-app/backend/app/services/data_loader.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_compare_routes.py`:

```python
@requires_stable
def test_eval_entry_carries_batch() -> None:
    entry = data_loader.get_eval_entry("docx", round_n=1, test_case_id="tc_a01")
    assert isinstance(entry["batch"], int)
    assert entry["batch"] >= 1


@requires_stable
def test_get_artifact_dir_resolves_under_stable() -> None:
    from app.config import STABLE_DIR

    entry = data_loader.get_eval_entry("docx", round_n=1, test_case_id="tc_a01")
    d = data_loader.get_artifact_dir("docx", 1, entry["batch"], "tc_a01")
    assert d.is_dir()
    assert str(d).startswith(str(STABLE_DIR))


def test_get_artifact_dir_rejects_traversal() -> None:
    with pytest.raises(Exception) as exc:
        data_loader.get_artifact_dir("docx", 1, 1, "../../etc")
    assert getattr(exc.value, "status_code", None) in (400, 404)
```

- [ ] **Step 2: Run tests, verify they fail**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_eval_entry_carries_batch tests/test_compare_routes.py::test_get_artifact_dir_resolves_under_stable tests/test_compare_routes.py::test_get_artifact_dir_rejects_traversal -q
```
Expected: FAIL (`batch` KeyError; `get_artifact_dir` undefined).

- [ ] **Step 3: Add `batch` to eval rows**

In `demo-app/backend/app/services/data_loader.py`, inside `get_eval_detail`, in the appended dict (the `out.append({...})` block), add a `batch` field right after `"round": int(rd),`:

```python
                "round": int(rd),
                "batch": int(r.get("batch", 1)),
```

- [ ] **Step 4: Add `get_artifact_dir`**

Append to `demo-app/backend/app/services/data_loader.py` (after `get_api_calls_for_test_case`). `re` is already imported at the top of the file — do not re-import it:

```python
_TC_SAFE = re.compile(r"^tc_[a-z0-9]+$", re.IGNORECASE)


def get_artifact_dir(skill: str, round_n: int, batch: int, test_case_id: str) -> Path:
    """Return STABLE_DIR/{skill}/round_{round}/batch_{batch}/{tc}/ — validated.

    Rejects path traversal in test_case_id and confirms the dir is under the
    skill's stable directory.
    """
    if not _TC_SAFE.match(test_case_id or ""):
        raise HTTPException(status_code=400, detail=f"bad test_case_id: {test_case_id}")
    base = _skill_dir(skill)
    path = (base / f"round_{int(round_n)}" / f"batch_{int(batch)}" / test_case_id).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="artifact path escapes stable dir") from e
    if not path.is_dir():
        raise HTTPException(status_code=404, detail=f"artifact dir not found: {path}")
    return path
```

- [ ] **Step 5: Run tests, verify they pass**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_eval_entry_carries_batch tests/test_compare_routes.py::test_get_artifact_dir_resolves_under_stable tests/test_compare_routes.py::test_get_artifact_dir_rejects_traversal -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/services/data_loader.py demo-app/backend/tests/test_compare_routes.py
git commit -m "feat: add artifact dir mapping + batch in eval rows"
```

---

### Task 4: Artifact serving endpoints

**Files:**
- Modify: `demo-app/backend/app/services/compare.py`
- Modify: `demo-app/backend/app/routes/compare.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_compare_routes.py`:

```python
@requires_stable
def test_replay_artifact_png_served(client: TestClient) -> None:
    entry = data_loader.get_eval_entry("docx", round_n=1, test_case_id="tc_a01")
    r = client.get(
        f"/api/compare/docx/artifact?round=1&batch={entry['batch']}&tc=tc_a01&file=page_01.png"
    )
    # page_01.png exists for tc_a01 in stable; if a given case lacks it, 404 is allowed.
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.headers["content-type"] == "image/png"


def test_replay_artifact_rejects_traversal(client: TestClient) -> None:
    r = client.get("/api/compare/docx/artifact?round=1&batch=1&tc=tc_a01&file=../x.png")
    assert r.status_code == 400


def test_live_artifact_unknown_run_404(client: TestClient) -> None:
    r = client.get("/api/compare/artifact?run_id=deadbeef&side=original&file=out.pdf")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests, verify they fail**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_replay_artifact_rejects_traversal tests/test_compare_routes.py::test_live_artifact_unknown_run_404 -q
```
Expected: FAIL (routes 404 because endpoints don't exist → traversal test gets 404 not 400; live test path differs).

- [ ] **Step 3: Add `output_dirs` to `CompareRun` + artifact helpers**

In `demo-app/backend/app/services/compare.py`:

Change the imports line `from dataclasses import dataclass` to:

```python
from dataclasses import dataclass, field
```

Add to the `CompareRun` dataclass (after `live_request`):

```python
    output_dirs: dict[str, str] = field(default_factory=dict)
```

Add `import re` to the stdlib import group at the top of `compare.py` (it is not yet imported there). Then add these helpers (place after `_resolve_fixture_path`):

```python
_SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]+$")


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
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(suffix, "application/octet-stream")
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type=media,
        headers={"Content-Disposition": f'{disposition}; filename="{path.name}"'},
    )


def _pdf_cache_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "compare-pdf-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_replay_pdf(skill: str, round_n: int, batch: int, test_case_id: str) -> Path:
    """Convert the stable .docx for one replay side to PDF, cached OUTSIDE stable."""
    _ensure_distillation_imports()
    from utils.converter import docx_to_pdf, find_docx

    cache = _pdf_cache_dir() / f"{skill}_r{round_n}_b{batch}_{test_case_id}.pdf"
    if cache.is_file():
        return cache
    art_dir = data_loader.get_artifact_dir(skill, round_n, batch, test_case_id)
    docx = find_docx(art_dir)
    if docx is None:
        raise HTTPException(status_code=404, detail="no .docx to render for this case")
    pdf = docx_to_pdf(docx)
    if pdf is None:
        raise HTTPException(status_code=502, detail="docx→pdf conversion failed")
    shutil.copyfile(pdf, cache)
    return cache


def serve_replay_artifact(skill: str, round_n: int, batch: int, test_case_id: str, file: str):
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


def serve_live_artifact(run_id: str, side: str, file: str):
    run = _get_run(run_id, "live")
    out_dir = run.output_dirs.get(side)
    if not out_dir:
        raise HTTPException(status_code=404, detail="no artifacts for that side yet")
    base = Path(out_dir).resolve()
    target = (base / _safe_file(file)).resolve()
    try:
        target.relative_to(base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path escapes output dir") from e
    return _serve_file(target, download=file.lower().endswith(".docx"))
```

(`_safe_file` already blocks `/` and `..`, so traversal returns 400 before reaching disk.)

- [ ] **Step 4: Add the routes**

In `demo-app/backend/app/routes/compare.py`, add two endpoints (after `list_compare_cases`):

```python
@router.get("/api/compare/artifact")
def get_live_artifact(run_id: str, side: str, file: str):
    return compare.serve_live_artifact(run_id, side, file)


@router.get("/api/compare/{skill}/artifact")
def get_replay_artifact(skill: str, round: int, batch: int, tc: str, file: str):
    return compare.serve_replay_artifact(skill, round, batch, tc, file)
```

(Declare `/api/compare/artifact` BEFORE `/api/compare/{skill}/artifact` so `artifact` is not captured as `{skill}`.)

- [ ] **Step 5: Run tests, verify they pass**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_replay_artifact_png_served tests/test_compare_routes.py::test_replay_artifact_rejects_traversal tests/test_compare_routes.py::test_live_artifact_unknown_run_404 -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/services/compare.py demo-app/backend/app/routes/compare.py demo-app/backend/tests/test_compare_routes.py
git commit -m "feat: serve compare artifacts (pdf/docx/png)"
```

---

### Task 5: Replay emits `artifact` events

**Files:**
- Modify: `demo-app/backend/app/services/compare.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Update the replay SSE test**

In `tests/test_compare_routes.py`, replace the body of `test_compare_replay_stream_emits_jsonl_and_result` assertions block (the part after `parsed = _parse_sse(raw)`) with:

```python
    parsed = _parse_sse(raw)
    events = [e for e, _ in parsed]
    assert events[0] == "status"
    assert "artifact" in events
    assert "result" in events
    assert events[-1] == "complete"

    statuses = [d["phase"] for e, d in parsed if e == "status"]
    assert statuses == ["queued", "run_original", "run_peak", "judge", "done"]

    sides = {d["side"] for e, d in parsed if e == "artifact"}
    assert sides == {"original", "peak"}

    result = next(d for e, d in parsed if e == "result")
    assert result["skill"] == "docx"
    assert result["winner"] in {"original", "peak", "tie"}
    assert result["original"]["round"] == 1
    assert result["peak"]["round"] >= 1
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_compare_replay_stream_emits_jsonl_and_result -q
```
Expected: FAIL — no `artifact` events yet.

- [ ] **Step 3: Add a replay-artifact builder**

In `demo-app/backend/app/services/compare.py`, add (after `_replay_result`):

```python
def _replay_artifacts(skill: str, side: str, round_n: int, batch: int, test_case_id: str) -> list[dict]:
    """Build artifact events for one replay side from stable files."""
    try:
        art_dir = data_loader.get_artifact_dir(skill, round_n, batch, test_case_id)
    except HTTPException:
        return []
    out: list[dict] = []
    base = f"/api/compare/{skill}/artifact?round={round_n}&batch={batch}&tc={test_case_id}"
    docx = next((p for p in sorted(art_dir.glob("*.docx")) if "fixture" not in p.name.lower()), None)
    if docx is not None:
        out.append({"side": side, "kind": "pdf", "label": docx.name,
                    "url": f"{base}&file=document.pdf",
                    "round": round_n, "batch": batch, "test_case_id": test_case_id})
        out.append({"side": side, "kind": "docx", "label": docx.name,
                    "url": f"{base}&file={docx.name}",
                    "round": round_n, "batch": batch, "test_case_id": test_case_id})
    else:
        text_file = next((p for p in art_dir.iterdir()
                          if p.suffix.lower() in {".txt", ".json", ".md"} and p.name != "agent_final.md"), None)
        if text_file is not None:
            out.append({"side": side, "kind": "text", "label": text_file.name,
                        "text": text_file.read_text(encoding="utf-8", errors="replace")[:8000],
                        "round": round_n, "batch": batch, "test_case_id": test_case_id})
    final = art_dir / "agent_final.md"
    if final.is_file():
        out.append({"side": side, "kind": "text", "label": "agent_final.md",
                    "text": final.read_text(encoding="utf-8", errors="replace")[:8000],
                    "round": round_n, "batch": batch, "test_case_id": test_case_id})
    return out
```

- [ ] **Step 4: Rewrite `stream_replay` to emit artifacts instead of jsonl**

Replace the whole `stream_replay` function body with:

```python
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
        yield _event("log", {"side": "system", "tag": "system",
                             "line": f"loaded replay {run.skill}/{run.test_case_id}"})

        yield _event("status", {"phase": "run_original"})
        for art in _replay_artifacts(run.skill, "original", 1,
                                     int(original_eval["batch"]), run.test_case_id):
            yield _event("artifact", art)

        yield _event("status", {"phase": "run_peak"})
        for art in _replay_artifacts(run.skill, "peak", int(result["best_round"]),
                                     int(peak_eval["batch"]), run.test_case_id):
            yield _event("artifact", art)

        yield _event("status", {"phase": "judge"})
        yield _event("log", {"side": "judge", "tag": "judge",
                             "line": f"winner={result['winner']} "
                                     f"original={result['original']['hybrid_score']} "
                                     f"peak={result['peak']['hybrid_score']}"})
        yield _event("result", result)
        yield _event("status", {"phase": "done"})
        yield _event("complete", {"run_id": run_id})
    except Exception as e:  # noqa: BLE001
        yield _event("status", {"phase": "error"})
        yield _event("log", {"side": "system", "tag": "error", "line": f"{type(e).__name__}: {e}"})
        yield _event("complete", {"run_id": run_id})
```

- [ ] **Step 5: Run replay tests, verify pass**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py -k replay -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/services/compare.py demo-app/backend/tests/test_compare_routes.py
git commit -m "feat: replay streams artifact events"
```

---

### Task 6: Live real-time step streaming

**Files:**
- Modify: `demo-app/backend/app/services/compare.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Replace the live-stream test to use an async-generator seam**

In `tests/test_compare_routes.py`, replace the whole `test_compare_live_stream_uses_runner_and_judge` function with:

```python
@requires_stable
def test_compare_live_stream_streams_steps_and_judge(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import compare as compare_module

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    async def fake_side_stream(*, run_id, side, skill, skill_round, prompt, fixture_path):
        yield {"event": "start", "skill": skill, "model": "m", "prompt": prompt}
        yield {"event": "tool_call", "iteration": 1, "tool": "Bash",
               "args": {"command": "ls", "description": "list"}}
        yield {"event": "tool_result", "iteration": 1, "tool": "Bash", "result": "ok"}
        yield {"event": "assistant_text", "iteration": 2, "text": "done"}
        yield {"event": "end", "iterations": 2, "stop_reason": "success",
               "duration_seconds": 1.0, "tokens": {"prompt": 1, "completion": 1}}
        yield {"__result__": {"side": side, "skill_round": skill_round,
                              "stop_reason": "success", "iterations": 2,
                              "duration_seconds": 1.0,
                              "token_usage": {"prompt": 1, "completion": 1},
                              "output_files": [], "output_dir": "/tmp/x", "log_file": ""}}

    def fake_judge(*, skill, prompt, original, peak, student_model):
        return {"winner": "peak", "score_original": 0.6, "score_peak": 0.9,
                "rationale": "peak better", "judge_model": "anthropic/claude-haiku-4-5",
                "student_model": student_model, "elapsed_s": 0.5,
                "original_output_files": [], "peak_output_files": []}

    monkeypatch.setattr(compare_module, "_run_student_side_streaming", fake_side_stream)
    monkeypatch.setattr(compare_module, "_judge_live", fake_judge)

    created = client.post("/api/compare/live",
                          json={"skill": "docx", "prompt_mode": "test_case", "test_case_id": "tc_a01"})
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    with client.stream("GET", f"/api/compare/live/{run_id}/stream") as r:
        raw = "".join(chunk for chunk in r.iter_text())

    parsed = _parse_sse(raw)
    events = [e for e, _ in parsed]
    assert "step" in events
    assert "result" in events
    assert events[-1] == "complete"
    step_sides = {d["side"] for e, d in parsed if e == "step"}
    assert step_sides == {"original", "peak"}
    kinds = {d["kind"] for e, d in parsed if e == "step"}
    assert {"tool_call", "tool_result", "assistant_text"} <= kinds
    result = next(d for e, d in parsed if e == "result")
    assert result["winner"] == "peak" and result["score_peak"] == 0.9
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_compare_live_stream_streams_steps_and_judge -q
```
Expected: FAIL — `_run_student_side_streaming` undefined.

- [ ] **Step 3: Add imports for threading + asyncio**

In `demo-app/backend/app/services/compare.py`, add to the stdlib import group:

```python
import asyncio
import threading
```

- [ ] **Step 4: Add the streaming side runner + step normalizer**

Add to `compare.py` (replace the old synchronous `_run_student_side` — delete it — and also delete the now-unused `_read_jsonl` helper that only it referenced; then add):

```python
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


async def _run_student_side_streaming(
    *, run_id: str, side: str, skill: str, skill_round: int, prompt: str, fixture_path: Path | None
):
    """Async generator. Yields raw student log-event dicts as they are written,
    then finally yields {"__result__": <side summary>}."""
    _ensure_distillation_imports()
    from runner.config import RunConfigV2
    from stages.student import run_student

    summary = data_loader.get_summary(skill)
    student_model = summary.get("student_model", "google/gemma-4-26b-a4b-it")
    work_root = Path(tempfile.mkdtemp(prefix=f"compare-{run_id}-{side}-"))
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
                user_prompt=prompt, skill_name=skill, skill_dir=skill_dir,
                model=student_model, config=config, max_retries=1,
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
    yield {"__result__": {
        "side": side, "skill_round": skill_round,
        "stop_reason": result.get("stop_reason", "unknown"),
        "iterations": result.get("iterations", 0),
        "duration_seconds": result.get("duration_seconds", 0.0),
        "token_usage": result.get("token_usage", {"prompt": 0, "completion": 0}),
        "output_files": result.get("output_files", []),
        "output_dir": str(output_dir),
        "log_file": str(result.get("log_file", "")),
    }}
```

- [ ] **Step 5: Add a live-artifact builder**

Add to `compare.py`:

```python
def _live_artifacts(run_id: str, side: str, summ: dict) -> list[dict]:
    """Convert the live side's output .docx → PDF and build artifact events."""
    _ensure_distillation_imports()
    from utils.converter import docx_to_pdf, find_docx

    out_dir = Path(summ["output_dir"])
    base = f"/api/compare/artifact?run_id={run_id}&side={side}"
    out: list[dict] = []
    docx = find_docx(out_dir) if out_dir.is_dir() else None
    if docx is not None:
        pdf = docx_to_pdf(docx)
        if pdf is not None:
            out.append({"side": side, "kind": "pdf", "label": docx.name,
                        "url": f"{base}&file={pdf.name}"})
        out.append({"side": side, "kind": "docx", "label": docx.name,
                    "url": f"{base}&file={docx.name}"})
    else:
        text_file = next((p for p in (out_dir.iterdir() if out_dir.is_dir() else [])
                          if p.suffix.lower() in {".txt", ".json", ".md"}), None)
        if text_file is not None:
            out.append({"side": side, "kind": "text", "label": text_file.name,
                        "text": text_file.read_text(encoding="utf-8", errors="replace")[:8000]})
    return out
```

- [ ] **Step 6: Rewrite `stream_live`**

Replace the whole `stream_live` function with:

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

        side_summaries: dict[str, dict] = {}
        for side, skill_round, phase in [("original", 0, "run_original"),
                                         ("peak", best_round, "run_peak")]:
            yield _event("status", {"phase": phase})
            async for ev in _run_student_side_streaming(
                run_id=run_id, side=side, skill=req.skill,
                skill_round=skill_round, prompt=prompt, fixture_path=fixture_path,
            ):
                if "__result__" in ev:
                    summ = ev["__result__"]
                    side_summaries[side] = summ
                    run.output_dirs[side] = summ["output_dir"]
                    for art in _live_artifacts(run_id, side, summ):
                        yield _event("artifact", art)
                else:
                    yield _event("step", _norm_step(side, ev))

        yield _event("status", {"phase": "judge"})
        result = _judge_live(
            skill=req.skill, prompt=prompt,
            original=side_summaries.get("original", {}),
            peak=side_summaries.get("peak", {}),
            student_model=student_model,
        )
        result["elapsed_s"] = round(time.time() - start, 2)
        yield _event("result", result)
        yield _event("status", {"phase": "done"})
        yield _event("complete", {"run_id": run_id})
    except Exception as e:  # noqa: BLE001
        yield _event("status", {"phase": "error"})
        yield _event("log", {"side": "system", "tag": "error", "line": f"{type(e).__name__}: {e}"})
        yield _event("complete", {"run_id": run_id})
```

- [ ] **Step 7: Run live test, verify it fails on judge image (next task) or passes via fake**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_compare_live_stream_streams_steps_and_judge -q
```
Expected: PASS (judge is monkeypatched). If `_judge_live` signature changed in Task 7 it stays compatible.

- [ ] **Step 8: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/services/compare.py demo-app/backend/tests/test_compare_routes.py
git commit -m "feat: stream live student steps in real time"
```

---

### Task 7: Image-based live judge

**Files:**
- Modify: `demo-app/backend/app/services/compare.py`
- Test: `demo-app/backend/tests/test_compare_routes.py`

- [ ] **Step 1: Write a judge-image unit test**

Append to `tests/test_compare_routes.py`:

```python
def test_build_judge_user_uses_images_when_docx(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.services import compare as compare_module

    # Fake docx_to_images to return one fake PNG; assert image blocks are built.
    png = tmp_path / "page_01.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(compare_module, "_render_side_images",
                        lambda summ: [png] if summ.get("output_files") else [])

    blocks = compare_module._build_judge_content(
        skill="docx", prompt="p",
        original={"output_files": ["x.docx"], "skill_round": 0, "stop_reason": "success"},
        peak={"output_files": ["y.docx"], "skill_round": 5, "stop_reason": "success"},
    )
    kinds = [b.get("type") for b in blocks]
    assert "image" in kinds  # at least one rendered page included
    assert "text" in kinds


def test_build_judge_user_text_fallback_when_no_docx(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import compare as compare_module

    monkeypatch.setattr(compare_module, "_render_side_images", lambda summ: [])
    blocks = compare_module._build_judge_content(
        skill="docx", prompt="p",
        original={"output_files": [], "skill_round": 0, "stop_reason": "success"},
        peak={"output_files": [], "skill_round": 5, "stop_reason": "success"},
    )
    assert all(b.get("type") == "text" for b in blocks)
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_build_judge_user_uses_images_when_docx tests/test_compare_routes.py::test_build_judge_user_text_fallback_when_no_docx -q
```
Expected: FAIL — `_build_judge_content` / `_render_side_images` undefined.

- [ ] **Step 3: Add image rendering + content builder; rewrite `_judge_live`**

In `demo-app/backend/app/services/compare.py`, add `import base64` to the stdlib imports.

Add these functions (place before `_judge_live`):

```python
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
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": data}}


def _side_text_summary(label: str, summ: dict) -> str:
    return (f"### {label}\n"
            f"skill_round={summ.get('skill_round')} stop_reason={summ.get('stop_reason')} "
            f"output_files={summ.get('output_files', [])}\n")


def _build_judge_content(*, skill: str, prompt: str, original: dict, peak: dict) -> list[dict]:
    """Build the judge `user` content blocks: text instructions + (images | text preview)."""
    blocks: list[dict] = [{
        "type": "text",
        "text": (f"Skill: {skill}\nTask prompt:\n{prompt}\n\n"
                 "Compare side A (original) vs side B (peak). "
                 "Below are each side's rendered output pages (or text summary).")
    }]
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
                    blocks.append({"type": "text",
                                   "text": f"{label} output {p.name}:\n"
                                           f"{p.read_text(encoding='utf-8', errors='replace')[:3000]}"})
    return blocks


def _judge_live(*, skill: str, prompt: str, original: dict, peak: dict, student_model: str) -> dict:
    _ensure_distillation_imports()
    from utils.llm_call import OPENROUTER_BASE_URL, call_llm

    system = (
        "You are judging an Arena comparison between two versions of the same agent skill. "
        "Return ONLY JSON with keys winner, score_original, score_peak, rationale. "
        "winner is original|peak|tie; scores are numbers 0..1."
    )
    content = _build_judge_content(skill=skill, prompt=prompt, original=original, peak=peak)
    start = time.time()
    raw, usage = call_llm(
        system=system, user=content, model=JUDGE_MODEL,
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=OPENROUTER_BASE_URL, max_tokens=1200, temperature=0,
    )
    parsed = _parse_judge_json(raw)
    parsed.update({
        "judge_model": JUDGE_MODEL, "student_model": student_model,
        "elapsed_s": round(time.time() - start, 2), "judge_usage": usage,
        "original_output_files": original.get("output_files", []),
        "peak_output_files": peak.get("output_files", []),
    })
    return parsed
```

Delete the old `_preview_output_files` and the old `_judge_live` body (superseded). Keep `_parse_judge_json` and `JUDGE_MODEL`.

- [ ] **Step 4: Run judge tests, verify pass**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest tests/test_compare_routes.py::test_build_judge_user_uses_images_when_docx tests/test_compare_routes.py::test_build_judge_user_text_fallback_when_no_docx -q
```
Expected: PASS.

- [ ] **Step 5: Run full backend suite**

Run:
```bash
/opt/anaconda3/envs/skills/bin/pytest -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/backend/app/services/compare.py demo-app/backend/tests/test_compare_routes.py
git commit -m "feat: image-based live compare judge"
```

---

### Task 8: Frontend types + artifact URL helper

**Files:**
- Modify: `demo-app/frontend/lib/types.ts`
- Modify: `demo-app/frontend/lib/api.ts`

- [ ] **Step 1: Add types**

Append to `demo-app/frontend/lib/types.ts`:

```ts
export type CompareStep = {
  side: "original" | "peak";
  kind: "start" | "cli_init" | "tool_call" | "tool_result" | "assistant_text" | "end" | "api_error" | string;
  iteration?: number | null;
  tool?: string | null;
  args?: { command?: string; description?: string; [k: string]: unknown } | null;
  result?: string | null;
  text?: string | null;
  stop_reason?: string | null;
  duration_seconds?: number | null;
  tokens?: { prompt?: number; completion?: number; total?: number } | null;
  ts?: string | null;
};

export type CompareArtifact = {
  side: "original" | "peak";
  kind: "pdf" | "docx" | "text" | "png";
  label: string;
  url?: string;
  text?: string;
};

export type CompareSideState = {
  steps: CompareStep[];
  artifacts: CompareArtifact[];
  status: "idle" | "running" | "done" | "error";
};
```

- [ ] **Step 2: Add artifact URL helper**

Append to `demo-app/frontend/lib/api.ts`:

```ts
export function compareArtifactUrl(path: string): string {
  // Backend emits root-relative artifact URLs (e.g. "/api/compare/...").
  return path.startsWith("http") ? path : `${BACKEND_URL}${path}`;
}
```

- [ ] **Step 3: Type-check**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
```
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/frontend/lib/types.ts demo-app/frontend/lib/api.ts
git commit -m "feat: add compare v2 step/artifact types"
```

---

### Task 9: `StepCard` component

**Files:**
- Create: `demo-app/frontend/app/compare/step-card.tsx`

- [ ] **Step 1: Create the component**

Create `demo-app/frontend/app/compare/step-card.tsx`:

```tsx
import type { CompareStep } from "@/lib/types";

export function StepCard({ step }: { step: CompareStep }) {
  const it = step.iteration != null ? `#${step.iteration}` : "";
  if (step.kind === "tool_call") {
    return (
      <div className="step step-tool">
        <div className="step-head"><span className="step-kind">tool · {step.tool}</span><span className="step-it">{it}</span></div>
        {step.args?.description && <div className="step-desc">{step.args.description}</div>}
        {step.args?.command && <pre className="step-code">{step.args.command}</pre>}
      </div>
    );
  }
  if (step.kind === "tool_result") {
    return (
      <details className="step step-result">
        <summary><span className="step-kind">result · {step.tool}</span><span className="step-it">{it}</span></summary>
        <pre className="step-code">{step.result}</pre>
      </details>
    );
  }
  if (step.kind === "assistant_text") {
    return (
      <div className="step step-assistant">
        <div className="step-head"><span className="step-kind">assistant</span><span className="step-it">{it}</span></div>
        <div className="step-text">{step.text}</div>
      </div>
    );
  }
  if (step.kind === "end") {
    return (
      <div className="step step-end">
        <span className="step-kind">end · {step.stop_reason}</span>
        <span className="muted"> {step.duration_seconds}s · {step.tokens?.total ?? "?"} tok</span>
      </div>
    );
  }
  if (step.kind === "start" || step.kind === "cli_init") {
    return <div className="step step-meta"><span className="step-kind">{step.kind}</span></div>;
  }
  return (
    <div className="step step-meta">
      <span className="step-kind">{step.kind}</span> <span className="muted">{step.text || step.result || ""}</span>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
```
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/frontend/app/compare/step-card.tsx
git commit -m "feat: add compare StepCard component"
```

---

### Task 10: `ArtifactView` component

**Files:**
- Create: `demo-app/frontend/app/compare/artifact-view.tsx`

- [ ] **Step 1: Create the component**

Create `demo-app/frontend/app/compare/artifact-view.tsx`:

```tsx
import { compareArtifactUrl } from "@/lib/api";
import type { CompareArtifact } from "@/lib/types";

export function ArtifactView({ artifacts }: { artifacts: CompareArtifact[] }) {
  const pdf = artifacts.find((a) => a.kind === "pdf");
  const docx = artifacts.find((a) => a.kind === "docx");
  const texts = artifacts.filter((a) => a.kind === "text");
  const png = artifacts.find((a) => a.kind === "png");

  return (
    <div className="artifact-view stack-sm">
      {pdf?.url && (
        <iframe className="artifact-pdf" src={compareArtifactUrl(pdf.url)} title={`Document ${pdf.label}`} />
      )}
      {!pdf && png?.url && (
        <img className="artifact-img" src={compareArtifactUrl(png.url)} alt={png.label} />
      )}
      {docx?.url && (
        <a className="btn btn-sm" href={compareArtifactUrl(docx.url)} download>
          Tải {docx.label}
        </a>
      )}
      {texts.map((t, i) => (
        <details key={i} className="artifact-text" open={i === 0}>
          <summary>{t.label}</summary>
          <pre>{t.text}</pre>
        </details>
      ))}
      {artifacts.length === 0 && <div className="muted">No output produced.</div>}
    </div>
  );
}
```

- [ ] **Step 2: Type-check + commit**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
```
Expected: No errors. Then:
```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/frontend/app/compare/artifact-view.tsx
git commit -m "feat: add compare ArtifactView (pdf/png/docx/text)"
```

---

### Task 11: `JudgeVerdict` + `ArenaColumn` components

**Files:**
- Create: `demo-app/frontend/app/compare/judge-verdict.tsx`
- Create: `demo-app/frontend/app/compare/arena-column.tsx`

- [ ] **Step 1: Create `judge-verdict.tsx`**

```tsx
import type { CompareResult } from "@/lib/types";

function fmt(v: number | null | undefined): string {
  return typeof v === "number" ? v.toFixed(3) : "n/a";
}

export function JudgeVerdict({ result }: { result: CompareResult | null }) {
  if (!result) return null;
  const label = result.winner === "peak" ? "Peak wins"
    : result.winner === "original" ? "Original wins" : "Tie";
  // Replay carries side payloads; live carries score_original/score_peak.
  const so = result.score_original ?? result.original?.hybrid_score;
  const sp = result.score_peak ?? result.peak?.hybrid_score;
  return (
    <section className="judge-verdict panel">
      <div className="panel-header">
        <h3 className="panel-title">Judge verdict</h3>
        <span className="badge badge-success">{label}</span>
      </div>
      <div className="panel-body stack-sm">
        <div className="row" style={{ gap: 16 }}>
          <span>A · original: <b>{fmt(so)}</b></span>
          <span>B · peak: <b>{fmt(sp)}</b></span>
          {result.judge_model && <span className="muted">judge {result.judge_model}</span>}
          {typeof result.elapsed_s === "number" && <span className="muted">{result.elapsed_s}s</span>}
        </div>
        {(result.rationale || result.peak?.judge_rationale) && (
          <p className="muted">{result.rationale || result.peak?.judge_rationale}</p>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Create `arena-column.tsx`**

```tsx
"use client";

import { useEffect, useRef } from "react";
import type { CompareResult, CompareSideState } from "@/lib/types";
import { ArtifactView } from "./artifact-view";
import { StepCard } from "./step-card";

function fmt(v: number | null | undefined): string {
  return typeof v === "number" ? v.toFixed(3) : "n/a";
}

export function ArenaColumn({
  title,
  mode,
  state,
  result,
  whichSide,
}: {
  title: string;
  mode: "replay" | "live";
  state: CompareSideState;
  result: CompareResult | null;
  whichSide: "original" | "peak";
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state.steps.length]);

  const side = result?.[whichSide];
  const liveScore = whichSide === "original" ? result?.score_original : result?.score_peak;

  return (
    <article className="arena-side panel">
      <div className="panel-header">
        <h3 className="panel-title">{title}</h3>
        <span className="badge">{state.status}</span>
      </div>
      <div className="panel-body stack-sm">
        <div className="grid-3">
          <div className="stat"><div className="stat-label">Hybrid</div><div className="stat-value">{fmt(side?.hybrid_score ?? liveScore)}</div></div>
          <div className="stat"><div className="stat-label">Rule</div><div className="stat-value">{fmt(side?.rule_score)}</div></div>
          <div className="stat"><div className="stat-label">Judge</div><div className="stat-value">{fmt(side?.llm_judge_score)}</div></div>
        </div>

        {mode === "live" && (
          <div ref={ref} className="step-timeline">
            {state.steps.length === 0 && <div className="muted">Waiting for steps…</div>}
            {state.steps.map((s, i) => <StepCard key={i} step={s} />)}
          </div>
        )}

        {state.artifacts.length > 0 && <ArtifactView artifacts={state.artifacts} />}

        {side?.rule_checks && (
          <div className="rule-list">
            {side.rule_checks.slice(0, 8).map((c) => (
              <div key={c.name} className="rule-row">
                <span className={c.passed ? "dot dot-ok" : "dot dot-bad"} />
                <span>{c.name}</span>
                <span>{fmt(c.score)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
```

- [ ] **Step 3: Type-check + commit**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
```
Expected: No errors. Then:
```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/frontend/app/compare/judge-verdict.tsx demo-app/frontend/app/compare/arena-column.tsx
git commit -m "feat: add compare JudgeVerdict + ArenaColumn"
```

---

### Task 12: Rewrite `compare-client.tsx`

**Files:**
- Modify: `demo-app/frontend/app/compare/compare-client.tsx`

- [ ] **Step 1: Replace the file**

Replace the entire contents of `demo-app/frontend/app/compare/compare-client.tsx` with:

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
  CompareArtifact,
  CompareCase,
  ComparePhase,
  CompareResult,
  CompareSideState,
  CompareStep,
} from "@/lib/types";
import { ArenaColumn } from "./arena-column";
import { JudgeVerdict } from "./judge-verdict";

type Props = { summaries: RealSummary[]; casesBySkill: Record<string, CompareCase[]> };
const SKILLS = ["docx", "internal-comms", "slack-gif-creator"] as const;
const EMPTY_SIDE: CompareSideState = { steps: [], artifacts: [], status: "idle" };

export function CompareClient({ summaries, casesBySkill }: Props) {
  const [skill, setSkill] = useState("docx");
  const [mode, setMode] = useState<"replay" | "live">("replay");
  const [promptMode, setPromptMode] = useState<"test_case" | "custom">("test_case");
  const [testCaseId, setTestCaseId] = useState(casesBySkill.docx?.[0]?.id || "");
  const [customPrompt, setCustomPrompt] = useState("");
  const [fixtureFile, setFixtureFile] = useState("");
  const [phase, setPhase] = useState<ComparePhase>("idle");
  const [original, setOriginal] = useState<CompareSideState>(EMPTY_SIDE);
  const [peak, setPeak] = useState<CompareSideState>(EMPTY_SIDE);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState("");
  const esRef = useRef<EventSource | null>(null);

  const summary = summaries.find((s) => s.skill === skill) || summaries[0];
  const cases = useMemo(() => casesBySkill[skill] || [], [casesBySkill, skill]);
  const activeCase = cases.find((c) => c.id === testCaseId) || cases[0];
  const fixtures = useMemo(() => {
    const seen = new Set<string>();
    for (const c of cases) for (const f of c.fixture_files) seen.add(f);
    return [...seen].sort();
  }, [cases]);

  const setSide = (s: "original" | "peak") => (s === "original" ? setOriginal : setPeak);

  function resetRun() {
    setOriginal(EMPTY_SIDE);
    setPeak(EMPTY_SIDE);
    setResult(null);
    setError("");
    setPhase("idle");
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
  }

  function attachStream(url: string) {
    const es = new EventSource(url);
    esRef.current = es;
    es.addEventListener("status", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as { phase: ComparePhase };
      setPhase(d.phase);
      if (d.phase === "run_original") setOriginal((p) => ({ ...p, status: "running" }));
      if (d.phase === "run_peak") {
        setOriginal((p) => (p.status === "running" ? { ...p, status: "done" } : p));
        setPeak((p) => ({ ...p, status: "running" }));
      }
      if (d.phase === "done" || d.phase === "error") {
        setOriginal((p) => ({ ...p, status: d.phase === "error" ? "error" : "done" }));
        setPeak((p) => ({ ...p, status: d.phase === "error" ? "error" : "done" }));
        es.close();
      }
    });
    es.addEventListener("step", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as CompareStep;
      setSide(d.side)((p) => ({ ...p, steps: [...p.steps, d] }));
    });
    es.addEventListener("artifact", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as CompareArtifact;
      setSide(d.side)((p) => ({ ...p, artifacts: [...p.artifacts, d] }));
    });
    es.addEventListener("result", (e) => {
      setResult(JSON.parse((e as MessageEvent).data) as CompareResult);
    });
    es.addEventListener("complete", () => es.close());
    es.onerror = () => { setError("Stream closed. Is the backend running?"); es.close(); };
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

  const canRun = mode === "replay" || promptMode === "test_case" || customPrompt.trim().length > 0;
  const running = phase !== "idle" && phase !== "done" && phase !== "error";

  return (
    <div className="page stack-lg">
      <section className="compare-header">
        <div>
          <div className="eyebrow">Arena Compare</div>
          <h1 className="h1"><Bi vi="So sánh skill original với skill peak." en="Compare original vs peak skill." /></h1>
          <p className="muted" style={{ maxWidth: 760 }}>
            <Bi vi="Replay hiện artifact thật; Live chạy 2 version skill, stream từng bước rồi judge."
                en="Replay shows real artifacts; Live runs both versions, streams each step, then judges." />
          </p>
        </div>
        <div className="compare-status"><span className="badge">{phase}</span></div>
      </section>

      <section className="compare-controls">
        <label>Skill
          <select className="select" value={skill} onChange={(e) => {
            const next = e.target.value; setSkill(next);
            setTestCaseId(casesBySkill[next]?.[0]?.id || ""); resetRun();
          }}>
            {SKILLS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <div className="segmented">
          <button className={mode === "replay" ? "active" : ""} onClick={() => setMode("replay")}>Replay</button>
          <button className={mode === "live" ? "active" : ""} onClick={() => setMode("live")}>Live judge</button>
        </div>
        <label>Test case
          <select className="select" value={activeCase?.id || ""} onChange={(e) => setTestCaseId(e.target.value)}>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}
          </select>
        </label>
        <button className="btn btn-primary" disabled={!canRun || running} onClick={runCompare}>
          <Icon name="play" size={16} />{mode === "replay" ? "Replay comparison" : "Run live arena"}
        </button>
      </section>

      {mode === "live" && (
        <section className="compare-live-controls">
          <div className="segmented">
            <button className={promptMode === "test_case" ? "active" : ""} onClick={() => setPromptMode("test_case")}>Existing test case</button>
            <button className={promptMode === "custom" ? "active" : ""} onClick={() => setPromptMode("custom")}>Custom prompt</button>
          </div>
          {promptMode === "custom" && (
            <textarea className="textarea" value={customPrompt} onChange={(e) => setCustomPrompt(e.target.value)} aria-label="Custom prompt" />
          )}
          <label>Fixture
            <select className="select" value={fixtureFile} onChange={(e) => setFixtureFile(e.target.value)}>
              <option value="">No fixture / auto from test case</option>
              {fixtures.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </label>
        </section>
      )}

      <section className="compare-prompt panel">
        <div className="panel-header"><h3 className="panel-title">Prompt</h3><span className="badge">best R{summary.best_round}</span></div>
        <div className="panel-body"><p>{promptMode === "custom" && customPrompt.trim() ? customPrompt : activeCase?.prompt}</p></div>
      </section>

      {error && <div className="compare-error">{error}</div>}

      <section className="arena-grid">
        <ArenaColumn title="A · Original Skill (R0)" mode={mode} state={original} result={result} whichSide="original" />
        <ArenaColumn title={`B · Peak Skill R${summary.best_round}`} mode={mode} state={peak} result={result} whichSide="peak" />
      </section>

      <JudgeVerdict result={result} />
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
```
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/frontend/app/compare/compare-client.tsx
git commit -m "feat: arena two-column compare client with step streaming"
```

---

### Task 13: Styles for timeline + step cards

**Files:**
- Modify: `demo-app/frontend/app/globals.css`

- [ ] **Step 1: Append styles**

Append to `demo-app/frontend/app/globals.css` (the existing compare styles already define `.compare-*`, `.arena-grid`, `.segmented`, `.rule-*`, `.dot-*`):

```css
.step-timeline {
  max-height: 420px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
}

.step {
  border: 1px solid var(--line);
  background: var(--surface-2);
  padding: 8px;
}

.step-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.step-kind {
  font-family: var(--font-mono);
  font-weight: 600;
}

.step-it {
  color: var(--fg-subtle);
  font-family: var(--font-mono);
}

.step-desc {
  margin-top: 4px;
}

.step-code {
  margin-top: 6px;
  padding: 6px 8px;
  background: var(--surface);
  border: 1px solid var(--line);
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
}

.step-assistant .step-text {
  margin-top: 4px;
  white-space: pre-wrap;
}

.step-tool { border-left: 3px solid var(--primary); }
.step-assistant { border-left: 3px solid var(--success); }
.step-end { border-left: 3px solid var(--fg-subtle); }

.artifact-pdf {
  width: 100%;
  height: 480px;
  border: 1px solid var(--line);
  background: var(--surface);
}

.artifact-img {
  width: 100%;
  border: 1px solid var(--line);
}

.artifact-text pre {
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--surface-2);
  padding: 8px;
}

.btn-sm {
  min-height: 30px;
  padding: 0 10px;
  font-size: 12px;
}
```

- [ ] **Step 2: Type-check + lint + build**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit
pnpm exec eslint app/compare components/sidebar.tsx lib/types.ts lib/api.ts
pnpm build
```
Expected: tsc clean; new compare files lint-clean; build succeeds with `/compare` as a dynamic route.

- [ ] **Step 3: Commit**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app/frontend/app/globals.css
git commit -m "feat: arena timeline + step-card + artifact styles"
```

---

### Task 14: End-to-end verification

**Files:** none unless a defect is found.

- [ ] **Step 1: Backend suite**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/pytest -q
```
Expected: all pass.

- [ ] **Step 2: Frontend checks**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/frontend
pnpm exec tsc --noEmit && pnpm build
```
Expected: tsc clean; build OK.

- [ ] **Step 3: Replay HTTP smoke (artifact events)**

Run:
```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app/backend
/opt/anaconda3/envs/skills/bin/uvicorn app.main:app --port 8000 >/tmp/cmp.log 2>&1 &
UV=$!; sleep 3
RID=$(curl -s -X POST localhost:8000/api/compare/replay -H 'Content-Type: application/json' -d '{"skill":"docx","test_case_id":"tc_a01"}' | /opt/anaconda3/envs/skills/bin/python -c 'import json,sys;print(json.load(sys.stdin)["run_id"])')
curl -sN "localhost:8000/api/compare/replay/$RID/stream" | grep -E '^event:' | sort | uniq -c
# Expect: status, artifact, result, complete, log
curl -s "localhost:8000/api/compare/docx/artifact?round=1&batch=1&tc=tc_a01&file=document.pdf" -o /tmp/doc.pdf -w '%{content_type}\n'
# Expect: application/pdf (requires soffice)
kill $UV
```
Expected: `artifact` events present; PDF served as `application/pdf`.

- [ ] **Step 4: Browser smoke (manual)**

```bash
cd /Users/soc_036/study_dir/skill_distillation/demo-app && make dev
```
Open `http://localhost:3000/compare`:
- Replay: two columns show PDF iframe + checks; judge verdict banner appears.
- Live (with `OPENROUTER_API_KEY` in `.env`): step cards stream into each column in real time, then PDF + judge verdict.

- [ ] **Step 5: Final commit (only if verification required fixes)**

```bash
cd /Users/soc_036/study_dir/skill_distillation
git add demo-app
git commit -m "fix: polish arena compare v2 verification"
```
If no edits were needed, do not create an empty commit.

---

## Notes for the implementer

- **No changes to `distillation_v2/` runner code** beyond the additive `docx_to_pdf` wrapper in `converter.py`. Live streaming works by tailing the JSONL the existing `AgentLogger` already writes (it flushes per line).
- `STABLE_DIR` is read-only — replay PDFs are cached under `tempfile.gettempdir()/compare-pdf-cache`, never written back into stable.
- Live mode needs `OPENROUTER_API_KEY` (now loaded from repo `.env`) and `soffice` (LibreOffice) for PDF/image rendering; conversion failures degrade gracefully (text-only judge, no PDF).
- Pre-commit reformats Python (ruff) — if a commit aborts with "files were modified", re-run `git add -A` and the same commit command.
- Pre-existing ESLint errors in `run-client.tsx` / `language-provider.tsx` / `theme-provider.tsx` are out of scope; lint only the compare files.
```
