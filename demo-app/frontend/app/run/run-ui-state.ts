type SearchParamValue = string | string[] | undefined;

export type RunSearchParams = Record<string, SearchParamValue>;

export type RunQueryState = {
  skill: string;
};

function firstParam(value: SearchParamValue): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

export function parseRunParams(
  params: RunSearchParams,
  validSkills: readonly string[],
  fallbackSkill: string,
): RunQueryState {
  const skill = firstParam(params.skill) || "";
  return {
    skill: validSkills.includes(skill) ? skill : fallbackSkill,
  };
}

export function parseRunQuery(
  search: string,
  validSkills: readonly string[],
  fallbackSkill: string,
): RunQueryState {
  const params = new URLSearchParams(search);
  return parseRunParams({ skill: params.get("skill") || undefined }, validSkills, fallbackSkill);
}

export function buildRunQuery(state: RunQueryState): string {
  const params = new URLSearchParams();
  if (state.skill) params.set("skill", state.skill);
  const query = params.toString();
  return query ? `?${query}` : "";
}
