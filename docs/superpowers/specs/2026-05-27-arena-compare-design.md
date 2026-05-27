# Arena Compare Page Design

## Goal

Add a new demo page at `/compare` that presents an Arena-style comparison between an original skill and its best distilled version.

The page must support two modes:

- Replay mode: uses existing stable result files and streams realistic JSONL/API-call logs so the demo feels like a live run without spending credits.
- Live mode: runs the same prompt through both skill versions using the real student model/API path, then calls the real judge model to compare the outputs.

The Sonnet 4.6 comparison idea is out of scope. This page compares skill versions, not Claude ceiling performance.

## Comparison Target

For a selected `skill`:

- Side A is the original skill: `SKILL_round_0.md`.
- Side B is the distilled peak skill: `SKILL_round_{summary.best_round}.md`.
- Existing test-case baseline score for Side A is taken from round 1 because `eval_detail.jsonl` starts at round 1.
- Existing test-case peak score for Side B is taken from `summary.best_round`.

Supported skills remain:

- `docx`
- `internal-comms`
- `slack-gif-creator`

## Route

Add a frontend route:

```txt
/compare
```

Add a sidebar item:

- Vietnamese: `So sánh`
- English: `Compare`

Default selection:

- skill: `docx`
- prompt source: existing test case
- test case: first available case for `docx`
- mode: Replay

## UI Layout

The page uses an Arena-style layout:

- A control bar at the top.
- A full-width prompt panel below the controls.
- Two side-by-side result columns:
  - A: Original Skill
  - B: Peak Skill
- A log console below or between the prompt and result columns.
- A winner banner once replay/live run completes.

Controls:

- Skill selector.
- Mode segmented control: `Replay` / `Live`.
- Prompt source segmented control in Live mode: `Existing test case` / `Custom prompt`.
- Existing test-case selector.
- Custom prompt textarea.
- Optional fixture dropdown populated from known fixture files in the selected skill's test cases.
- Run button:
  - `Replay comparison` in Replay mode.
  - `Run live arena` in Live mode.

Each side column shows:

- Version label: `SKILL_round_0.md` or `SKILL_round_{best_round}.md`.
- Hybrid score when available.
- Rule score when available.
- LLM judge score when available.
- Rule checks.
- Judge rationale.
- Output directory or generated output files.

## Replay Mode

Replay mode does not call external APIs.

Backend behavior:

- Read `summary.json` for the selected skill.
- Read `eval_detail.jsonl`.
- Read `api_calls.jsonl`.
- Find the selected test case in round 1 and best round.
- Stream events over SSE.

Replay SSE phases:

```txt
queued -> run_original -> run_peak -> judge -> done
```

Replay SSE events:

```txt
event: status
data: { "phase": "queued" | "run_original" | "run_peak" | "judge" | "done" | "error" }

event: log
data: { "side": "system" | "original" | "peak" | "judge", "line": string, "tag": string }

event: jsonl
data: { "source": "api_calls" | "eval_detail", "side": "original" | "peak" | "judge", "record": object }

event: result
data: CompareReplayResult

event: complete
data: { "run_id": string }
```

The UI renders `jsonl` events as expandable JSON rows in the log console. This makes the replay look like an actual model/API run while still being deterministic.

Winner logic in replay mode:

- Compare `hybrid_score` from round 1 and best round for the same test case.
- `peak` wins if it exceeds original by at least `0.02`.
- `original` wins if it exceeds peak by at least `0.02`.
- Otherwise, result is `tie`.

## Live Mode

Live mode calls real APIs and can take minutes.

Live prompt modes:

- Existing test case: use the selected test case prompt and its fixture metadata.
- Custom prompt: use the textarea prompt and an optional fixture selected from known fixtures. File upload is intentionally out of scope for the first implementation.

Backend behavior:

1. Create a live compare run id.
2. Materialize two temporary skill folders:
   - original: selected skill folder with `SKILL.md` replaced by `SKILL_round_0.md`
   - peak: selected skill folder with `SKILL.md` replaced by `SKILL_round_{best_round}.md`
3. Run the student model once against the original version.
4. Run the student model once against the peak version.
5. Stream the real runner JSONL/tool events to the frontend as they happen.
6. Call judge model `anthropic/claude-haiku-4-5` via OpenRouter to compare the two outputs.
7. Stream the final winner and rationale.

The temporary skill folders are copied from `distillation_v2/skills/<skill>` so scripts/assets stay intact. Only `SKILL.md` changes between the two sides.

Student model:

- Use `summary.student_model` for the selected skill.

Judge model:

- Use `anthropic/claude-haiku-4-5` through OpenRouter, matching the existing pipeline judge.

Live SSE phases:

```txt
queued -> run_original -> run_peak -> judge -> done
```

Live SSE events mirror replay events but `jsonl` records come from actual runner logs.

Live result shape:

```ts
type LiveCompareResult = {
  winner: "original" | "peak" | "tie";
  score_original: number;
  score_peak: number;
  rationale: string;
  judge_model: "anthropic/claude-haiku-4-5";
  student_model: string;
  elapsed_s: number;
  original_output_files: string[];
  peak_output_files: string[];
};
```

## Backend API

Add compare routes:

```txt
GET  /api/compare/{skill}/cases
POST /api/compare/replay
GET  /api/compare/replay/{run_id}/stream
POST /api/compare/live
GET  /api/compare/live/{run_id}/stream
```

`GET /api/compare/{skill}/cases` returns test case metadata and available fixture files:

```ts
type CompareCase = {
  id: string;
  workflow: string;
  name: string;
  prompt: string;
  expected_behavior: string;
  fixture_files: string[];
};
```

`POST /api/compare/replay` body:

```ts
{
  skill: "docx" | "internal-comms" | "slack-gif-creator";
  test_case_id: string;
}
```

`POST /api/compare/live` body:

```ts
{
  skill: "docx" | "internal-comms" | "slack-gif-creator";
  prompt_mode: "test_case" | "custom";
  test_case_id?: string;
  custom_prompt?: string;
  fixture_file?: string;
}
```

## Error Handling

Replay mode:

- Unknown skill returns 404 or 422.
- Missing test case returns 404.
- Missing stable files returns a readable `error` SSE event.

Live mode:

- Missing `OPENROUTER_API_KEY` returns 400 before starting the stream.
- Missing Claude CLI or runner failure produces `error` SSE events and keeps partial logs visible.
- If one side fails and the other succeeds, still call judge with available failure metadata so the result can explain the failure.
- If both sides fail before producing usable output, mark winner as `tie` with a failure rationale.

## Testing

Backend tests:

- Compare cases endpoint returns known test cases and fixture files.
- Replay run creates a run id.
- Replay stream emits status, jsonl, result, and complete events.
- Replay winner logic handles peak win, original win, and tie.
- Live run validates missing API key without calling external services.
- Live stream can be unit-tested with monkeypatched runner and judge calls.

Frontend verification:

- Type-check with `pnpm exec tsc --noEmit`.
- Ensure `/compare` renders with default `docx` data.
- Ensure Replay button streams logs and reveals the result.
- Ensure Live mode disables run until prompt requirements are met.

## Out Of Scope

- Claude Sonnet 4.6 comparison.
- File upload for custom prompt fixtures.
- Full batch comparison across all test cases.
- Re-running the full distillation pipeline.
- Persisting live run results back into `distillation_v2/results/stable`.
