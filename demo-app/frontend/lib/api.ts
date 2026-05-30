/* Server-side fetch helpers for the FastAPI backend. Used inside Server
 * Components (async page.tsx) so the result is rendered on the server. */

import type { CompareCase, CompareSuggestion, SkillSummary } from "./types";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  process.env.BACKEND_URL ||
  "http://127.0.0.1:8000";

const FETCH_OPTS: RequestInit = {
  // Always refresh — these are static files but they can change between runs.
  // Demo scale is tiny so no caching tradeoff worth tuning.
  cache: "no-store",
};

export type SkillListEntry = {
  name: string;
  rounds_run: number;
  final_score: number;
  best_score: number;
  best_round: number;
  student_model: string;
  teacher_model: string;
};

export type RealSummary = Omit<SkillSummary, "vi" | "en" | "last_run" | "seed">;

export type SkillMdResponse = {
  requested_round: number;
  round: number;
  content: string;
  fallback: boolean;
};

async function get<T>(path: string): Promise<T> {
  const url = `${BACKEND_URL}${path}`;
  const res = await fetch(url, FETCH_OPTS);
  if (!res.ok) {
    throw new Error(`fetch ${path} → ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export function fetchSkills(): Promise<SkillListEntry[]> {
  return get<SkillListEntry[]>("/api/skills");
}

export function fetchSummary(skill: string): Promise<RealSummary> {
  return get<RealSummary>(`/api/skills/${encodeURIComponent(skill)}/summary`);
}

export function fetchAvailableRounds(skill: string): Promise<{ rounds: number[] }> {
  return get<{ rounds: number[] }>(
    `/api/skills/${encodeURIComponent(skill)}/available-rounds`
  );
}

export function fetchSkillMd(skill: string, round: number): Promise<SkillMdResponse> {
  return get<SkillMdResponse>(
    `/api/skills/${encodeURIComponent(skill)}/skill-md?round=${round}`
  );
}

export type EvalDetailEntry = {
  round: number;
  test_case_id: string;
  workflow: string;
  rule_score: number;
  llm_judge_score: number | null;
  hybrid_score: number;
  judge_rationale: string;
  rule_checks: { name: string; passed: boolean; score: number | null; reason: string }[];
  prompt: string;
  output: string;
};

export function fetchEvalDetail(skill: string, round?: number): Promise<EvalDetailEntry[]> {
  const qs = round !== undefined ? `?round=${round}` : "";
  return get<EvalDetailEntry[]>(`/api/skills/${encodeURIComponent(skill)}/eval${qs}`);
}

export { BACKEND_URL };

export type CompareRunResponse = { run_id: string };

export function fetchCompareCases(skill: string): Promise<CompareCase[]> {
  return get<CompareCase[]>(`/api/compare/${encodeURIComponent(skill)}/cases`);
}

export async function createCompareReplayRun(
  skill: string,
  testCaseId: string
): Promise<CompareRunResponse> {
  const res = await fetch(`${BACKEND_URL}/api/compare/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skill, test_case_id: testCaseId }),
  });
  if (!res.ok) throw new Error(`compare replay → ${res.status} ${res.statusText}`);
  return (await res.json()) as CompareRunResponse;
}

export async function createCompareLiveRun(body: {
  skill: string;
  prompt_mode: "test_case" | "custom";
  test_case_id?: string;
  custom_prompt?: string;
  fixture_file?: string;
}): Promise<CompareRunResponse> {
  const res = await fetch(`${BACKEND_URL}/api/compare/live`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`compare live → ${res.status} ${detail}`);
  }
  return (await res.json()) as CompareRunResponse;
}

export function compareReplayStreamUrl(runId: string): string {
  return `${BACKEND_URL}/api/compare/replay/${encodeURIComponent(runId)}/stream`;
}

export function compareLiveStreamUrl(runId: string): string {
  return `${BACKEND_URL}/api/compare/live/${encodeURIComponent(runId)}/stream`;
}

export function compareArtifactUrl(path: string): string {
  // Backend emits root-relative artifact URLs (e.g. "/api/compare/...").
  return path.startsWith("http") ? path : `${BACKEND_URL}${path}`;
}

export function fetchCompareSuggestions(skill: string, limit = 5): Promise<CompareSuggestion[]> {
  return get<CompareSuggestion[]>(
    `/api/compare/${encodeURIComponent(skill)}/suggestions?limit=${limit}`
  );
}
