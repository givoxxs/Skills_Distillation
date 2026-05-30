export type ScorePoint = { round: number; avg_score: number };

export type SkillSummary = {
  skill: string;
  vi: string;             // display label injected client-side from display-meta
  en?: string;
  student_model: string;
  teacher_model: string;
  judge_model: string;
  batch_size: number;
  rounds_run: number;
  final_score: number;
  best_round: number;
  best_score: number;
  score_history: ScorePoint[];
  rubric_cache_keys: Record<string, string>;
  last_run?: string;
  seed?: number;
};

export type RuleCheck = { name: string; passed: boolean; reason: string };

export type EvalEntry = {
  round: number;
  test_case_id: string;
  workflow: string;
  rule_score: number;
  llm_judge_score: number | null;
  hybrid_score: number;
  judge_rationale: string;
  rule_checks: RuleCheck[];
  prompt: string;
  output: string;
};

export type ApiCall = {
  round: number;
  stage: "student" | "judge" | "teacher";
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  latency_ms: number;
  timestamp: string;
};

export type Kpis = {
  skills_count: number;
  total_improvement_pct: number;
  best_peak: { skill: string; score: number; round: number };
  total_cost: number;
};

export type CompareWinner = "original" | "peak" | "tie";
export type ComparePhase = "idle" | "queued" | "running" | "run_original" | "run_peak" | "judge" | "done" | "error";

export type CompareSuggestion = {
  test_case_id: string;
  name: string;
  original: number;
  peak: number;
  delta: number;
};

export type CompareCase = {
  id: string;
  workflow: string;
  name: string;
  prompt: string;
  expected_behavior: string;
  fixture_files: string[];
};

export type CompareSideResult = {
  label: string;
  round: number;
  skill_md_round: number;
  hybrid_score?: number;
  rule_score?: number;
  llm_judge_score?: number | null;
  rule_checks?: { name: string; passed: boolean; score?: number | null; reason: string }[];
  judge_rationale?: string;
  output?: string;
};

export type CompareResult = {
  skill?: string;
  test_case_id?: string;
  winner: CompareWinner;
  best_round?: number;
  original?: CompareSideResult;
  peak?: CompareSideResult;
  score_original?: number;
  score_peak?: number;
  rationale?: string;
  judge_model?: string;
  student_model?: string;
  elapsed_s?: number;
  original_output_files?: string[];
  peak_output_files?: string[];
};

export type CompareStep = {
  side: "original" | "peak";
  kind: "start" | "cli_init" | "tool_call" | "tool_result" | "assistant_text" | "end" | "api_error" | string;
  iteration?: number | null;
  tool?: string | null;
  args?: { command?: string; description?: string; [k: string]: unknown } | null;
  result?: string | null;
  text?: string | null;
  stop_reason?: string | null;
  duration_seconds?: number | null;
  tokens?: { prompt?: number; completion?: number; total?: number } | null;
  ts?: string | null;
};

export type CompareArtifact = {
  side: "original" | "peak";
  kind: "pdf" | "docx" | "text" | "png";
  label: string;
  url?: string;
  text?: string;
};

export type CompareSideState = {
  steps: CompareStep[];
  artifacts: CompareArtifact[];
  status: "idle" | "running" | "done" | "error";
};
