"""Integration test: run one real TC through the student pipeline.

Usage
-----
# Run with default TC (tc_a01) and default model (from config.yaml):
    pytest tests/test_integration_student.py -v -s

# Override model:
    INTEGRATION_MODEL="google/gemma-4-26b-a4b-it" \
    pytest tests/test_integration_student.py -v -s

# Override prompt:
    INTEGRATION_PROMPT="Create a 2-page report about AI" \
    pytest tests/test_integration_student.py -v -s

# Use Anthropic directly (bypass OpenRouter) — for validating skill correctness:
    INTEGRATION_USE_ANTHROPIC=1 \
    pytest tests/test_integration_student.py -v -s

Model resolution order:
  1. INTEGRATION_MODEL env var
  2. INTEGRATION_USE_ANTHROPIC=1  → uses ANTHROPIC_MODEL (default: claude-haiku-4-5)
  3. Fallback: google/gemma-4-26b-a4b-it via OpenRouter

Requirements
------------
- OPENROUTER_API_KEY set in .env or env  (unless INTEGRATION_USE_ANTHROPIC=1)
- ANTHROPIC_KEY set in .env              (only if INTEGRATION_USE_ANTHROPIC=1)
- `claude` binary on PATH
- Skills folder: distillation_v2/skills/docx/

Output files (if any) are copied to:
    tests/integration_results/<run-timestamp>/
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Allow imports from distillation_v2/ root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner.config import RunConfigV2
from stages.student import run_student

# ── Constants ─────────────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_V2_ROOT = _HERE.parent
_SKILL_DIR = _V2_ROOT / "skills" / "docx"

_DEFAULT_PROMPT = (
    "Create a Word document with a bulleted list of 5 items: "
    "'Design', 'Develop', 'Test', 'Deploy', 'Monitor'. "
    "Use proper Word list formatting."
)

_RESULTS_DIR = _HERE / "integration_results"

# ── Model resolution ─────────────────────────────────────────────────────────

_USE_ANTHROPIC = os.environ.get("INTEGRATION_USE_ANTHROPIC", "") not in ("", "0")
_ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY", "")
_OR_KEY = os.getenv("OPENROUTER_API_KEY", "")


def _resolve_model() -> str:
    """Resolve the model to use for the integration test."""
    if os.environ.get("INTEGRATION_MODEL"):
        return os.environ["INTEGRATION_MODEL"]
    if _USE_ANTHROPIC:
        return os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    return "google/gemma-4-26b-a4b-it"  # same as pipeline default in config.yaml


def _resolve_config(output_dir: Path, log_dir: Path) -> tuple[RunConfigV2, str]:
    """Return (config, model) for the test run."""
    model = _resolve_model()
    if _USE_ANTHROPIC:
        # Call Anthropic API directly (no OpenRouter)
        config = RunConfigV2(
            openrouter_api_key=_ANTHROPIC_KEY,
            openrouter_base_url="",  # empty → Sandbox won't set ANTHROPIC_BASE_URL
            log_dir=str(log_dir),
            output_dir=str(output_dir),
            sandbox_keep_on_fail=True,
            verbose=True,
        )
    else:
        config = RunConfigV2(
            log_dir=str(log_dir),
            output_dir=str(output_dir),
            sandbox_keep_on_fail=True,
            verbose=True,
        )
    return config, model


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_prompt() -> str:
    return os.environ.get("INTEGRATION_PROMPT", _DEFAULT_PROMPT)


def _copy_outputs_to_results(output_dir: Path, log_dir: Path, run_label: str) -> Path:
    dst = _RESULTS_DIR / run_label
    dst.mkdir(parents=True, exist_ok=True)
    for f in output_dir.iterdir():
        if f.is_dir():
            shutil.copytree(f, dst / f.name, dirs_exist_ok=True)
        else:
            shutil.copy2(f, dst / f.name)
    # Copy JSONL logs alongside output files
    logs_dst = dst / "logs"
    if log_dir.exists() and any(log_dir.iterdir()):
        shutil.copytree(log_dir, logs_dst, dirs_exist_ok=True)
    return dst


# ── Skip guards ──────────────────────────────────────────────────────────────

_missing_skill = not _SKILL_DIR.is_dir()
_missing_claude = shutil.which("claude") is None

if _USE_ANTHROPIC:
    _missing_key = not _ANTHROPIC_KEY
    _key_label = "ANTHROPIC_KEY"
else:
    _missing_key = not _OR_KEY
    _key_label = "OPENROUTER_API_KEY"

_skip_reason = (
    f"{_key_label} not set"
    if _missing_key
    else "skills/docx/ not found"
    if _missing_skill
    else "`claude` binary not on PATH"
    if _missing_claude
    else None
)


# ── Test ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(_skip_reason is not None, reason=_skip_reason or "")
def test_student_runs_real_tc(tmp_path):
    """Run tc_a01 (or INTEGRATION_PROMPT) through the real Claude Code CLI.

    Asserts:
      - stop_reason is not a runner_error
      - iterations > 0  (model actually did work)
      - token_usage prompt > 0
      - at least one output file produced
    """
    prompt = _get_prompt()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    config, model = _resolve_config(output_dir, log_dir)

    print(f"\n[integration] model     : {model}")
    print(
        f"[integration] via       : {'Anthropic direct' if _USE_ANTHROPIC else 'OpenRouter'}"
    )
    print(f"[integration] prompt    : {prompt[:80]}...")
    print(f"[integration] skill_dir : {_SKILL_DIR}")
    print(f"[integration] output_dir: {output_dir}")

    result = run_student(
        user_prompt=prompt,
        skill_name="docx",
        skill_dir=_SKILL_DIR,
        model=model,
        config=config,
        max_retries=1,
    )

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"\n[integration] stop_reason : {result.get('stop_reason')}")
    print(f"[integration] iterations  : {result.get('iterations')}")
    print(f"[integration] token_usage : {result.get('token_usage')}")
    print(f"[integration] output_files: {result.get('output_files')}")
    print(f"[integration] duration    : {result.get('duration_seconds')}s")

    # ── Copy outputs + logs to tests/integration_results/ ────────────────────
    run_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    copied_to = _copy_outputs_to_results(output_dir, log_dir, run_label)
    print(f"[integration] results saved → {copied_to}")
    print(f"[integration] logs saved    → {copied_to / 'logs'}")

    # ── Assertions ────────────────────────────────────────────────────────────
    assert not result.get("skipped"), "TC was skipped — all retries failed"
    assert not result.get("stop_reason", "").startswith(
        "runner_error"
    ), f"Runner error: {result.get('stop_reason')}"
    assert result.get("iterations", 0) > 0, (
        "iterations=0: model never ran (0-token exit). "
        "Check sandbox skill installation or claude binary."
    )
    assert (
        result.get("token_usage", {}).get("prompt", 0) > 0
    ), "prompt tokens=0: Claude CLI exited without calling the model."
    assert result.get(
        "output_files"
    ), "No output files produced. Agent ran but created nothing."
