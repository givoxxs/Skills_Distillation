"""Read summary.json + SKILL_round_*.md from distillation_v2/results/stable/.

This module is **read-only** — never writes back into the upstream repo.
Per HANDOFF.md, the stable results directory is the source of truth.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from app.config import KNOWN_SKILLS, STABLE_DIR, TEST_CASES_DIR

_ROUND_RE = re.compile(r"^SKILL_round_(\d+)\.md$")

# tc_<letter><n> → workflow name. Matches distillation_v2/.claude/rules/
# skills-testcases-rules.md and the prototype's data model.
_TC_WORKFLOW_BY_LETTER = {
    "a": "create",
    "b": "read",
    "c": "edit",
    "d": "convert",
    "e": "edge",
}
_TC_ID_RE = re.compile(r"^tc_([a-z])(\d+)$", re.IGNORECASE)

# Hybrid score weight — matches distillation_v2/config.yaml (llm_judge_weight 0.20).
_LLM_JUDGE_WEIGHT = 0.20


def _skill_dir(skill: str) -> Path:
    if skill not in KNOWN_SKILLS:
        raise HTTPException(status_code=404, detail=f"unknown skill: {skill}")
    path = STABLE_DIR / skill
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=502, detail=f"stable dir missing for {skill}")
    return path


@lru_cache(maxsize=8)
def _read_summary(skill: str, mtime: float) -> dict:
    """Cache keyed by (skill, mtime). New mtime → fresh read."""
    del mtime  # mtime is just a cache key; the real read uses skill.
    summary_path = _skill_dir(skill) / "summary.json"
    if not summary_path.exists():
        raise HTTPException(status_code=502, detail=f"summary.json missing for {skill}")
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=502, detail=f"summary.json invalid for {skill}: {e}"
        ) from e


def get_summary(skill: str) -> dict:
    summary_path = _skill_dir(skill) / "summary.json"
    return _read_summary(skill, summary_path.stat().st_mtime)


def list_skills() -> list[dict]:
    """Return a slim card for each known skill — drives the Overview page."""
    out = []
    for skill in KNOWN_SKILLS:
        if not (STABLE_DIR / skill).exists():
            continue
        s = get_summary(skill)
        out.append(
            {
                "name": skill,
                "rounds_run": s.get("rounds_run", 0),
                "final_score": s.get("final_score", 0.0),
                "best_score": s.get("best_score", 0.0),
                "best_round": s.get("best_round", 0),
                "student_model": s.get("student_model", ""),
                "teacher_model": s.get("teacher_model", ""),
            }
        )
    return out


def available_rounds(skill: str) -> list[int]:
    """List round numbers that have a SKILL_round_<N>.md file on disk."""
    rounds: list[int] = []
    for entry in _skill_dir(skill).iterdir():
        m = _ROUND_RE.match(entry.name)
        if m:
            rounds.append(int(m.group(1)))
    rounds.sort()
    return rounds


@lru_cache(maxsize=128)
def _read_skill_md(skill: str, round_n: int, mtime: float) -> str:
    del mtime
    path = _skill_dir(skill) / f"SKILL_round_{round_n}.md"
    return path.read_text(encoding="utf-8")


def _workflow_from_id(test_case_id: str, fallback: str = "create") -> str:
    m = _TC_ID_RE.match(test_case_id)
    if not m:
        return fallback
    return _TC_WORKFLOW_BY_LETTER.get(m.group(1).lower(), fallback)


def _rule_score_from_checks(checks: list[dict]) -> float:
    if not checks:
        return 0.0
    total = 0.0
    n = 0
    for c in checks:
        score = c.get("score")
        if score is None:
            # Fallback to passed boolean.
            score = 1.0 if c.get("passed") else 0.0
        total += float(score)
        n += 1
    return total / n if n else 0.0


def _hybrid(rule_score: float, judge_score: float | None) -> float:
    if judge_score is None:
        return rule_score
    return (1.0 - _LLM_JUDGE_WEIGHT) * rule_score + _LLM_JUDGE_WEIGHT * float(
        judge_score
    )


@lru_cache(maxsize=8)
def _read_test_cases(skill: str, mtime: float) -> dict[str, dict]:
    """Return test cases keyed by id (tc_a01 → entry)."""
    del mtime
    path = TEST_CASES_DIR / f"{skill}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    entries = data.get("test_cases", []) if isinstance(data, dict) else data
    out: dict[str, dict] = {}
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        key = e.get("id") or e.get("test_case_id")
        if not key:
            continue
        out[str(key)] = e
    return out


def _get_test_cases(skill: str) -> dict[str, dict]:
    path = TEST_CASES_DIR / f"{skill}.json"
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return _read_test_cases(skill, mtime)


@lru_cache(maxsize=8)
def _read_eval_detail_raw(skill: str, mtime: float) -> list[dict]:
    """Cache the raw JSONL records keyed by (skill, mtime)."""
    del mtime
    path = _skill_dir(skill) / "eval_detail.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # Skip malformed lines rather than failing the whole endpoint.
            continue
    return out


@lru_cache(maxsize=8)
def _read_api_calls_raw(skill: str, mtime: float) -> list[dict]:
    del mtime
    path = _skill_dir(skill) / "api_calls.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def get_api_calls(skill: str, round_n: int | None = None) -> list[dict]:
    """Raw api_calls.jsonl records (judge + teacher; student is not logged
    by the upstream pipeline because it goes through Claude Code CLI).
    Filter by round when provided — only teacher records carry a `round`
    field, so judge records pass through unfiltered."""
    path = _skill_dir(skill) / "api_calls.jsonl"
    mtime = path.stat().st_mtime if path.exists() else 0.0
    rows = _read_api_calls_raw(skill, mtime)
    if round_n is None:
        return rows
    out = []
    for r in rows:
        if r.get("type") == "teacher":
            if r.get("round") == round_n:
                out.append(r)
        else:
            # judge records lack a round field — include them all and let
            # the consumer correlate by test_case.
            out.append(r)
    return out


def get_eval_detail(skill: str, round_n: int | None = None) -> list[dict]:
    """Return frontend-shaped EvalEntry records.

    Real fields from ``eval_detail.jsonl``:
      round, batch, test_case_id, skill, model, round_n, output_dir,
      checks (name/passed/score/reason), llm_judge_score, llm_judge_reasoning.

    Synthesised for the UI:
      workflow            ← derived from test_case_id prefix
      rule_score          ← mean of check.score
      hybrid_score        ← 0.8 * rule + 0.2 * judge (matches config.yaml)
      judge_rationale     ← llm_judge_reasoning
      rule_checks         ← checks
      prompt              ← test_cases/<skill>.json lookup
      output              ← output_dir (relative path on disk; UI shows it
                            as "stored at <path>" instead of inlining)
    """
    path = _skill_dir(skill) / "eval_detail.jsonl"
    mtime = path.stat().st_mtime if path.exists() else 0.0
    raw = _read_eval_detail_raw(skill, mtime)
    tcs = _get_test_cases(skill)
    workflows_known = {_workflow_from_id(k) for k in tcs.keys() if k} | set(
        _TC_WORKFLOW_BY_LETTER.values()
    )

    out: list[dict] = []
    for r in raw:
        rd = r.get("round", r.get("round_n"))
        if rd is None:
            continue
        if round_n is not None and rd != round_n:
            continue
        tc_id = r.get("test_case_id", "")
        tc_meta = tcs.get(tc_id, {})
        workflow = tc_meta.get("workflow") or _workflow_from_id(tc_id)
        if workflow not in workflows_known:
            workflow = workflow or "create"
        checks = r.get("checks") or []
        rule_score = _rule_score_from_checks(checks)
        judge_score = r.get("llm_judge_score")
        # Real pipeline skips judge when rule too low — surface that as None.
        if judge_score is None or (
            isinstance(judge_score, float) and judge_score < 0.0
        ):
            judge_score = None
        hybrid = _hybrid(rule_score, judge_score)

        out.append(
            {
                "round": int(rd),
                "test_case_id": tc_id,
                "workflow": workflow,
                "rule_score": round(float(rule_score), 4),
                "llm_judge_score": (
                    None if judge_score is None else round(float(judge_score), 4)
                ),
                "hybrid_score": round(float(hybrid), 4),
                "judge_rationale": r.get("llm_judge_reasoning", ""),
                "rule_checks": [
                    {
                        "name": c.get("name", ""),
                        "passed": bool(c.get("passed")),
                        "score": (
                            None
                            if c.get("score") is None
                            else round(float(c["score"]), 3)
                        ),
                        "reason": c.get("reason", ""),
                    }
                    for c in checks
                ],
                "prompt": tc_meta.get("prompt", ""),
                "output": r.get("output_dir", ""),
            }
        )
    return out


def get_skill_md(skill: str, round_n: int) -> tuple[int, str]:
    """Return (effective_round, content). Falls back to the closest *lower*
    round if the exact one is missing — matches the prototype's fill rule."""
    rounds = available_rounds(skill)
    if not rounds:
        raise HTTPException(status_code=502, detail=f"no SKILL_round_*.md for {skill}")

    if round_n in rounds:
        chosen = round_n
    else:
        prior = [r for r in rounds if r <= round_n]
        if not prior:
            chosen = rounds[0]
        else:
            chosen = max(prior)

    path = _skill_dir(skill) / f"SKILL_round_{chosen}.md"
    return chosen, _read_skill_md(skill, chosen, path.stat().st_mtime)


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
