"""CLI entry point for Skill Distillation v2.

exports: main()  (click command — CLI entry point)
used_by: __main__ (python run.py ...)
rules:   --no-skill forces rounds=1 + dry_run + regenerate_rubric=False and
         redirects results to results/<date>/noskill/ so the real run is not
         wiped; it reuses the cached rubric for an apples-to-apples baseline.
         --regenerate-rubric (CLI) OR config wins; default reuses the cache.
agent:   claude-opus-4-8 | anthropic | 2026-06-07 | feat/arena-compare | add --no-skill baseline flag
         claude-sonnet-4-6 | anthropic | 2026-06-08 | feat/arena-compare | add --no-feedback blind-rewrite ablation

Usage:
    cd distillation_v2/
    python run.py --skill docx --rounds 3 --test-cases 5 --verbose
    python run.py --skill docx --dry-run                     # skip Teacher
    python run.py --skill docx --regenerate-rubric           # force new rubric
    python run.py --skill docx --resume                      # continue partial run
    python run.py --skill docx --no-skill                    # zero-shot baseline (no SKILL.md)
    python run.py --skill docx --no-feedback --rounds 3      # blind-rewrite ablation

Config defaults are loaded from config.yaml in this directory.
All CLI flags override the config file.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))

_CONFIG_FILE = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    if not _CONFIG_FILE.is_file():
        return {}
    with _CONFIG_FILE.open() as f:
        return yaml.safe_load(f) or {}


@click.command()
@click.option("--skill", "-s", required=True, help="Skill name (e.g. docx).")
@click.option("--rounds", "-r", type=int, default=None, help="Max distillation rounds.")
@click.option(
    "--batch-size", "-b", type=int, default=None, help="Test cases per batch."
)
@click.option(
    "--test-cases",
    "-n",
    type=int,
    default=None,
    help="Number of test cases to use (from top of file). Default: all.",
)
@click.option("--student", default=None, help="OpenRouter model ID for Student.")
@click.option("--teacher", default=None, help="Claude model for Teacher.")
@click.option(
    "--judge", default=None, help="Claude model for Judge + Rubric generator."
)
@click.option("--test-cases-file", default=None, help="Path to test cases JSON.")
@click.option("--results-dir", default=None, help="Root results dir.")
@click.option(
    "--skills-dir", default=None, help="Override path to skill_runner/skills/."
)
@click.option("--rubric-cache-dir", default=None, help="Rubric cache directory.")
@click.option(
    "--regenerate-rubric",
    is_flag=True,
    default=False,
    help="Bypass rubric cache and generate a fresh rubric.",
)
@click.option(
    "--ensemble-n", type=int, default=None, help="LLM Judge calls per test case."
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Verbose progress output."
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Run Student + Judge but skip Teacher (no SKILL.md rewrites).",
)
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Resume from last completed batch in the results dir.",
)
@click.option(
    "--no-rollback",
    is_flag=True,
    default=False,
    help="Always keep new SKILL.md after Teacher rewrite, skipping validation.",
)
@click.option(
    "--stop-threshold",
    type=float,
    default=None,
    help="Stop early when avg score >= this value (default from config).",
)
@click.option(
    "--no-llm-judge",
    is_flag=True,
    default=False,
    help="Skip LLM Judge; score using rule-based checks only (no Anthropic API for scoring).",
)
@click.option(
    "--workflow",
    default=None,
    help="Comma-separated workflow letters to RUN (e.g. 'b,c,d,e'). "
    "Rubric is still generated from all test cases. "
    "Letters: a=create, b=read, c=edit, d=convert, e=edge.",
)
@click.option(
    "--parallel",
    type=int,
    default=1,
    show_default=True,
    help="Number of test cases to run concurrently (default: 1 = sequential). "
    "Use 3-5 to speed up; higher values may hit API rate limits.",
)
@click.option(
    "--no-skill",
    is_flag=True,
    default=False,
    help="Baseline mode: run the Student with NO skill installed (no SKILL.md, "
    "scripts, or 'Use skill X' prefix) — zero-shot floor. Forces rounds=1 + no "
    "Teacher, reuses the cached rubric, and writes to results/<date>/noskill/.",
)
@click.option(
    "--no-feedback",
    is_flag=True,
    default=False,
    help="Blind-rewrite ablation: Teacher rewrites SKILL.md each round WITHOUT "
    "seeing any run_log failure summaries — only the current SKILL.md plus a "
    "generic 'improve for small models' instruction. Used to isolate whether the "
    "feedback loop (not just the teacher's rewriting ability) drives improvement.",
)
def main(
    skill,
    rounds,
    batch_size,
    test_cases,
    student,
    teacher,
    judge,
    test_cases_file,
    results_dir,
    skills_dir,
    rubric_cache_dir,
    regenerate_rubric,
    ensemble_n,
    verbose,
    dry_run,
    resume,
    no_rollback,
    stop_threshold,
    no_llm_judge,
    workflow,
    parallel,
    no_skill,
    no_feedback,
):
    """Run Skill Distillation v2 for one skill."""
    full_cfg = _load_config()
    cfg = full_cfg.get("distillation", {})
    sandbox_cfg = full_cfg.get("sandbox", {})

    rubric_cfg = full_cfg.get("rubric", {})
    student_cfg = full_cfg.get("student", {})
    logging_cfg = full_cfg.get("logging", {})

    # Results dir with date subfolder
    base_results = results_dir or cfg.get("results_dir", "./results")
    results_dir = str(Path(base_results) / datetime.now().strftime("%d_%m_%Y"))

    # Logging setup
    import pipeline
    from utils import setup_logging

    setup_logging(
        level=logging_cfg.get("level", "info"),
        eval_detail=logging_cfg.get("eval_detail", True),
        api_calls=logging_cfg.get("api_calls", True),
        results_dir=results_dir,
        skill=skill,
        stream=True,
    )
    _log = logging.getLogger("distillation")
    _log.info(
        "v2  OPENROUTER_API_KEY=%s",
        "SET" if os.environ.get("OPENROUTER_API_KEY") else "MISSING",
    )

    # Resolve CLI > config > default
    rounds = rounds if rounds is not None else cfg.get("max_rounds", 3)
    batch_size = batch_size if batch_size is not None else cfg.get("batch_size", 5)
    student = student or cfg.get("student_model", "google/gemma-4-26b-a4b-it")
    teacher = teacher or cfg.get("teacher_model", "claude-haiku-4-5")
    judge = judge or cfg.get("judge_model", "claude-haiku-4-5")
    ensemble_n = ensemble_n if ensemble_n is not None else cfg.get("ensemble_n", 1)
    rubric_cache_dir = rubric_cache_dir or rubric_cfg.get("cache_dir", "./rubrics")
    # CLI flag --regenerate-rubric always wins; otherwise read from config (default: true)
    regenerate_rubric = regenerate_rubric or rubric_cfg.get("regenerate_each_run", True)
    keep_recent_rubrics = rubric_cfg.get("keep_recent", 5)
    gate1_threshold = cfg.get("gate1_threshold", 0.10)
    gate2_threshold = cfg.get("gate2_threshold", 0.10)
    validation_tc_count = 0 if no_rollback else cfg.get("validation_tc_count", 3)
    teacher_temperature = cfg.get("teacher_temperature", 0.3)
    judge_temperature = cfg.get("judge_temperature", 0.2)
    max_retry_per_tc = cfg.get("max_retry_per_tc", 3)
    max_image_pages = cfg.get("max_image_pages", 10)
    max_gif_frames = cfg.get("max_gif_frames", 5)
    watch_skill_hash = rubric_cfg.get("watch_skill_hash", False)

    # --no-skill baseline: zero-shot floor. One round, no Teacher, reuse the
    # cached rubric (so scores are directly comparable to the real run), and
    # write to a separate dir so the real distillation results aren't wiped.
    if no_skill:
        rounds = 1
        dry_run = True
        regenerate_rubric = False
        results_dir = str(Path(results_dir) / "noskill")
        click.echo(
            "[--no-skill] baseline mode: rounds=1, no Teacher, rubric from cache, "
            f"results → {results_dir}"
        )

    if no_feedback:
        click.echo(
            "[--no-feedback] blind-rewrite mode: Teacher rewrites SKILL.md each round "
            "WITHOUT run_log failure data — ablation for feedback-loop value"
        )

    # Test cases file (default to v2 test_cases/)
    if test_cases_file is None:
        default_file = Path(__file__).parent / "test_cases" / f"{skill}.json"
        test_cases_file = str(default_file)
    tc_path = Path(test_cases_file)
    if not tc_path.is_file():
        click.echo(f"[ERROR] test cases file not found: {tc_path}", err=True)
        sys.exit(1)

    all_cases = [
        tc for tc in json.loads(tc_path.read_text()).get("test_cases", []) if "id" in tc
    ]
    if not all_cases:
        click.echo(f"[ERROR] no test cases in {tc_path}", err=True)
        sys.exit(1)
    selected = all_cases[:test_cases] if test_cases else all_cases

    # --workflow / --test-cases filter which TCs are RUN.
    # Rubric uses the full TC pool (all_cases) so the grading yardstick is
    # stable across runs and not skewed by an ad-hoc subset.
    _WORKFLOW_MAP = {
        "a": "create",
        "b": "read",
        "c": "edit",
        "d": "convert",
        "e": "edge",
    }
    if workflow:
        wf_names = {
            _WORKFLOW_MAP.get(w.strip().lower(), w.strip().lower())
            for w in workflow.split(",")
        }
        run_cases = [tc for tc in selected if tc.get("workflow", "create") in wf_names]
        if not run_cases:
            click.echo(
                f"[ERROR] --workflow '{workflow}' matched 0 test cases", err=True
            )
            sys.exit(1)
    else:
        run_cases = selected

    click.echo(
        f"Loaded {len(selected)}/{len(all_cases)} test cases from {tc_path.name}"
        + (f"  (running {len(run_cases)} after --workflow filter)" if workflow else "")
    )
    click.echo(
        f"Config: rounds={rounds}  batch={batch_size}  student={student}  "
        f"teacher={teacher}  judge={judge}  ensemble_n={ensemble_n}  parallel={parallel}"
    )
    click.echo(f"Rubric: cache_dir={rubric_cache_dir}  regenerate={regenerate_rubric}")

    summary = pipeline.run_distillation(
        skill=skill,
        test_cases=run_cases,
        rubric_test_cases=all_cases,
        student_model=student,
        teacher_model=teacher,
        judge_model=judge,
        llm_api_key=os.getenv("OPENROUTER_API_KEY"),
        llm_base_url=pipeline.OPENROUTER_BASE_URL,
        max_rounds=rounds,
        batch_size=batch_size,
        stop_threshold=stop_threshold
        if stop_threshold is not None
        else cfg.get("stop_threshold", 0.7),
        converge_delta=cfg.get("converge_delta", 0.02),
        converge_k=cfg.get("converge_k", 3),
        gate1_threshold=gate1_threshold,
        gate2_threshold=gate2_threshold,
        validation_tc_count=validation_tc_count,
        teacher_temperature=teacher_temperature,
        judge_temperature=judge_temperature,
        max_retry_per_tc=max_retry_per_tc,
        max_image_pages=max_image_pages,
        max_gif_frames=max_gif_frames,
        results_dir=results_dir,
        rubric_cache_dir=rubric_cache_dir,
        skills_dir=skills_dir,
        test_cases_dir=str(tc_path.parent),
        regenerate_rubric=regenerate_rubric,
        watch_skill_hash=watch_skill_hash,
        keep_recent_rubrics=keep_recent_rubrics,
        ensemble_n=ensemble_n,
        sandbox_tmp_root=sandbox_cfg.get("tmp_root", "~/.cache/distill_v2"),
        sandbox_keep_on_fail=sandbox_cfg.get("keep_on_fail", True),
        claude_binary=student_cfg.get("claude_binary", "claude"),
        verbose=verbose,
        dry_run=dry_run,
        resume=resume,
        no_llm_judge=no_llm_judge,
        concurrent_tcs=max(1, parallel),
        no_skill=no_skill,
        no_feedback=no_feedback,
    )

    click.echo("\n" + "=" * 60)
    click.echo("DISTILLATION V2 COMPLETE")
    click.echo("=" * 60)
    click.echo(f"Skill:        {summary['skill']}")
    click.echo(f"Rounds run:   {summary['rounds_run']}")
    click.echo(f"Final score:  {summary['final_score']:.3f}")
    click.echo(
        f"Best round:   {summary['best_round']} (score={summary['best_score']:.3f})"
    )
    click.echo("\nScore history:")
    for entry in summary["score_history"]:
        bar = "█" * int(entry["avg_score"] * 20)
        click.echo(f"  Round {entry['round']:2d}: {entry['avg_score']:.3f} {bar}")
    click.echo(f"\nResults saved to: {Path(results_dir) / skill}")
    click.echo(f"Run ID:       {summary.get('run_id', '-')}")
    click.echo(f"Run manifest: {summary.get('manifest', '-')}")


if __name__ == "__main__":
    main()
