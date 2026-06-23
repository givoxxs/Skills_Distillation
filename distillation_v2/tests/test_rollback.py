"""Tests for utils/rollback.py — keep/rollback decision logic."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.rollback import choose_validation_tcs, decide


def _emit(msg: str) -> None:
    pass  # silent in tests


ALL_TCS = [{"id": f"tc_{i:02d}"} for i in range(20)]


def test_choose_validation_tcs_count():
    selected, _ = choose_validation_tcs(ALL_TCS, n=3)
    assert len(selected) == 3


def test_choose_validation_tcs_does_not_exceed_total():
    selected, _ = choose_validation_tcs(ALL_TCS, n=100)
    assert len(selected) == len(ALL_TCS)


def test_choose_validation_tcs_is_reproducible_with_seed():
    a, _ = choose_validation_tcs(ALL_TCS, n=5, seed=42)
    b, _ = choose_validation_tcs(ALL_TCS, n=5, seed=42)
    assert [t["id"] for t in a] == [t["id"] for t in b]


def test_choose_validation_tcs_different_seeds_differ():
    a, _ = choose_validation_tcs(ALL_TCS, n=5, seed=1)
    b, _ = choose_validation_tcs(ALL_TCS, n=5, seed=2)
    # Very unlikely to be identical with 20 TCs
    assert [t["id"] for t in a] != [t["id"] for t in b]


def test_choose_validation_tcs_top_n_by_score():
    from evaluator.base import EvalResult

    # Create 20 test results. We want to test rank selection (indices start=min(5, max(0, 20-n)))
    # For n=2 and total=20, start = min(5, 18) = 5.
    # So it takes 0-indexed indices 5 and 6 of the sorted list (reverse=True).
    # Let's assign scores such that we know exactly who is at indices 5 and 6.
    # Sorted order (highest score first):
    # index 0..4: score 1.0 (5 TCs) -> tc_00, tc_01, tc_02, tc_03, tc_04
    # index 5: score 0.8 (1 TC) -> tc_05
    # index 6: score 0.7 (1 TC) -> tc_06
    # index 7..19: score 0.1 (13 TCs) -> others
    results = []
    for tc in ALL_TCS:
        tid = tc["id"]
        if tid in ["tc_00", "tc_01", "tc_02", "tc_03", "tc_04"]:
            score = 1.0
        elif tid == "tc_05":
            score = 0.8
        elif tid == "tc_06":
            score = 0.7
        else:
            score = 0.1
        er = EvalResult(
            test_case_id=tid, skill="s", model="m", round_n=1, output_dir="/tmp"
        )
        er.llm_judge_score = score
        results.append(er)

    selected, baseline = choose_validation_tcs(ALL_TCS, n=2, round_results=results)
    ids = [t["id"] for t in selected]
    assert ids == ["tc_05", "tc_06"]
    assert abs(baseline - 0.75) < 1e-9


# ── decide() ──────────────────────────────────────────────────────────────────


def test_decide_keeps_when_new_is_better():
    assert (
        decide(val_score=0.80, baseline_score=0.70, threshold=0.05, emit=_emit) is True
    )


def test_decide_keeps_on_tie():
    assert (
        decide(val_score=0.70, baseline_score=0.70, threshold=0.05, emit=_emit) is True
    )


def test_decide_keeps_when_drop_is_within_threshold():
    # 0.66 >= 0.70 - 0.05 = 0.65 → keep
    assert (
        decide(val_score=0.66, baseline_score=0.70, threshold=0.05, emit=_emit) is True
    )


def test_decide_rollbacks_when_drop_exceeds_threshold():
    # 0.60 < 0.70 - 0.05 = 0.65 → rollback
    assert (
        decide(val_score=0.60, baseline_score=0.70, threshold=0.05, emit=_emit) is False
    )


def test_decide_rollbacks_on_large_drop():
    assert (
        decide(val_score=0.30, baseline_score=0.80, threshold=0.05, emit=_emit) is False
    )


def test_decide_keeps_when_new_equals_baseline_minus_threshold():
    # Exactly at boundary: 0.65 >= 0.70 - 0.05 = 0.65 → keep
    assert (
        decide(val_score=0.65, baseline_score=0.70, threshold=0.05, emit=_emit) is True
    )
