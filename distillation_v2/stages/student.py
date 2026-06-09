"""Student runner: execute one task via Claude Code CLI inside a Sandbox.

exports: run_student(user_prompt, skill_name, skill_dir, model, config,
           max_retries=3, current_skill_md=None, no_skill=False) -> dict
         make_skip_result(tc, skill, model, round_n, output_dir) -> EvalResult
used_by: pipeline.py (_run_batch -> run_student; skip path -> make_skip_result)
rules:   settings.json MUST set autoCompactEnabled=false + pin the model —
         otherwise the CLI auto-compacts via sonnet over OpenRouter and silently
         burns credits. SKILL.md is copied to cwd/CLAUDE.md so non-Claude
         (OpenRouter) models actually receive the skill. no_skill=True skips the
         skill install (no SKILL.md/scripts/CLAUDE.md/"Use skill" prefix) but
         STILL writes settings.json and copies fixtures — the zero-shot baseline.
agent:   claude-opus-4-8 | anthropic | 2026-06-07 | feat/arena-compare | added no_skill baseline mode

Skill injection strategy:
  - skills/<skill_name>/  → sandbox_home/.claude/skills/<skill_name>/
    (toàn bộ folder skill được copy vào đây, Claude Code tự nhận diện)
  Prompt format: "Use skill <skill_name> to: <user_task_prompt>"

No-skill baseline (no_skill=True): the skill is NOT installed (no SKILL.md, no
scripts, no cwd/CLAUDE.md, no "Use skill X to:" prefix) — only settings.json
(model pin + autoCompactEnabled=false) and input fixtures are set up. Used to
measure the zero-shot floor the skill must beat. Same judge/rubric as normal.

Key behaviors:
  - Runs `claude --bare --model <model> -p "Use skill <skill> to: <prompt>" ...`
    inside Sandbox.
  - Retries up to max_retries on transient failures; skips TC after all attempts fail.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluator.base import CheckResult, EvalResult
from runner.config import RunConfigV2
from runner.logger import AgentLogger
from runner.sandbox import Sandbox
from runner.stream_parser import Event, ParserState, parse_line

_log = logging.getLogger("distillation.v2.student")

_RETRIABLE_STOP_REASONS = frozenset(
    {
        "runner_error",
        "no_end_event",
        "cli_exit_1",
        "cli_exit_2",
        "timeout",
    }
)


# ── Public API ────────────────────────────────────────────────────────────────


def run_student(
    user_prompt: str,
    skill_name: str,
    skill_dir: Path,
    model: str,
    config: RunConfigV2,
    max_retries: int = 3,
    current_skill_md: Path | None = None,
    no_skill: bool = False,
) -> dict[str, Any]:
    """Run the student model on one task, with retry-then-skip on failure.

    Args:
        user_prompt:      The task description (may include fixture file notice).
        skill_name:       Skill folder name, e.g. "docx". Used as slash command name.
        skill_dir:        Path to skills/<skill_name>/ containing SKILL.md + scripts/.
        model:            OpenRouter model ID routed via Claude Code CLI.
        config:           RunConfigV2 with sandbox + path settings.
        max_retries:      Max consecutive attempts before skipping the TC.
        current_skill_md: Working copy of SKILL.md to inject instead of skill_dir/SKILL.md.
        no_skill:         Baseline mode — skip skill installation and the
                          "Use skill X to:" prefix (zero-shot floor measurement).
    """
    prompt = _build_prompt(skill_name, user_prompt, no_skill=no_skill)
    logger = AgentLogger(log_dir=config.log_dir, skill_name=skill_name, model=model)
    logger.log_start(skill_name, model, user_prompt)

    last_result: dict[str, Any] = {}
    for attempt in range(1, max_retries + 1):
        result = _run_once(
            prompt,
            skill_name,
            skill_dir,
            model,
            config,
            logger,
            attempt,
            current_skill_md=current_skill_md,
            no_skill=no_skill,
        )
        last_result = result
        stop = result.get("stop_reason", "")
        is_retriable = any(stop.startswith(r) for r in _RETRIABLE_STOP_REASONS)
        if not is_retriable or attempt == max_retries:
            break
        _log.warning(
            "student: attempt %d/%d failed (%s), retrying...",
            attempt,
            max_retries,
            stop,
        )
        time.sleep(2 * attempt)

    skipped = (
        last_result.get("stop_reason", "").startswith(tuple(_RETRIABLE_STOP_REASONS))
        and last_result.get("_attempt", 1) >= max_retries
    )
    last_result["skipped"] = skipped
    if skipped:
        _log.warning(
            "student: all %d retries failed for %s — TC skipped",
            max_retries,
            skill_name,
        )
    return last_result


def make_skip_result(
    tc: dict[str, Any],
    skill: str,
    model: str,
    round_n: int,
    output_dir: str,
) -> EvalResult:
    """Zero-score EvalResult for a TC where all retry attempts failed."""
    er = EvalResult(
        test_case_id=tc.get("id", "unknown"),
        skill=skill,
        model=model,
        round_n=round_n,
        output_dir=output_dir,
    )
    er.llm_judge_score = 0.0
    er.checks.append(
        CheckResult(
            name="student_ran",
            passed=False,
            score=0.0,
            reason="all retry attempts failed",
        )
    )
    return er


# ── Prompt + skill injection ──────────────────────────────────────────────────


def _build_prompt(skill_name: str, user_prompt: str, no_skill: bool = False) -> str:
    """Build the student prompt.

    Normal mode references the installed skill. Baseline mode (no_skill) returns
    the task verbatim — no skill is installed, so the "Use skill X to:" prefix
    would point at nothing.
    """
    if no_skill:
        return user_prompt
    return f"Use skill {skill_name} to: {user_prompt}"


def _install_skill_in_sandbox(
    sandbox: Sandbox,
    skill_name: str,
    skill_dir: Path,
    model: str = "",
    current_skill_md: Path | None = None,
    no_skill: bool = False,
) -> None:
    """Install skill into the sandbox.

    Three things are set up:
      1. settings.json → sandbox_home/.claude/settings.json
         Forces the CLI to use the student model for ALL internal calls.
         autoCompactEnabled=false prevents silent sonnet API calls on context growth.
      2. skill_dir/ → sandbox_home/.claude/skills/<skill_name>/
         Copy the entire skill folder so Claude-native models can load it.
      3. SKILL.md → sandbox.cwd/CLAUDE.md   ← KEY for non-Claude models
         Claude Code CLI always injects CLAUDE.md from the project cwd into the
         system prompt regardless of which underlying model is used. Without this,
         models routed via OpenRouter (gemma, qwen, etc.) never receive the skill
         instructions and respond with "I don't have a skill for that."
    """
    claude_dir = sandbox.home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    # 1. Force model in settings + disable auto-compaction
    settings: dict[str, object] = {"autoCompactEnabled": False}
    if model:
        settings["model"] = model
    (claude_dir / "settings.json").write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )

    # Baseline mode: settings.json (model pin + autoCompactEnabled=false) is all
    # the student needs. Do NOT copy SKILL.md, scripts, or cwd/CLAUDE.md — the
    # student gets the task with no skill knowledge (zero-shot floor).
    if no_skill:
        _log.debug("no_skill: skipping skill install for %s", skill_name)
        return

    if not skill_dir.is_dir():
        _log.warning(
            "skill_dir not found: %s — skill %s will be missing", skill_dir, skill_name
        )
        return

    # Resolve which SKILL.md to use (teacher working copy takes priority)
    effective_skill_md: Path
    if current_skill_md and Path(current_skill_md).is_file():
        effective_skill_md = Path(current_skill_md)
        _log.debug("using teacher working copy: %s", effective_skill_md)
    else:
        effective_skill_md = skill_dir / "SKILL.md"

    # 2. Copy entire skill folder → sandbox_home/.claude/skills/<skill_name>/
    skills_dst = claude_dir / "skills" / skill_name
    shutil.copytree(skill_dir, skills_dst, dirs_exist_ok=True)
    if effective_skill_md != skill_dir / "SKILL.md":
        shutil.copy2(effective_skill_md, skills_dst / "SKILL.md")

    # Expose skill folder on PYTHONPATH so `from core.<x> import ...` from
    # SKILL.md examples resolves without the student model having to grep/find
    # the source from `/` (a recurring failure mode in weaker SLLMs).
    existing_pp = sandbox.env.get("PYTHONPATH", "")
    sandbox.env["PYTHONPATH"] = (
        f"{skills_dst}{os.pathsep}{existing_pp}" if existing_pp else str(skills_dst)
    )

    # Mirror skill helper folders (core/, scripts/, ...) into the sandbox cwd
    # so an `ls` shows them immediately. PYTHONPATH alone isn't enough — weaker
    # SLLMs still scan `/` with find before trusting the import will work.
    # Files keep their original mtime, so sandbox.list_outputs() (which filters
    # by mtime >= since_ts) won't mistake them for agent-produced artifacts.
    _SKILL_SKIP_NAMES = {".git", "__pycache__", "node_modules", ".npm"}
    for child in skill_dir.iterdir():
        if not child.is_dir() or child.name in _SKILL_SKIP_NAMES:
            continue
        shutil.copytree(child, sandbox.cwd / child.name, dirs_exist_ok=True)

    # 3. Write SKILL.md to cwd/CLAUDE.md so ALL models receive skill instructions
    #    via Claude Code CLI's automatic project-context injection.
    shutil.copy2(effective_skill_md, sandbox.cwd / "CLAUDE.md")
    _log.debug("installed skill %s → %s + cwd/CLAUDE.md", skill_name, skills_dst)


# ── Single attempt ────────────────────────────────────────────────────────────


def _run_once(
    prompt: str,
    skill_name: str,
    skill_dir: Path,
    model: str,
    config: RunConfigV2,
    logger: AgentLogger,
    attempt: int,
    current_skill_md: Path | None = None,
    no_skill: bool = False,
) -> dict[str, Any]:
    start_ts = time.time()
    stop_reason = "unknown"
    iterations = 0
    tokens: dict[str, int] = {"prompt": 0, "completion": 0}
    output_files: list[str] = []

    try:
        with Sandbox(
            name=f"student-{attempt}",
            api_key=config.openrouter_api_key,
            base_url=config.openrouter_base_url,
            parent_tmp=Path(os.path.expanduser(config.sandbox_tmp_root)),
            keep_on_fail=config.sandbox_keep_on_fail,
            claude_binary=config.claude_binary,
        ) as sandbox:
            # Install skill as /<skill_name> slash command + copy scripts
            _install_skill_in_sandbox(
                sandbox,
                skill_name,
                skill_dir,
                model=model,
                current_skill_md=current_skill_md,
                no_skill=no_skill,
            )

            # Copy input fixtures into sandbox cwd
            for f in config.input_files:
                if Path(f).is_file():
                    sandbox.copy_input(Path(f))

            run_start = time.time()
            stop_reason, iterations, tokens, final_text = _stream_claude(
                prompt=prompt,
                model=model,
                config=config,
                sandbox=sandbox,
                logger=logger,
            )
            if final_text:
                _write_agent_final(sandbox.cwd, final_text)
            if config.output_dir:
                output_files = _copy_outputs(
                    sandbox, run_start, Path(config.output_dir)
                )
                if stop_reason == "end_turn" and not output_files:
                    stop_reason = "runner_error: no_output_files"

    except Exception as e:  # noqa: BLE001
        _log.error(
            "student._run_once failed (attempt %d): %s", attempt, e, exc_info=False
        )
        stop_reason = f"runner_error: {type(e).__name__}"
        logger.log_error(0, str(e))

    return {
        "stop_reason": stop_reason,
        "iterations": iterations,
        "output_files": output_files,
        "log_file": logger.log_path,
        "duration_seconds": round(time.time() - start_ts, 2),
        "token_usage": tokens,
        "_attempt": attempt,
    }


# ── Claude CLI subprocess ─────────────────────────────────────────────────────


@dataclass
class _StreamState:
    """Mutable result of streaming a Claude CLI subprocess."""

    stop_reason: str = "no_end_event"
    iterations: int = 0
    tokens: dict[str, int] = field(
        default_factory=lambda: {"prompt": 0, "completion": 0}
    )
    final_text: str = ""


def _build_claude_cmd(prompt: str, model: str, config: RunConfigV2) -> list[str]:
    return [
        config.claude_binary,
        "--model",
        model,
        "-p",
        prompt,
        "--bare",
        "--verbose",
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        "--max-turns",
        str(config.max_turns),
    ]


def _kill_process_group(proc: subprocess.Popen) -> None:
    # SIGKILL the whole process group so children spawned by the student
    # (grep -r /, find /, ...) die with the parent. Falls back to proc.kill()
    # if the proc was not started in a new session (defensive).
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass


def _spawn_stderr_drainer(proc: subprocess.Popen) -> tuple[threading.Thread, list[str]]:
    """Drain stderr in a background thread to prevent pipe deadlock.

    If stderr buffer fills (>64 KB) while we're blocking on stdout reads,
    the child process stalls writing stderr and we stall reading stdout.
    """
    chunks: list[str] = []

    def _drain() -> None:
        if proc.stderr:
            data = proc.stderr.read()
            if data:
                chunks.append(data)

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    return t, chunks


def _spawn_watchdog(
    proc: subprocess.Popen, timeout_seconds: float
) -> tuple[threading.Event, threading.Event]:
    """Kill the subprocess after timeout_seconds total wall-clock time.

    Without this, `for raw_line in proc.stdout` blocks forever when the process
    hangs with stdout still open — proc.wait(timeout=...) only runs AFTER stdout
    is exhausted, so it never fires in the hung case.

    Returns (cancel_event, killed_event). Set cancel_event to disarm the watchdog.
    """
    cancel = threading.Event()
    killed = threading.Event()

    def _watchdog() -> None:
        if not cancel.wait(timeout=timeout_seconds):
            if proc.poll() is None:
                _log.warning(
                    "Watchdog: killing hung subprocess after %ds", timeout_seconds
                )
                killed.set()
                _kill_process_group(proc)

    threading.Thread(target=_watchdog, daemon=True).start()
    return cancel, killed


def _consume_events(
    proc: subprocess.Popen,
    state: _StreamState,
    logger: AgentLogger,
) -> None:
    """Read stream-json events from stdout and fold them into `state`."""
    assert proc.stdout is not None
    parser_state = ParserState()
    for raw_line in proc.stdout:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        for event in parse_line(payload, parser_state):
            _emit(logger, event)
            if event.kind == "end":
                state.stop_reason = event.data.get("stop_reason", state.stop_reason)
                state.iterations = event.data.get("iterations", state.iterations)
                state.tokens = event.data.get("tokens", state.tokens)
                state.final_text = event.data.get("final_text", "")


def _finalize_proc(
    proc: subprocess.Popen,
    stderr_drainer: threading.Thread,
    stderr_chunks: list[str],
    killed_by_watchdog: threading.Event,
    state: _StreamState,
    logger: AgentLogger,
) -> None:
    """Wait for proc + drainer, then set final stop_reason on `state`."""
    stderr_drainer.join(timeout=30)
    stderr_text = stderr_chunks[0] if stderr_chunks else ""

    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _log.warning("Process refused to die after SIGKILL")

    if killed_by_watchdog.is_set():
        state.stop_reason = "timeout"
    elif proc.returncode != 0 and state.stop_reason == "no_end_event":
        state.stop_reason = f"cli_exit_{proc.returncode}"
        if stderr_text:
            logger.log_error(state.iterations, stderr_text.strip()[:500])


def _stream_claude(
    prompt: str,
    model: str,
    config: RunConfigV2,
    sandbox: Sandbox,
    logger: AgentLogger,
) -> tuple[str, int, dict[str, int], str]:
    proc = subprocess.Popen(
        _build_claude_cmd(prompt, model, config),
        env=sandbox.env,
        cwd=str(sandbox.cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        # Isolate the student in its own process group so any shell helpers
        # it spawns (grep, find, ...) can be SIGKILLed together via killpg
        # on watchdog timeout — otherwise they survive as orphans and bleed CPU.
        start_new_session=True,
    )

    state = _StreamState()
    stderr_drainer, stderr_chunks = _spawn_stderr_drainer(proc)
    cancel_watchdog, killed_by_watchdog = _spawn_watchdog(proc, config.timeout_seconds)

    try:
        _consume_events(proc, state, logger)
        cancel_watchdog.set()
        _finalize_proc(
            proc, stderr_drainer, stderr_chunks, killed_by_watchdog, state, logger
        )
    finally:
        if proc.poll() is None:
            _kill_process_group(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    return state.stop_reason, state.iterations, state.tokens, state.final_text


def _emit(logger: AgentLogger, event: Event) -> None:
    d = event.data
    if event.kind == "tool_call":
        logger.log_tool_call(d["iteration"], d["tool"], d.get("args", {}))
    elif event.kind == "tool_result":
        prefix = "[ERROR] " if d.get("is_error") else ""
        logger.log_tool_result(d["iteration"], d["tool"], prefix + d.get("result", ""))
    elif event.kind == "assistant_text":
        logger.log_event(d["iteration"], "assistant_text", {"text": d["text"]})
    elif event.kind == "api_error":
        logger.log_error(d.get("iteration", 0), d.get("error", ""))
    elif event.kind == "end":
        logger.log_end(
            iterations=d.get("iterations", 0),
            stop_reason=d.get("stop_reason", "unknown"),
            duration=d.get("duration_seconds", 0.0),
            tokens=d.get("tokens", {"prompt": 0, "completion": 0}),
        )
    elif event.kind == "start":
        logger.log_event(0, "cli_init", {"session_id": d.get("session_id")})


def _write_agent_final(cwd: Path, text: str) -> None:
    """Persist the agent's final assistant message to agent_final.md so the
    judge can read prints/reports that don't live in produced output files
    (e.g. validate/optimize workflows that print results to stdout)."""
    try:
        (cwd / "agent_final.md").write_text(text, encoding="utf-8")
    except OSError as e:
        _log.warning("failed to write agent_final.md: %s", e)


_OUTPUT_EXTENSIONS = frozenset(
    {
        ".docx",
        ".doc",
        ".pdf",
        ".xlsx",
        ".xls",
        ".csv",
        ".txt",
        ".md",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
    }
)
_SKIP_NAMES = frozenset({"package.json", "package-lock.json", "yarn.lock"})


def _copy_outputs(sandbox: Sandbox, since_ts: float, output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for src in sandbox.list_outputs(since_ts):
        if src.name in _SKIP_NAMES:
            continue
        if src.suffix.lower() not in _OUTPUT_EXTENSIONS:
            continue
        rel = src.relative_to(sandbox.cwd)
        dst = output_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied
