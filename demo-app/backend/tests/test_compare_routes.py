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
