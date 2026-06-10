export type SkillDetailSortKey =
  | "test_case_id"
  | "workflow"
  | "rule_score"
  | "llm_judge_score"
  | "hybrid_score";

export type SkillDetailSortDir = "asc" | "desc";

export type SkillDetailQueryState = {
  fromRound: number;
  toRound: number;
  evalRound: number;
  workflow: string;
  sortKey: SkillDetailSortKey;
  sortDir: SkillDetailSortDir;
  testCaseId?: string;
};

type SearchParamValue = string | string[] | undefined;
export type SkillDetailSearchParams = Record<string, SearchParamValue>;

type ParseOptions = {
  diffRounds: readonly number[];
  evalRounds: readonly number[];
  workflows: readonly string[];
  fallbackFrom: number;
  fallbackTo: number;
  fallbackEvalRound: number;
};

const SORT_KEYS: SkillDetailSortKey[] = [
  "test_case_id",
  "workflow",
  "rule_score",
  "llm_judge_score",
  "hybrid_score",
];

function firstParam(value: SearchParamValue): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

function parseAllowedInt(value: string | undefined, allowed: readonly number[], fallback: number): number {
  if (!value) return fallback;
  const parsed = Number.parseInt(value, 10);
  return allowed.includes(parsed) ? parsed : fallback;
}

function parseWorkflow(value: string | undefined, workflows: readonly string[]): string {
  if (!value || value === "all") return "all";
  return workflows.includes(value) ? value : "all";
}

function parseSortKey(value: string | undefined): SkillDetailSortKey {
  return SORT_KEYS.includes(value as SkillDetailSortKey) ? (value as SkillDetailSortKey) : "hybrid_score";
}

function parseSortDir(value: string | undefined): SkillDetailSortDir {
  return value === "asc" ? "asc" : "desc";
}

export function parseSkillDetailParams(
  params: SkillDetailSearchParams,
  options: ParseOptions,
): SkillDetailQueryState {
  return {
    fromRound: parseAllowedInt(firstParam(params.from), options.diffRounds, options.fallbackFrom),
    toRound: parseAllowedInt(firstParam(params.to), options.diffRounds, options.fallbackTo),
    evalRound: parseAllowedInt(firstParam(params.round), options.evalRounds, options.fallbackEvalRound),
    workflow: parseWorkflow(firstParam(params.workflow), options.workflows),
    sortKey: parseSortKey(firstParam(params.sort)),
    sortDir: parseSortDir(firstParam(params.dir)),
    testCaseId: firstParam(params.case) || undefined,
  };
}

export function parseSkillDetailQuery(search: string, options: ParseOptions): SkillDetailQueryState {
  const params = new URLSearchParams(search);
  return parseSkillDetailParams(
    {
      from: params.get("from") || undefined,
      to: params.get("to") || undefined,
      round: params.get("round") || undefined,
      workflow: params.get("workflow") || undefined,
      sort: params.get("sort") || undefined,
      dir: params.get("dir") || undefined,
      case: params.get("case") || undefined,
    },
    options,
  );
}

export function buildSkillDetailQuery(state: SkillDetailQueryState): string {
  const params = new URLSearchParams();
  params.set("from", String(state.fromRound));
  params.set("to", String(state.toRound));
  params.set("round", String(state.evalRound));
  params.set("workflow", state.workflow);
  params.set("sort", state.sortKey);
  params.set("dir", state.sortDir);
  if (state.testCaseId) params.set("case", state.testCaseId);
  return `?${params.toString()}`;
}
