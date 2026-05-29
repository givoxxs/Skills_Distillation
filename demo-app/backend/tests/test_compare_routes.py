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
