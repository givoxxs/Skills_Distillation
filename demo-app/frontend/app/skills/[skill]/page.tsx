import Link from "next/link";
import { notFound } from "next/navigation";
import { Bi } from "@/components/bi";
import { TopBar } from "@/components/topbar";
import { SkillDetailClient } from "./skill-detail-client";
import {
  apiCallsBySkill,
  workflowsBySkill as MOCK_WORKFLOWS,
} from "@/lib/mock-data";
import {
  fetchAvailableRounds,
  fetchEvalDetail,
  fetchSkillMd,
  fetchSummary,
} from "@/lib/api";
import { displayMetaFor } from "@/lib/display-meta";
import type { EvalEntry, SkillSummary } from "@/lib/types";
import { parseSkillDetailParams, type SkillDetailSearchParams } from "./skill-detail-ui-state";

const BILINGUAL = true;
const SUPPORTED = new Set(["docx", "internal-comms", "slack-gif-creator"]);

export default async function SkillDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ skill: string }>;
  searchParams?: Promise<SkillDetailSearchParams>;
}) {
  const { skill } = await params;
  if (!SUPPORTED.has(skill)) notFound();

  let realSummary;
  let availableRounds: { rounds: number[] };
  let evalEntries: EvalEntry[];
  try {
    [realSummary, availableRounds, evalEntries] = await Promise.all([
      fetchSummary(skill),
      fetchAvailableRounds(skill),
      fetchEvalDetail(skill),
    ]);
  } catch (e) {
    throw new Error(
      `Backend không phản hồi tại ${process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000"}. ` +
        `Đảm bảo \`make dev\` (hoặc \`uvicorn\` riêng) đang chạy.\n\n${(e as Error).message}`
    );
  }

  // Fetch all real SKILL.md files in parallel
  const skillMdResponses = await Promise.all(
    availableRounds.rounds.map((r) => fetchSkillMd(skill, r))
  );
  const skillMdByRound: Record<number, string> = {};
  for (const r of skillMdResponses) {
    skillMdByRound[r.round] = r.content;
  }
  // Fill any gap (e.g. round 0 missing) by inheriting nearest prior round
  for (let r = 0; r <= realSummary.rounds_run; r++) {
    if (skillMdByRound[r]) continue;
    for (let prior = r; prior >= 0; prior--) {
      if (skillMdByRound[prior]) {
        skillMdByRound[r] = skillMdByRound[prior];
        break;
      }
    }
  }

  const meta = displayMetaFor(skill);
  const summary: SkillSummary = {
    ...realSummary,
    vi: meta.vi,
    en: meta.en,
  };

  // Workflows derived from real rubric_cache_keys when available, fallback to mock list
  const workflows =
    Object.keys(realSummary.rubric_cache_keys || {}).length > 0
      ? Object.keys(realSummary.rubric_cache_keys).sort()
      : MOCK_WORKFLOWS[skill] || [];

  // Group real eval entries by round.
  const evalByRound: Record<number, EvalEntry[]> = {};
  for (const entry of evalEntries) {
    (evalByRound[entry.round] ||= []).push(entry as EvalEntry);
  }
  // api_calls.jsonl in the upstream pipeline lacks `round` / `cost_usd` /
  // `latency_ms` / `timestamp` — keep the deterministic mock for the cost
  // bar chart so the panel still renders something meaningful; the UI
  // carries a "demo data" badge there.
  const apiCalls = apiCallsBySkill[skill] || [];
  const initialState = parseSkillDetailParams(await (searchParams || Promise.resolve({})), {
    diffRounds: Array.from({ length: realSummary.rounds_run + 1 }, (_, i) => i),
    evalRounds: realSummary.score_history.map((h) => h.round),
    workflows,
    fallbackFrom: 0,
    fallbackTo: realSummary.best_round,
    fallbackEvalRound: realSummary.score_history[realSummary.score_history.length - 1].round,
  });

  return (
    <>
      <TopBar
        crumbs={[
          { label: <Bi vi="Tổng quan" en="Overview" />, href: "/" },
          { label: "Skills", href: "/" },
          { label: <span className="mono">{summary.skill}</span> },
        ]}
        actions={
          <Link href={`/run?skill=${encodeURIComponent(summary.skill)}`} className="btn btn-sm">
            <Bi vi="Chạy mini cho skill này" en="Run mini for this skill" />
          </Link>
        }
      />
      <SkillDetailClient
        summary={summary}
        workflows={workflows}
        evalByRound={evalByRound}
        apiCalls={apiCalls}
        skillMdByRound={skillMdByRound}
        bilingual={BILINGUAL}
        initialState={initialState}
      />
    </>
  );
}
