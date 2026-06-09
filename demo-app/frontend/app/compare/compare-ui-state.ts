import type { ComparePhase, CompareResult } from "@/lib/types";

type TimelineState = "done" | "active" | "pending" | "error";

export type PhaseStep = {
  key: "queued" | "running" | "judge" | "done";
  label: string;
  state: TimelineState;
};

export type CompareMode = "replay" | "live";
export type PromptMode = "test_case" | "custom";

export type CompareQueryState = {
  skill?: string;
  mode?: CompareMode;
  testCaseId?: string;
  promptMode?: PromptMode;
  fixtureFile?: string;
};

type SearchParamValue = string | string[] | undefined;
export type CompareSearchParams = Record<string, SearchParamValue>;

const PHASE_ORDER: ComparePhase[] = [
  "idle",
  "queued",
  "running",
  "run_original",
  "run_peak",
  "judge",
  "done",
];

function phaseRank(phase: ComparePhase): number {
  if (phase === "error") return Number.MAX_SAFE_INTEGER;
  const rank = PHASE_ORDER.indexOf(phase);
  return rank === -1 ? 0 : rank;
}

function timelineState(phase: ComparePhase, active: ComparePhase[], doneBefore: ComparePhase): TimelineState {
  if (phase === "error") return "error";
  if (active.includes(phase)) return "active";
  return phaseRank(phase) > phaseRank(doneBefore) ? "done" : "pending";
}

export function comparePhaseSteps(phase: ComparePhase): PhaseStep[] {
  return [
    {
      key: "queued",
      label: "Queued",
      state: timelineState(phase, ["queued"], "queued"),
    },
    {
      key: "running",
      label: "Run A/B",
      state: timelineState(phase, ["running", "run_original", "run_peak"], "run_peak"),
    },
    {
      key: "judge",
      label: "Judge",
      state: timelineState(phase, ["judge"], "judge"),
    },
    {
      key: "done",
      label: "Done",
      state: phase === "done" ? "active" : phase === "error" ? "error" : "pending",
    },
  ];
}

export function modeHelpText(mode: CompareMode): string {
  if (mode === "replay") {
    return "Replay is deterministic: it loads stored artifacts and saved evaluation scores for the selected test case.";
  }
  return "Live judge runs original and peak skills now, streams both sides, then judges. Requires OPENROUTER_API_KEY on the backend.";
}

export function normalizeCompareError(message: string): string {
  if (/OPENROUTER_API_KEY/i.test(message)) {
    return "Live judge needs OPENROUTER_API_KEY in the backend .env before it can run.";
  }
  if (/Stream closed|EventSource|Failed to fetch/i.test(message)) {
    return "The compare stream closed. Check that the FastAPI backend is still running on port 8000.";
  }
  return message;
}

export function parseCompareQuery(
  search: string,
  validSkills: readonly string[],
  fallbackSkill: string,
): CompareQueryState {
  const params = new URLSearchParams(search);
  return parseCompareParams(
    {
      skill: params.get("skill") || undefined,
      mode: params.get("mode") || undefined,
      case: params.get("case") || undefined,
      prompt: params.get("prompt") || undefined,
      fixture: params.get("fixture") || undefined,
    },
    validSkills,
    fallbackSkill,
  );
}

function firstParam(value: SearchParamValue): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

export function parseCompareParams(
  params: CompareSearchParams,
  validSkills: readonly string[],
  fallbackSkill: string,
): CompareQueryState {
  const modeParam = firstParam(params.mode);
  const promptParam = firstParam(params.prompt);
  const fixtureParam = firstParam(params.fixture);
  const caseParam = firstParam(params.case);
  const skill = firstParam(params.skill) || "";

  return {
    skill: validSkills.includes(skill) ? skill : fallbackSkill,
    mode: modeParam === "live" ? "live" : modeParam === "replay" ? "replay" : undefined,
    testCaseId: caseParam || undefined,
    promptMode: promptParam === "custom" ? "custom" : promptParam === "test_case" ? "test_case" : undefined,
    fixtureFile: fixtureParam || undefined,
  };
}

export function buildCompareQuery(state: CompareQueryState): string {
  const params = new URLSearchParams();
  if (state.skill) params.set("skill", state.skill);
  if (state.mode) params.set("mode", state.mode);
  if (state.testCaseId) params.set("case", state.testCaseId);
  if (state.promptMode) params.set("prompt", state.promptMode);
  if (state.fixtureFile) params.set("fixture", state.fixtureFile);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function scoreDeltaLabel(result: Pick<CompareResult, "winner" | "score_original" | "score_peak" | "original" | "peak">): string {
  if (result.winner === "tie") return "Tie";
  const original = result.score_original ?? result.original?.hybrid_score;
  const peak = result.score_peak ?? result.peak?.hybrid_score;
  if (typeof original !== "number" || typeof peak !== "number") {
    return result.winner === "peak" ? "Peak wins" : "Original wins";
  }
  const delta = Math.abs(peak - original).toFixed(3);
  return result.winner === "peak" ? `Peak +${delta}` : `Original +${delta}`;
}
