# Arena Compare v2 — Side-by-Side Step Streaming Design

## Context

`/compare` already exists (see `2026-05-27-arena-compare-design.md`). It compares the
original skill (`SKILL_round_0.md`) against the distilled peak skill
(`SKILL_round_{best_round}.md`) in replay + live modes over SSE.

This v2 redesign makes the page feel like an LLM arena (e.g. arena.ai side-by-side):
two columns, each showing one skill version's run **step by step**, plus an in-browser
view of the produced document. It also fixes a live-mode env bug.

Goals:

1. Fix `400 OPENROUTER_API_KEY is required` — backend never loads `.env`.
2. Stream each student step (tool call / tool result / assistant text) to the UI **in
   real time** during live runs, using the existing student JSONL log shape.
3. Show the live **judge** verdict (image-based when possible, matching the pipeline).
4. Show the produced `.docx` **in the browser** (PDF inline) + download, plus the
   stored rendered output for replay.
5. Lay the UI out as two side-by-side arena columns with a per-step timeline.

Non-goals (out of scope): token-by-token streaming of the judge call, file upload for
custom fixtures, batch comparison across all test cases, persisting live results.

## Student log shape (source of truth for steps)

`distillation_v2` student runs emit one JSONL record per event via `AgentLogger`
(written incrementally to `config.log_dir`). Verified shape:

```jsonc
{"event":"start",        "skill":"docx","model":"...","prompt":"...","ts":"..."}
{"event":"cli_init",     "iteration":0,"session_id":"...","ts":"..."}
{"event":"tool_call",    "iteration":1,"tool":"Bash","args":{"command":"...","description":"..."},"ts":"..."}
{"event":"tool_result",  "iteration":1,"tool":"Bash","result":"...","ts":"..."}
{"event":"assistant_text","iteration":2,"text":"...","ts":"..."}
{"event":"end",          "iterations":2,"stop_reason":"success","duration_seconds":85.13,"tokens":{"prompt":..,"completion":..,"total":..},"ts":"..."}
```

The UI renders `tool_call`/`tool_result`/`assistant_text` as a timeline; `start`/`end`
drive status; `cli_init` is informational.

**Replay has no stored per-test-case student JSONL.** `STABLE_DIR/{skill}/round_{r}/batch_{b}/{tc}/`
holds artifacts (`agent_final.md`, output `.docx`, `page_*.png`) and per-batch
`scores.json`/`run_log.md`, but no structured student log. Therefore the step timeline
is a **live-only** feature; replay shows the stored artifacts instead (decided with the
user — no synthetic steps).

## Environment fix

`demo-app/backend/app/config.py`: load the repo-root `.env` at import time, mirroring
`distillation_v2/runner/config.py`:

```python
from dotenv import load_dotenv
load_dotenv(DISTILL_REPO_ROOT / ".env")
```

`python-dotenv` is already installed in the `skills` conda env. After this, the backend
process sees `OPENROUTER_API_KEY` and live mode passes its pre-flight check. Replay mode
is unaffected.

## SSE protocol (v2)

Replace the raw `jsonl` dump with a typed, side-tagged `step` event. Phases unchanged.

```txt
event: status   data: { "phase": "queued"|"run_original"|"run_peak"|"judge"|"done"|"error" }

event: step     data: {
  "side": "original" | "peak",
  "kind": "start"|"cli_init"|"tool_call"|"tool_result"|"assistant_text"|"end",
  "iteration": number,
  "tool": string?,            // tool_call / tool_result
  "args": object?,            // tool_call ({command, description, ...})
  "result": string?,          // tool_result (truncated server-side to ~4 KB)
  "text": string?,            // assistant_text
  "stop_reason": string?,     // end
  "duration_seconds": number?,// end
  "tokens": object?,          // end
  "ts": string
}

event: artifact data: {       // emitted once per side after its run completes
  "side": "original" | "peak",
  "kind": "pdf"|"docx"|"text"|"png",
  "label": string,            // file name
  "url": string?,             // artifact endpoint URL (pdf/docx/png)
  "text": string?,            // inline text content (read-workflow output / agent_final.md)
  "round": number, "batch": number?, "test_case_id": string?
}

event: log      data: { "side": "system"|"original"|"peak"|"judge", "tag": string, "line": string }
event: result   data: CompareResult        // replay result or live judge verdict
event: complete data: { "run_id": string }
```

Replay emits `status` + `artifact` (per side) + `result`. Live emits `status` + `step`
(streamed) + `artifact` (per side, after each run) + judge `result`.

## Backend

### Artifact location + serving

Map a replay side to its artifact directory:

```
STABLE_DIR / {skill} / round_{round} / batch_{batch} / {test_case_id}/
```

`round` and `batch` come from the matched `eval_detail.jsonl` row (it carries both).
`eval_detail.output_dir` is a stale relative path and must NOT be used for disk access.

New helper in `data_loader.py`:

```python
def get_artifact_dir(skill, round_n, batch, test_case_id) -> Path  # validated, under STABLE_DIR
```

New endpoint serves files from a validated artifact dir (replay) or a live run's temp
output dir (live), with path-traversal protection (resolve + `relative_to` check):

```txt
GET /api/compare/artifact?run_id=&side=&file=        # live: served from run temp dir
GET /api/compare/{skill}/artifact?round=&batch=&tc=&file=   # replay: served from STABLE_DIR
```

Behavior by file type:
- `*.pdf` → `application/pdf` (inline). Converted on demand from the `.docx` and cached
  in a **backend cache dir outside `STABLE_DIR`** (e.g. `tempfile.gettempdir()/compare-pdf-cache/{skill}/r{round}/b{batch}/{tc}.pdf`),
  keyed by side. `STABLE_DIR` is read-only — never write conversion output back into it.
  For live, the PDF is produced inside the run's temp output dir (already writable).
- `*.docx` → `Content-Disposition: attachment` download.
- `*.png` → `image/png` (stored replay render fallback; read directly from `STABLE_DIR`).
- `*.txt/.json/.md` → returned inline as text in the `artifact` event, not via this
  endpoint.

Live artifact lookup: `create_live_run` records each side's output dir on the
`CompareRun` registry entry (`output_dirs: {side: Path}`), set when each side finishes.
The live artifact endpoint resolves `(run_id, side)` → that dir, then validates `file`
against it. Live temp dirs are retained for the session so artifacts stay served
(demo scale; consistent with the runner's `sandbox_keep_on_fail`).

### DOCX → PDF / PNG (reuse `utils/converter.py`)

`converter.py` already does soffice-based conversion with profile isolation + retries.
Add one public wrapper (keeps the PDF, unlike `docx_to_images` which deletes it):

```python
def docx_to_pdf(docx_path: Path) -> Path | None:
    return _convert_to_pdf_with_retry(docx_path)
```

- PDF view: `docx_to_pdf(find_docx(output_dir))`, cache the result path (replay → backend
  cache dir outside `STABLE_DIR`; live → the run's writable temp dir).
- Image judge: `docx_to_images(docx_path)` → PNG paths (existing).
- `find_docx(output_dir)` (existing) locates the produced `.docx`.

Conversion failures are non-fatal: fall back to stored `page_*.png` (replay) or to
text-only judging (live), matching the pipeline's degrade-gracefully behavior.

### Live mode — real-time step streaming

The student runner is blocking (Claude Code CLI subprocess) and writes its JSONL log
incrementally. Stream by **tailing that file** from the async SSE generator while the
runner thread executes. No changes to `distillation_v2/` runner code.

Refactor the side runner into a streaming seam (testable, monkeypatchable):

```python
async def _run_student_side_streaming(*, run_id, side, skill, skill_round, prompt, fixture_path):
    """Async generator. Yields student events (dicts, log shape) as they are written,
    then finally yields {"__result__": <side summary dict>}."""
    # 1. materialize skill version (existing _materialize_skill_version)
    # 2. start run_student(...) in a worker thread (asyncio.to_thread / executor)
    # 3. poll the per-side log_dir for the new .jsonl; tail new lines;
    #    parse + yield each as an event; sleep ~0.3s between polls
    # 4. when the thread completes, drain remaining lines, then yield {"__result__": summary}
```

`stream_live` consumes this generator, wraps each event as a `step` SSE (adding `side`),
then after both sides finish:
- convert each side's output `.docx` → PDF (emit `artifact`),
- call the judge, emit `result`.

The existing test seam stays: tests monkeypatch `_run_student_side_streaming` with a fake
async generator (yields a few events + a `__result__`), and `_judge_live` with a fake.

Side summary dict (the `__result__`) keeps the current fields: `side, skill_round,
stop_reason, iterations, duration_seconds, token_usage, output_files, log_file` plus
`output_dir` (temp dir, for artifact serving).

### Live judge — image-based when possible

Match the pipeline's image-based judging. In `_judge_live`:
- If a side produced a `.docx`: render to PNG(s) via `docx_to_images`, base64-encode,
  and include as image content blocks (the existing `call_llm` already supports
  Anthropic-style `{"type":"image",...}` blocks → routed to OpenRouter image_url).
- Otherwise (read workflow → `output.txt/json`): include the text preview (current
  behavior).
- Keep returning the same `CompareResult` shape (`winner, score_original, score_peak,
  rationale, judge_model, student_model, elapsed_s, *_output_files`), plus per-side
  `artifact` URLs so the UI can show each side's document next to the verdict.

Judge stays a single non-streaming `call_llm`; the UI shows a "judging…" status then the
verdict card. (Token-level judge streaming is out of scope.)

## Frontend (arena layout)

Split the monolithic `compare-client.tsx` into focused pieces (each < 200 lines):

- `compare-client.tsx` — state, controls, SSE wiring, routes `step`/`artifact` events to
  the correct side.
- `arena-column.tsx` — one side: header (label, `R{skill_md_round}`, status, score), then
  either a live **step timeline** or a replay **artifact view**.
- `step-card.tsx` — renders one step by `kind`: `tool_call` (tool name + command +
  description), `tool_result` (collapsible truncated output), `assistant_text` (markdown
  text), `end` (stop_reason + duration + tokens).
- `artifact-view.tsx` — PDF `<iframe>` for `.docx`/`pdf`, text panel for `text`, `<img>`
  for `png`; a "Tải .docx" download button when a docx URL is present.
- `judge-verdict.tsx` — winner banner + scores + rationale.

Layout (top → bottom):
1. Header + controls (skill / mode / test case / live prompt + fixture) — unchanged.
2. Shared prompt panel.
3. **Two columns**: A · Original (R0) | B · Peak (R{best_round}).
   - Live: step timeline streaming in real time; artifact view appears when the side ends.
   - Replay: artifact view (PDF iframe + final text + checks + scores) immediately.
4. Judge verdict banner (appears at `judge`/`done`).

State per side: `steps: StepEvent[]`, `artifacts: ArtifactEvent[]`, `status`. The client
appends incoming `step`/`artifact` events to the matching side. Timeline auto-scrolls
(reuse the run page's stick-to-bottom pattern).

New types in `lib/types.ts`: `CompareStep`, `CompareArtifact`, `CompareSideState`. New
API helpers unchanged from v1 (`createCompareReplayRun`, `createCompareLiveRun`,
`compareReplayStreamUrl`, `compareLiveStreamUrl`) plus an `compareArtifactUrl(...)`
builder.

## Error handling

- Live without `OPENROUTER_API_KEY`: still 400 before streaming (now satisfied via
  `.env`).
- soffice/conversion failure: emit a `log` line, fall back to PNG (replay) or text judge
  (live); never abort the stream.
- One side fails (`runner_error`/`timeout`): still emit its `end` step + run the judge
  with available metadata so the verdict can explain the failure.
- Stream/exception: emit `status:error` + a `log` error line + `complete` (current
  pattern preserved).
- Artifact endpoint: 404 for unknown file, 400 for path escaping the allowed root.

## Testing

Backend (`tests/test_compare_routes.py`):
- `step` event contract for replay (artifact events present, no fake steps) and live
  (via fake `_run_student_side_streaming` async generator + fake `_judge_live`).
- `get_artifact_dir` maps round/batch/tc correctly and rejects traversal.
- Artifact endpoint: PDF content-type (mock conversion), docx download disposition,
  text inline, 404/400 paths.
- `_parse_judge_json` unit tests (existing) retained.
- Judge image fallback: when no docx, judge receives text (assert call args via monkeypatch).

Frontend: `tsc --noEmit` clean, new files lint-clean, `next build` succeeds; step events
route to the correct column (light component test or manual smoke).

Manual: `make dev` → `/compare`; replay shows PDF + checks; live (with key) streams
tool-call steps live then shows the verdict.

## Out of scope

- Token-by-token judge streaming.
- File upload for custom fixtures.
- Batch / all-test-case comparison.
- Persisting live runs back into `distillation_v2/results/stable`.
