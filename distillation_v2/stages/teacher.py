"""Teacher: rewrite SKILL.md once per round using all batch run_log.md files.

v2 change vs v1: Teacher is called ONCE per round (not per batch).
It receives the concatenated run_logs from all batches in the round.

exports: rewrite(skill_md_path, run_logs, ..., no_feedback=False) -> str
used_by: pipeline.py (_apply_teacher_step -> teacher_rewrite)
rules:   When no_feedback=True, run_logs are ignored and the teacher rewrites
         the SKILL.md with only the generic "improve for small models" instruction
         — used as an ablation to isolate whether the feedback loop (not just the
         teacher's general rewriting ability) drives score improvements.
agent:   claude-sonnet-4-6 | anthropic | 2026-06-08 | feat/arena-compare | add no_feedback blind-rewrite mode
"""

from __future__ import annotations

import logging
import time
from pathlib import Path


from utils import write_api_call
from utils.llm_call import call_llm

_log = logging.getLogger("distillation.v2.teacher")

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 8192

_SYSTEM_PROMPT = """You are an expert technical writer specializing in AI agent skill definitions \
optimized for small language models (7B–30B params).

## Context

The student model has limited reasoning capacity. It benefits from:
- Short, direct instructions with one clear action per step
- Concrete code examples it can copy and adapt
- Explicit fallbacks when something fails
- No multi-step self-verification loops (these confuse small models)

## Your Task

Rewrite the provided SKILL.md to fix failures identified in the execution logs.
Output ONLY the new SKILL.md content — no explanation, no markdown wrapper.

## Rules

### What you MUST do
1. **Fix the failures** — address each failure pattern from the run logs directly. \
Add a concrete code fix or clarification for each.
2. **Preserve what works** — do not weaken or remove instructions that made test cases pass.
3. **Add a "Common Mistakes" section** at the bottom based on run_log failures, \
if one does not already exist. Update it if it does.
4. **Provide a minimal working code template** for the most common task pattern \
(create a simple document). Keep it copy-paste ready.
5. **Add fallback strategies** where the model repeatedly gets stuck. \
Format: "If X fails, try Y instead."

### What you MUST NOT do
6. **Do not add self-check loops or verification checklists.** \
Phrases like "Before proceeding, answer these N questions..." cause small models \
to mistake the check itself as completing the task.
7. **Do not pad the output.** Longer is not better. Remove redundant instructions, \
repeated warnings, or obsolete examples if they no longer apply.
8. **Do not add sections the model cannot act on** — no meta-commentary, \
no rationale blocks, no "why this matters" paragraphs.

### Length guidance
Add content only when it directly fixes a failure. \
Remove content when it is redundant or contradicts a fix. \
Shorter is acceptable if it improves clarity."""


def rewrite(
    skill_md_path: str | Path,
    run_logs: list[str],
    model: str = DEFAULT_MODEL,
    round_n: int = 0,
    dry_run: bool = False,
    anthropic_api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.3,
    no_feedback: bool = False,
) -> str:
    """Rewrite SKILL.md using all batch run_logs from the current round.

    Args:
        skill_md_path: Path to current SKILL.md.
        run_logs:      List of run_log.md strings (one per batch).
        model:         Teacher model ID.
        round_n:       Current round number (for logging).
        dry_run:       If True, return unchanged SKILL.md without API call.
        anthropic_api_key: OpenRouter API key (required).
        no_feedback:   If True, ignore run_logs and issue a generic "improve for
                       small models" instruction (blind-rewrite ablation).

    Returns:
        New SKILL.md content as a string.
    """
    skill_md_path = Path(skill_md_path)
    current_md = skill_md_path.read_text(encoding="utf-8")

    if dry_run:
        _log.info("teacher: dry_run — skipping API call")
        return current_md

    if not anthropic_api_key:
        raise RuntimeError("teacher requires an OpenRouter API key")
    api_key = anthropic_api_key

    if no_feedback:
        user_prompt = _build_blind_prompt(current_md, round_n)
        n_logs_logged = 0
    else:
        user_prompt = _build_prompt(current_md, run_logs, round_n)
        n_logs_logged = len(run_logs)
    return _call_api(
        user_prompt, model, api_key, round_n, n_logs_logged, base_url, temperature
    )


def _build_prompt(current_md: str, run_logs: list[str], round_n: int) -> str:
    combined_logs = "\n\n---\n\n".join(
        f"### Batch {i + 1}\n\n{log}" for i, log in enumerate(run_logs)
    )
    return (
        f"Below is the current SKILL.md and execution logs from Round {round_n} "
        f"({len(run_logs)} batch(es)).\n\n"
        "Rewrite SKILL.md to fix the identified problems. Follow the rules in your system prompt.\n\n"
        "---\n# Current SKILL.md\n\n"
        f"{current_md}\n\n"
        "---\n# Round Execution Logs (all batches)\n\n"
        f"{combined_logs}\n\n"
        "---\nNow write the improved SKILL.md:"
    )


def _build_blind_prompt(current_md: str, round_n: int) -> str:
    """Blind-rewrite prompt: no run_logs, only the current SKILL.md.

    Used for the no-feedback ablation. The teacher must improve the skill
    definition using only its own knowledge of what works for small models,
    without seeing any failure evidence from the student runs.
    """
    return (
        f"Below is the current SKILL.md (Round {round_n}).\n\n"
        "Your task: rewrite it to make it work better for small language models "
        "(7B–30B params). Apply the rules in your system prompt.\n\n"
        "You have no execution logs — improve based on your general knowledge of "
        "what makes skill definitions effective for small models.\n\n"
        "---\n# Current SKILL.md\n\n"
        f"{current_md}\n\n"
        "---\nNow write the improved SKILL.md:"
    )


def _call_api(
    user_prompt: str,
    model: str,
    api_key: str,
    round_n: int,
    n_logs: int,
    base_url: str | None = None,
    temperature: float = 0.3,
) -> str:
    delays = [3, 6, 15]
    last_exc: Exception | None = None
    start = time.time()

    for attempt, delay in enumerate([0] + delays):
        if delay:
            _log.warning(
                "LLM overloaded, retry in %ds (attempt %d)", delay, attempt + 1
            )
            time.sleep(delay)
        try:
            output, usage = call_llm(
                system=_SYSTEM_PROMPT,
                user=user_prompt,
                model=model,
                api_key=api_key,
                max_tokens=MAX_TOKENS,
                base_url=base_url,
                temperature=temperature,
            )
            if not output:
                raise RuntimeError("Teacher returned empty response")
            write_api_call(
                {
                    "type": "teacher",
                    "model": model,
                    "round": round_n,
                    "n_run_logs": n_logs,
                    **usage,
                    "elapsed_s": round(time.time() - start, 2),
                }
            )
            return output
        except Exception as e:  # noqa: BLE001
            if hasattr(e, "status_code") and getattr(e, "status_code", None) == 529:
                last_exc = e
                continue
            write_api_call(
                {
                    "type": "teacher",
                    "model": model,
                    "round": round_n,
                    "error": str(e),
                    "elapsed_s": round(time.time() - start, 2),
                }
            )
            raise

    raise RuntimeError(
        f"LLM API still overloaded after {len(delays)} retries"
    ) from last_exc
