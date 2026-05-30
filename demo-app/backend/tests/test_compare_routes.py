"""Tests for /api/compare routes and compare data helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import STABLE_DIR
from app.services import data_loader

requires_stable = pytest.mark.skipif(
    not STABLE_DIR.exists(),
    reason=f"distillation_v2 stable dir missing at {STABLE_DIR}",
)


def _docx_artifacts_present() -> bool:
    """True only when per-test-case artifact dirs are on disk.

    CI commits the lightweight stable files (summary.json, eval_detail.jsonl,
    SKILL_round_*.md) but NOT the heavy per-test-case outputs
    (round_N/batch_M/tc/*.docx + rendered PNGs). Tests that need those real
    files must skip when they're absent.
    """
    base = STABLE_DIR / "docx"
    return base.exists() and any(base.glob("round_1/batch_*/tc_a01"))


requires_docx_artifacts = pytest.mark.skipif(
    not _docx_artifacts_present(),
    reason="stable docx per-test-case artifact dirs not present (e.g. CI without rendered outputs)",
)


@requires_stable
def test_compare_cases_returns_prompt_and_fixtures(client: TestClient) -> None:
    r = client.get("/api/compare/docx/cases")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) > 0
    first = body[0]
    assert {
        "id",
        "workflow",
        "name",
        "prompt",
        "expected_behavior",
        "fixture_files",
    } <= set(first)
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
    r = client.post(
        "/api/compare/replay", json={"skill": "docx", "test_case_id": "tc_a01"}
    )
    assert r.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{12}", r.json()["run_id"])


@requires_stable
@requires_docx_artifacts
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


def test_compare_live_requires_api_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = client.post(
        "/api/compare/live",
        json={"skill": "docx", "prompt_mode": "test_case", "test_case_id": "tc_a01"},
    )
    assert r.status_code == 400
    assert "OPENROUTER_API_KEY" in r.json()["detail"]


def test_compare_live_custom_requires_prompt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    r = client.post(
        "/api/compare/live",
        json={"skill": "docx", "prompt_mode": "custom", "custom_prompt": "   "},
    )
    assert r.status_code == 422


@requires_stable
def test_compare_live_rejects_unknown_fixture(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
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


@requires_stable
def test_compare_live_stream_streams_steps_and_judge(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import compare as compare_module

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    async def fake_side_stream(
        *, run_id, side, skill, skill_round, prompt, fixture_path
    ):
        yield {"event": "start", "skill": skill, "model": "m", "prompt": prompt}
        yield {
            "event": "tool_call",
            "iteration": 1,
            "tool": "Bash",
            "args": {"command": "ls", "description": "list"},
        }
        yield {"event": "tool_result", "iteration": 1, "tool": "Bash", "result": "ok"}
        yield {"event": "assistant_text", "iteration": 2, "text": "done"}
        yield {
            "event": "end",
            "iterations": 2,
            "stop_reason": "success",
            "duration_seconds": 1.0,
            "tokens": {"prompt": 1, "completion": 1},
        }
        yield {
            "__result__": {
                "side": side,
                "skill_round": skill_round,
                "stop_reason": "success",
                "iterations": 2,
                "duration_seconds": 1.0,
                "token_usage": {"prompt": 1, "completion": 1},
                "output_files": [],
                "output_dir": "/tmp/x",
                "log_file": "",
            }
        }

    def fake_judge(*, skill, prompt, original, peak, student_model):
        return {
            "winner": "peak",
            "score_original": 0.6,
            "score_peak": 0.9,
            "rationale": "peak better",
            "judge_model": "anthropic/claude-haiku-4-5",
            "student_model": student_model,
            "elapsed_s": 0.5,
            "original_output_files": [],
            "peak_output_files": [],
        }

    monkeypatch.setattr(compare_module, "_run_student_side_streaming", fake_side_stream)
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
    assert "step" in events
    assert "result" in events
    assert events[-1] == "complete"
    step_sides = {d["side"] for e, d in parsed if e == "step"}
    assert step_sides == {"original", "peak"}
    kinds = {d["kind"] for e, d in parsed if e == "step"}
    assert {"tool_call", "tool_result", "assistant_text"} <= kinds
    result = next(d for e, d in parsed if e == "result")
    assert result["winner"] == "peak" and result["score_peak"] == 0.9


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


def test_backend_loads_repo_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    import app.config as config_mod

    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=test-sentinel\n")
    monkeypatch.setenv("DISTILL_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    importlib.reload(config_mod)
    try:
        assert os.getenv("OPENROUTER_API_KEY") == "test-sentinel"
    finally:
        monkeypatch.undo()
        importlib.reload(config_mod)  # restore config to the real repo root


@requires_stable
def test_eval_entry_carries_batch() -> None:
    entry = data_loader.get_eval_entry("docx", round_n=1, test_case_id="tc_a01")
    assert isinstance(entry["batch"], int)
    assert entry["batch"] >= 1


@requires_stable
@requires_docx_artifacts
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


def test_build_judge_user_uses_images_when_docx(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.services import compare as compare_module

    png = tmp_path / "page_01.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(
        compare_module,
        "_render_side_images",
        lambda summ: [png] if summ.get("output_files") else [],
    )

    blocks = compare_module._build_judge_content(
        skill="docx",
        prompt="p",
        original={
            "output_files": ["x.docx"],
            "skill_round": 0,
            "stop_reason": "success",
        },
        peak={"output_files": ["y.docx"], "skill_round": 5, "stop_reason": "success"},
    )
    kinds = [b.get("type") for b in blocks]
    assert "image" in kinds  # at least one rendered page included
    assert "text" in kinds


def test_build_judge_user_text_fallback_when_no_docx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import compare as compare_module

    monkeypatch.setattr(compare_module, "_render_side_images", lambda summ: [])
    blocks = compare_module._build_judge_content(
        skill="docx",
        prompt="p",
        original={"output_files": [], "skill_round": 0, "stop_reason": "success"},
        peak={"output_files": [], "skill_round": 5, "stop_reason": "success"},
    )
    assert all(b.get("type") == "text" for b in blocks)
