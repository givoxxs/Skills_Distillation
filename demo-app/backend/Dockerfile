# Dockerfile lives in demo-app/backend/ but the build context is the
# REPO ROOT so we can COPY the pipeline data alongside the app source.
# Wire it that way in render.yaml (dockerContext: ".").

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── System deps ────────────────────────────────────────────────────────────
# Node 20 (NodeSource) : Claude Code CLI needs Node 20+; Debian bookworm only
#                        ships Node 18 which may lack required runtime APIs.
# libreoffice-writer  : soffice for docx → PDF conversion
# poppler-utils       : pdf2image needs pdftoppm for PDF → PNG pages
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends \
        nodejs \
        libreoffice-writer \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# ── Claude Code CLI ────────────────────────────────────────────────────────
RUN npm install -g @anthropic-ai/claude-code

# ── Python runtime deps ────────────────────────────────────────────────────
RUN pip install \
    "fastapi>=0.135.1,<1.0" \
    "uvicorn[standard]>=0.42.0,<1.0" \
    "pydantic>=2.12.5,<3.0" \
    "httpx>=0.28.0,<1.0" \
    "python-dotenv>=1.0" \
    "openai>=1.0" \
    "anthropic>=0.30" \
    "Pillow>=10.0" \
    "pdf2image>=1.17"

# ── App source ─────────────────────────────────────────────────────────────
COPY demo-app/backend/app/ ./app/

# ── Pipeline data + source ─────────────────────────────────────────────────
# results/stable + test_cases : read-only data for replay mode
# runner/ stages/ utils/ evaluator/ : Python source for live compare execution
# skills/ : SKILL.md definitions and scripts materialised per live run
COPY distillation_v2/results/stable/ /data/distillation_v2/results/stable/
COPY distillation_v2/test_cases/     /data/distillation_v2/test_cases/
COPY distillation_v2/runner/         /data/distillation_v2/runner/
COPY distillation_v2/stages/         /data/distillation_v2/stages/
COPY distillation_v2/utils/          /data/distillation_v2/utils/
COPY distillation_v2/evaluator/      /data/distillation_v2/evaluator/
COPY distillation_v2/skills/         /data/distillation_v2/skills/
COPY distillation_v2/__init__.py     /data/distillation_v2/__init__.py

# data_loader resolves paths from DISTILL_REPO_ROOT.
ENV DISTILL_REPO_ROOT=/data

# Claude Code refuses `--dangerously-skip-permissions` when invoked as root.
# Live compare also writes to /live_runs and /.rubric_cache, so create those
# runtime dirs explicitly before dropping privileges.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /live_runs /.rubric_cache /home/appuser/.cache \
    && chown -R appuser:appuser /app /live_runs /.rubric_cache /home/appuser

ENV HOME=/home/appuser \
    XDG_CACHE_HOME=/home/appuser/.cache

USER appuser

# Render injects $PORT; default 8000 for local docker run.
ENV PORT=8000
EXPOSE 8000

# Hard-coded production origins live in env (ALLOWED_ORIGINS) so the
# image stays redeployable when the frontend domain changes.
ENV ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Run via uvicorn directly (not gunicorn) — SSE long-poll behaves better
# with a single-worker async server. Render's free tier has 0.5 vCPU so
# 1 worker is the right answer anyway.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
