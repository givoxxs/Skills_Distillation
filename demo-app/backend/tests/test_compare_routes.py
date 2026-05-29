"""Tests for /api/compare routes and compare data helpers."""

from __future__ import annotations

import json
import re

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
def test_compare_live_stream_uses_runner_and_judge(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import compare as compare_module

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    def fake_run_side(
        *,
        run_id: str,
        side: str,
        skill: str,
        skill_round: int,
        prompt: str,
        fixture_path,
    ):
        return {
            "side": side,
            "skill_round": skill_round,
            "stop_reason": "end_turn",
            "iterations": 2,
            "duration_seconds": 1.2,
            "token_usage": {"prompt": 100, "completion": 20},
            "output_files": [f"/tmp/{side}/agent_final.md"],
            "log_records": [
                {
                    "event": "start",
                    "skill": skill,
                    "model": "google/gemma-4-26b-a4b-it",
                    "prompt": prompt,
                },
                {
                    "event": "end",
                    "stop_reason": "end_turn",
                    "tokens": {"prompt": 100, "completion": 20},
                },
            ],
        }

    def fake_judge(
        *, skill: str, prompt: str, original: dict, peak: dict, student_model: str
    ):
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
