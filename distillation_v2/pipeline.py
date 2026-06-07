"""Distillation v2 pipeline — main orchestration loop.

Flow per round:
  1. Run all batches (student → judge → run_log.md).
  2. Gate 2: if round_avg dropped > gate2_threshold vs prev round → hard rollback
     to best-ever SKILL.md, skip Teacher.
  3. Teacher reads ALL run_logs → generates SKILL_candidate.md.
  4. Gate 1: run rank-6/7/8 TCs with SKILL_candidate. Keep if val_score >=
     baseline (those TCs' score in current round) - gate1_threshold.
  5. Check stopping criteria.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluator.base import EvalResult
from runner.config import RunConfigV2
from stages.judge import Judge
from stages.rubric_gen import generate_rubric
from stages.student import make_skip_result, run_student
from stages.summarizer import make_run_log
from stages.teacher import rewrite as teacher_rewrite
from utils import get_logger, write_api_call, write_eval_detail
from utils.rollback import choose_validation_tcs, decide, run_validation

_log = get_logger("v2.pipeline")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _or_model(model: str) -> str:
    """Prefix model with 'anthropic/' for OpenRouter if not already namespaced."""
    return model if "/" in model else f"anthropic/{model}"


def _avg_judge_score(results: list[EvalResult]) -> float:
    """Average llm_judge_score over a list, treating negatives as 0 in the sum
    while dividing by the full count (preserves original inline semantics)."""
    if not results:
        return 0.0
    return sum(r.llm_judge_score for r in results if r.llm_judge_score >= 0) / len(
        results
    )


def _resolve_llm_setup(
    llm_api_key: str | None,
    llm_base_url: str | None,
    teacher_model: str,
    judge_model: str,
) -> tuple[str, str | None, str, str]:
    """Resolve LLM API key + auto-prefix teacher/judge models for OpenRouter."""
    resolved_llm_key = llm_api_key or os.getenv("OPENROUTER_API_KEY")
    if not resolved_llm_key:
        raise RuntimeError("No LLM API key found. Set OPENROUTER_API_KEY.")
    if llm_base_url and "openrouter" in llm_base_url:
        teacher_model = _or_model(teacher_model)
        judge_model = _or_model(judge_model)
    return resolved_llm_key, llm_base_url, teacher_model, judge_model


def _init_judges(
    *,
    skill: str,
    skill_dir: Path,
    rubric_pool: list[dict[str, Any]],
    rubric_cache_dir: str,
    judge_model: str,
    regenerate_rubric: bool,
    watch_skill_hash: bool,
    keep_recent_rubrics: int,
    ensemble_n: int,
    max_image_pages: int,
    max_gif_frames: int,
    judge_temperature: float,
    anthropic_api_key: str,
    base_url: str | None,
) -> tuple[dict[str, Judge], dict[str, str]]:
    """Generate one rubric + Judge per workflow present in `rubric_pool`."""
    workflows = sorted(set(tc.get("workflow", "create") for tc in rubric_pool))
    judges: dict[str, Judge] = {}
    rubric_keys: dict[str, str] = {}
    for wf in workflows:
        wf_tcs = [tc for tc in rubric_pool if tc.get("workflow", "create") == wf]
        wf_rubric = generate_rubric(
            skill_name=skill,
            skill_dir=skill_dir,
            test_cases=wf_tcs,
            workflow=wf,
            cache_dir=rubric_cache_dir,
            model=judge_model,
            regenerate=regenerate_rubric,
            watch_skill_hash=watch_skill_hash,
            keep_recent=keep_recent_rubrics,
            anthropic_api_key=anthropic_api_key,
            base_url=base_url,
        )
        judges[wf] = Judge(
            rubric=wf_rubric,
            model=judge_model,
            ensemble_n=ensemble_n,
            max_image_pages=max_image_pages,
            max_gif_frames=max_gif_frames,
            anthropic_api_key=anthropic_api_key,
            base_url=base_url,
            temperature=judge_temperature,
        )
        rubric_keys[wf] = wf_rubric.get("cache_key", "")
    return judges, rubric_keys


def _run_one_batch_persisted(
    *,
    batch: list[dict],
    batch_idx: int,
    n_batches: int,
    round_n: int,
    skill: str,
    student_model: str,
    judges: dict[str, Judge],
    results_path: Path,
    test_cases_dir: str,
    base_config: RunConfigV2,
    max_retry_per_tc: int,
    working_md: Path,
    concurrent_tcs: int,
    no_llm_judge: bool,
    emit: Callable[[str], None],
    no_skill: bool = False,
) -> tuple[list[EvalResult], list[str], str]:
    """Run one batch + persist run_log.md + scores.json + eval_detail.jsonl.

    Returns (eval_results, log_paths, run_log_md_content).
    """
    emit(f"  [R{round_n}.B{batch_idx}/{n_batches}] running {len(batch)} TC(s)...")
    batch_start = time.time()
    batch_results, batch_logs = _run_batch(
        batch=batch,
        skill=skill,
        student_model=student_model,
        judges=judges,
        results_path=results_path,
        test_cases_dir=test_cases_dir,
        base_config=base_config,
        round_n=round_n,
        batch_idx=batch_idx,
        max_retry_per_tc=max_retry_per_tc,
        current_skill_md=working_md,
        emit=emit,
        concurrent_tcs=concurrent_tcs,
        no_llm_judge=no_llm_judge,
        no_skill=no_skill,
    )

    run_log_content = make_run_log(batch_results, round_n, batch_idx, batch_logs)
    run_log_path = (
        results_path / f"round_{round_n}" / f"batch_{batch_idx}" / "run_log.md"
    )
    run_log_path.parent.mkdir(parents=True, exist_ok=True)
    run_log_path.write_text(run_log_content, encoding="utf-8")

    elapsed = time.time() - batch_start
    avg = _avg_judge_score(batch_results)
    passed = sum(1 for r in batch_results if r.llm_judge_score >= 0.8)
    emit(
        f"  [R{round_n}.B{batch_idx}] {passed}/{len(batch_results)} passed"
        f"  avg={avg:.3f}  ({elapsed:.1f}s)"
    )
    _save_batch_scores(results_path, round_n, batch_idx, batch_results)
    for r in batch_results:
        write_eval_detail({"round": round_n, "batch": batch_idx, **asdict(r)})
    return batch_results, batch_logs, run_log_content


def _apply_gate2(
    *,
    round_avg: float,
    prev_avg: float,
    gate2_threshold: float,
    best_round_n: int,
    best_score: float,
    best_skill_snapshot: Path | None,
    working_md: Path,
    emit: Callable[[str], None],
) -> bool:
    """Hard-rollback to best snapshot if round dropped more than threshold.

    Returns True if gate2 fired (caller should skip Teacher this round).
    """
    delta = round_avg - prev_avg
    if delta >= -gate2_threshold:
        return False
    emit(
        f"  [gate2] FAIL (Δ={delta:+.3f} < -{gate2_threshold})"
        f" → hard rollback to best R{best_round_n} ({best_score:.3f})"
    )
    if best_skill_snapshot and best_skill_snapshot.exists():
        shutil.copy2(best_skill_snapshot, working_md)
        emit(f"  [gate2] restored {best_skill_snapshot.name}")
    else:
        emit("  [gate2] WARNING: no valid snapshot to restore — skipping Teacher only")
    return True


def _apply_teacher_step(
    *,
    working_md: Path,
    run_logs: list[str],
    teacher_model: str,
    teacher_temperature: float,
    anthropic_api_key: str,
    base_url: str | None,
    round_n: int,
    test_cases: list[dict[str, Any]],
    all_results: list[EvalResult],
    validation_tc_count: int,
    gate1_threshold: float,
    val_batch_fn: Callable[[list[dict]], list[EvalResult]],
    emit: Callable[[str], None],
) -> None:
    """Run Teacher rewrite + Gate 1 validation. Mutates working_md only on accept."""
    emit(f"  Teacher rewriting SKILL.md from {len(run_logs)} run_log(s)...")
    teacher_start = time.time()
    try:
        new_skill = teacher_rewrite(
            skill_md_path=working_md,
            run_logs=run_logs,
            model=teacher_model,
            round_n=round_n,
            anthropic_api_key=anthropic_api_key,
            base_url=base_url,
            temperature=teacher_temperature,
        )
        emit(
            f"  Teacher done ({len(new_skill)} chars,"
            f" {time.time() - teacher_start:.1f}s)"
        )

        if validation_tc_count == 0:
            emit("  [gate1] DISABLED — keeping new SKILL.md unconditionally")
            working_md.write_text(new_skill, encoding="utf-8")
            return

        val_tcs, val_baseline = choose_validation_tcs(
            test_cases, validation_tc_count, round_results=all_results
        )
        emit(
            "  [gate1] val TCs (rank 6-8): "
            + ", ".join(tc["id"] for tc in val_tcs)
            + f"  baseline={val_baseline:.3f}"
        )

        val_score = run_validation(
            skill_md_path=working_md,
            new_skill_content=new_skill,
            validation_tcs=val_tcs,
            run_batch_fn=val_batch_fn,
            emit=emit,
        )
        if decide(val_score, val_baseline, gate1_threshold, emit):
            working_md.write_text(new_skill, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        emit(f"  Teacher FAILED: {e}. Skipping rewrite.")
        write_api_call({"type": "teacher", "error": str(e), "round": round_n})


# ── Public entry point ────────────────────────────────────────────────────────


def run_distillation(
    skill: str,
    test_cases: list[dict[str, Any]],
    rubric_test_cases: list[dict[str, Any]] | None = None,
    student_model: str = "google/gemma-4-26b-a4b-it",
    teacher_model: str = "claude-haiku-4-5",
    judge_model: str = "claude-haiku-4-5",
    llm_api_key: str | None = None,
    llm_base_url: str | None = OPENROUTER_BASE_URL,
    max_rounds: int = 3,
    batch_size: int = 5,
    stop_threshold: float = 0.7,
    converge_delta: float = 0.02,
    converge_k: int = 3,
    gate1_threshold: float = 0.10,
    gate2_threshold: float = 0.10,
    validation_tc_count: int = 3,
    teacher_temperature: float = 0.3,
    judge_temperature: float = 0.2,
    max_retry_per_tc: int = 3,
    max_image_pages: int = 10,
    max_gif_frames: int = 5,
    results_dir: str = "./results",
    rubric_cache_dir: str = "./rubrics",
    skills_dir: str | None = None,
    test_cases_dir: str | None = None,
    regenerate_rubric: bool = True,
    watch_skill_hash: bool = False,
    keep_recent_rubrics: int = 5,
    ensemble_n: int = 1,
    sandbox_tmp_root: str = "~/.cache/distill_v2",
    sandbox_keep_on_fail: bool = True,
    claude_binary: str = "claude",
    verbose: bool = False,
    dry_run: bool = False,
    resume: bool = False,
    no_llm_judge: bool = False,
    concurrent_tcs: int = 1,
    no_skill: bool = False,
) -> dict[str, Any]:
    # Resolve LLM credentials + auto-prefix models for OpenRouter
    resolved_llm_key, resolved_base_url, teacher_model, judge_model = (
        _resolve_llm_setup(llm_api_key, llm_base_url, teacher_model, judge_model)
    )

    v2_root = Path(__file__).resolve().parent
    results_path = Path(results_dir) / skill
    results_path.mkdir(parents=True, exist_ok=True)

    skills_dir = skills_dir or str(v2_root / "skills")
    test_cases_dir = test_cases_dir or str(v2_root / "test_cases")
    skill_dir = Path(skills_dir) / skill
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.is_file():
        raise FileNotFoundError(f"SKILL.md not found: {skill_md_path}")

    # Fresh-run cleanup: without --resume, wipe the skill results dir so each
    # run starts clean (no stale round dirs, logs, JSONL files, snapshots).
    if not resume and results_path.exists():
        shutil.rmtree(results_path)
    results_path.mkdir(parents=True, exist_ok=True)

    # working_md is the mutable copy; original skill_md_path is never modified.
    working_md = results_path / "SKILL_current.md"
    if not working_md.exists():
        shutil.copy2(skill_md_path, working_md)

    # Per-workflow rubrics + judges. Use rubric_test_cases (full set) when
    # provided so rubric covers every workflow even if subset is being run.
    rubric_pool = rubric_test_cases if rubric_test_cases is not None else test_cases
    judges, rubric_keys = _init_judges(
        skill=skill,
        skill_dir=skill_dir,
        rubric_pool=rubric_pool,
        rubric_cache_dir=rubric_cache_dir,
        judge_model=judge_model,
        regenerate_rubric=regenerate_rubric,
        watch_skill_hash=watch_skill_hash,
        keep_recent_rubrics=keep_recent_rubrics,
        ensemble_n=ensemble_n,
        max_image_pages=max_image_pages,
        max_gif_frames=max_gif_frames,
        judge_temperature=judge_temperature,
        anthropic_api_key=resolved_llm_key,
        base_url=resolved_base_url,
    )

    # ── Run config for student ────────────────────────────────────────────────
    base_config = RunConfigV2(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        claude_binary=claude_binary,
        skills_dir=skills_dir,
        log_dir=str(v2_root / "logs"),
        sandbox_tmp_root=sandbox_tmp_root,
        sandbox_keep_on_fail=sandbox_keep_on_fail,
        verbose=verbose,
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    run_log_file = open(
        results_path / "run.log", "w" if not resume else "a", buffering=1
    )

    def emit(msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        run_log_file.write(line + "\n")
        if verbose:
            print(line, flush=True)

    eff_batch = (
        batch_size if (batch_size and batch_size < len(test_cases)) else len(test_cases)
    )
    n_batches = math.ceil(len(test_cases) / eff_batch)

    emit("=" * 60)
    emit(f"V2 START  skill={skill}  student={student_model}  teacher={teacher_model}")
    for wf, j in judges.items():
        emit(f"Rubric [{wf}]: {len(j.rubric['criteria'])} criteria")
    emit(f"TCs: {len(test_cases)}  batches/round={n_batches}  batch_size={eff_batch}")
    if validation_tc_count == 0:
        emit("Rollback: DISABLED (--no-rollback)")
    else:
        emit(
            f"Gate1 threshold: {gate1_threshold}  Gate2 threshold: {gate2_threshold}"
            f"  validation_tcs: {validation_tc_count} (rank 6-8)"
        )
    emit("=" * 60)

    _save_skill_version(working_md, results_path, round_n=0, skip_if_exists=resume)

    history: list[dict] = []
    prev_avg: float | None = None
    recent_deltas: list[float] = []
    best_score: float = 0.0
    best_round_n: int = 0
    best_skill_snapshot: Path | None = None

    for round_n in range(1, max_rounds + 1):
        emit(f"\n--- Round {round_n}/{max_rounds} ---")
        round_start = time.time()
        all_results: list[EvalResult] = []
        run_logs: list[str] = []
        batch_log_paths: list[list[str]] = []

        batches = [
            test_cases[i : i + eff_batch] for i in range(0, len(test_cases), eff_batch)
        ]

        # ── Run all batches ───────────────────────────────────────────────────
        for batch_idx, batch in enumerate(batches, 1):
            if resume and _is_batch_complete(results_path, round_n, batch_idx):
                cached = _load_cached_batch(
                    results_path, round_n, batch_idx, batch, skill, student_model
                )
                all_results.extend(cached)
                emit(f"  [R{round_n}.B{batch_idx}] resumed ({len(cached)} tc)")
                continue

            batch_results, batch_logs, run_log_content = _run_one_batch_persisted(
                batch=batch,
                batch_idx=batch_idx,
                n_batches=n_batches,
                round_n=round_n,
                skill=skill,
                student_model=student_model,
                judges=judges,
                results_path=results_path,
                test_cases_dir=test_cases_dir,
                base_config=base_config,
                max_retry_per_tc=max_retry_per_tc,
                working_md=working_md,
                concurrent_tcs=concurrent_tcs,
                no_llm_judge=no_llm_judge,
                emit=emit,
                no_skill=no_skill,
            )
            all_results.extend(batch_results)
            batch_log_paths.append(batch_logs)
            run_logs.append(run_log_content)

        round_avg = _avg_judge_score(all_results)

        # ── Gate 2: hard rollback if round dropped too much vs prev ──────────
        gate2_triggered = False
        if not dry_run and validation_tc_count > 0 and prev_avg is not None:
            gate2_triggered = _apply_gate2(
                round_avg=round_avg,
                prev_avg=prev_avg,
                gate2_threshold=gate2_threshold,
                best_round_n=best_round_n,
                best_score=best_score,
                best_skill_snapshot=best_skill_snapshot,
                working_md=working_md,
                emit=emit,
            )

        # ── Teacher rewrite + Gate 1 validation ──────────────────────────────
        if not dry_run and run_logs and not gate2_triggered:

            def _val_batch(tcs: list[dict]) -> list[EvalResult]:
                results, _ = _run_batch(
                    batch=tcs,
                    skill=skill,
                    student_model=student_model,
                    judges=judges,
                    results_path=results_path / "validation" / f"round_{round_n}",
                    test_cases_dir=test_cases_dir,
                    base_config=base_config,
                    round_n=round_n,
                    batch_idx=0,
                    max_retry_per_tc=max_retry_per_tc,
                    current_skill_md=working_md,
                    emit=emit,
                    no_llm_judge=no_llm_judge,
                )
                return results

            _apply_teacher_step(
                working_md=working_md,
                run_logs=run_logs,
                teacher_model=teacher_model,
                teacher_temperature=teacher_temperature,
                anthropic_api_key=resolved_llm_key,
                base_url=resolved_base_url,
                round_n=round_n,
                test_cases=test_cases,
                all_results=all_results,
                validation_tc_count=validation_tc_count,
                gate1_threshold=gate1_threshold,
                val_batch_fn=_val_batch,
                emit=emit,
            )
        elif dry_run:
            emit("  DRY RUN — skipping Teacher + rollback.")

        # ── Round summary ─────────────────────────────────────────────────────
        _save_skill_version(working_md, results_path, round_n, skip_if_exists=resume)

        # Track best round for Gate 2 hard rollback.
        # SKILL_round_{N-1}.md is the version the current round's batches ran with —
        # that is the proven-good snapshot to restore if future rounds regress.
        if round_avg > best_score:
            best_score = round_avg
            best_round_n = round_n
            best_skill_snapshot = results_path / f"SKILL_round_{round_n - 1}.md"

        duration = time.time() - round_start
        bar = "█" * int(round_avg * 20)
        emit(f"  Round {round_n} avg={round_avg:.3f} {bar}  ({duration:.1f}s)")

        history.append(
            {
                "round": round_n,
                "avg_score": round_avg,
                "n_batches": len(batches),
                "eval_results": [_serialize_result(r) for r in all_results],
            }
        )
        _save_round_scores(results_path, round_n, history[-1])

        # ── Stopping criteria ─────────────────────────────────────────────────
        if round_avg >= stop_threshold:
            emit(f"  STOP: score {round_avg:.3f} >= threshold {stop_threshold}")
            break
        if prev_avg is not None:
            recent_deltas.append(abs(round_avg - prev_avg))
            if len(recent_deltas) >= converge_k and all(
                d < converge_delta for d in recent_deltas[-converge_k:]
            ):
                emit(f"  STOP: converged (Δ<{converge_delta} for {converge_k} rounds)")
                break
        if round_n == max_rounds:
            emit(f"  STOP: reached max_rounds={max_rounds}")
        prev_avg = round_avg

    best = (
        max(history, key=lambda h: h["avg_score"])
        if history
        else {"round": 0, "avg_score": 0.0}
    )
    summary = {
        "skill": skill,
        "student_model": student_model,
        "teacher_model": teacher_model,
        "judge_model": judge_model,
        "batch_size": eff_batch,
        "rounds_run": len(history),
        "final_score": history[-1]["avg_score"] if history else 0.0,
        "best_round": best["round"],
        "best_score": best["avg_score"],
        "score_history": [
            {"round": h["round"], "avg_score": h["avg_score"]} for h in history
        ],
        "rubric_cache_keys": rubric_keys,
    }
    (results_path / "summary.json").write_text(json.dumps(summary, indent=2))
    try:
        emit("")
        emit("=" * 60)
        emit(
            f"DONE. Best round: {summary['best_round']}  score={summary['best_score']:.3f}"
        )
    finally:
        run_log_file.close()
    return summary


# ── Batch runner ──────────────────────────────────────────────────────────────


def _run_batch(
    batch: list[dict],
    skill: str,
    student_model: str,
    judges: dict[str, Judge],
    results_path: Path,
    test_cases_dir: str,
    base_config: RunConfigV2,
    round_n: int,
    batch_idx: int,
    max_retry_per_tc: int,
    current_skill_md: Path,
    emit: Callable[[str], None],
    concurrent_tcs: int = 1,
    no_llm_judge: bool = False,
    no_skill: bool = False,
) -> tuple[list[EvalResult], list[str]]:
    skill_dir = Path(base_config.skills_dir) / skill
    n = len(batch)

    # Thread-safe emit wrapper (no-op lock when sequential)
    _lock = threading.Lock()

    def _emit(msg: str) -> None:
        with _lock:
            emit(msg)

    def _run_one(tc_idx: int, tc: dict) -> tuple[EvalResult, list[str]]:
        tc_log_paths: list[str] = []
        output_dir = results_path / f"round_{round_n}" / f"batch_{batch_idx}" / tc["id"]
        output_dir.mkdir(parents=True, exist_ok=True)
        _emit(f"    [{tc_idx}/{n}] {tc['id']}  '{tc.get('name', '')}'")
        tc_start = time.time()

        # Fixture handling — supports both fixture_file (str) and fixture_files (list)
        input_files: list[Path] = []
        raw = tc.get("fixture_files") or (
            [tc["fixture_file"]] if tc.get("fixture_file") else []
        )
        for rel in raw:
            src = Path(test_cases_dir) / rel
            if src.is_file():
                input_files.append(src)
            else:
                _emit(f"      WARNING: fixture missing: {src}")

        user_prompt = tc.get("prompt", "")
        workflow = tc.get("workflow", "create")
        if workflow == "read":
            user_prompt = (
                "[CRITICAL: You MUST save your output to a file on disk (e.g. output.txt, output.json). Do NOT just print to the terminal — the evaluator reads files only.]\n\n"
                + user_prompt
            )
        if input_files:
            names = ", ".join(f.name for f in input_files)
            user_prompt = f"[Files in your working dir: {names}]\n\n{user_prompt}"

        config = RunConfigV2(
            openrouter_api_key=base_config.openrouter_api_key,
            claude_binary=base_config.claude_binary,
            skills_dir=base_config.skills_dir,
            log_dir=base_config.log_dir,
            output_dir=str(output_dir),
            input_files=input_files,
            sandbox_tmp_root=base_config.sandbox_tmp_root,
            sandbox_keep_on_fail=base_config.sandbox_keep_on_fail,
            verbose=base_config.verbose,
        )

        run = run_student(
            user_prompt=user_prompt,
            skill_name=skill,
            skill_dir=skill_dir,
            model=student_model,
            config=config,
            max_retries=max_retry_per_tc,
            current_skill_md=current_skill_md,
            no_skill=no_skill,
        )

        if run.get("skipped"):
            _emit(f"      SKIPPED (all {max_retry_per_tc} retries failed)")
            er = make_skip_result(tc, skill, student_model, round_n, str(output_dir))
            if run.get("log_file"):
                tc_log_paths.append(run["log_file"])
            return er, tc_log_paths

        _emit(
            f"      stop={run.get('stop_reason')}  iters={run.get('iterations')}  ({time.time()-tc_start:.1f}s)"
        )
        if run.get("log_file"):
            tc_log_paths.append(run["log_file"])

        if no_llm_judge:
            er = EvalResult(
                test_case_id=tc["id"],
                skill=skill,
                model=student_model,
                round_n=round_n,
                output_dir=str(output_dir),
            )
            er.llm_judge_score = 0.0
            er.llm_judge_reasoning = "skipped (--no-llm-judge)"
        else:
            try:
                wf = tc.get("workflow", "create")
                tc_judge = judges.get(wf) or next(iter(judges.values()))
                tc_with_skill = {**tc, "skill": skill}
                er = tc_judge.score(
                    output_dir=str(output_dir),
                    test_case=tc_with_skill,
                    model=student_model,
                    round_n=round_n,
                    input_files=input_files if wf == "read" else None,
                )
            except Exception as e:  # noqa: BLE001
                _log.exception("judge.score() crashed for %s", tc["id"])
                _emit(f"      JUDGE ERROR: {e}")
                er = make_skip_result(
                    tc, skill, student_model, round_n, str(output_dir)
                )

        score = er.llm_judge_score if er.llm_judge_score >= 0 else 0.0
        status = "PASS" if score >= 0.8 else "FAIL"
        _emit(f"      [{status}] score={score:.2f}")
        return er, tc_log_paths

    # ── Execute: sequential or parallel ──────────────────────────────────────
    if concurrent_tcs <= 1:
        pairs = [_run_one(i, tc) for i, tc in enumerate(batch, 1)]
    else:
        pairs: list[tuple[EvalResult, list[str]]] = [None] * n  # type: ignore[list-item]
        with ThreadPoolExecutor(max_workers=concurrent_tcs) as pool:
            future_to_pos = {
                pool.submit(_run_one, i, tc): pos
                for pos, (i, tc) in enumerate(enumerate(batch, 1))
            }
            for future in as_completed(future_to_pos):
                pairs[future_to_pos[future]] = future.result()

    results = [er for er, _ in pairs]
    log_paths = [lp for _, lps in pairs for lp in lps]
    return results, log_paths


# ── Persistence helpers ───────────────────────────────────────────────────────


def _serialize_result(r: EvalResult) -> dict[str, Any]:
    return {
        "test_case_id": r.test_case_id,
        "llm_score": r.llm_judge_score if r.llm_judge_score >= 0 else None,
        "checks": [
            {"name": c.name, "passed": c.passed, "score": c.score, "reason": c.reason}
            for c in r.checks
        ],
    }


def _save_batch_scores(
    results_path: Path, round_n: int, batch_idx: int, results: list[EvalResult]
) -> None:
    p = results_path / f"round_{round_n}" / f"batch_{batch_idx}" / "scores.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "round": round_n,
                "batch": batch_idx,
                "avg_score": _avg_judge_score(results),
                "eval_results": [_serialize_result(r) for r in results],
            },
            indent=2,
        )
    )


def _save_round_scores(results_path: Path, round_n: int, data: dict) -> None:
    p = results_path / f"round_{round_n}" / "scores.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def _save_skill_version(
    skill_md_path: Path,
    results_path: Path,
    round_n: int,
    skip_if_exists: bool = False,
) -> None:
    dest = results_path / f"SKILL_round_{round_n}.md"
    if skip_if_exists and dest.exists():
        return
    shutil.copy2(skill_md_path, dest)


def _is_batch_complete(results_path: Path, round_n: int, batch_idx: int) -> bool:
    return (
        results_path / f"round_{round_n}" / f"batch_{batch_idx}" / "scores.json"
    ).exists()


def _load_cached_batch(
    results_path: Path,
    round_n: int,
    batch_idx: int,
    batch: list[dict],
    skill: str,
    model: str,
) -> list[EvalResult]:
    scores_path = (
        results_path / f"round_{round_n}" / f"batch_{batch_idx}" / "scores.json"
    )
    data = json.loads(scores_path.read_text())
    by_id = {e["test_case_id"]: e for e in data.get("eval_results", [])}
    results: list[EvalResult] = []
    for tc in batch:
        entry = by_id.get(tc["id"])
        if entry is None:
            raise ValueError(
                f"Cache miss for TC '{tc['id']}' in round {round_n} batch {batch_idx}. "
                "Test cases may have changed since last run — delete cached results or "
                "remove --resume to re-run from scratch."
            )
        er = EvalResult(
            test_case_id=tc["id"],
            skill=skill,
            model=model,
            round_n=round_n,
            output_dir=str(
                results_path / f"round_{round_n}" / f"batch_{batch_idx}" / tc["id"]
            ),
        )
        er.llm_judge_score = entry.get("llm_score") or 0.0
        results.append(er)
    return results
