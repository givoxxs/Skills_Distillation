import { Bi } from "@/components/bi";
import { TopBar } from "@/components/topbar";
import { fetchCompareCases, fetchCompareSuggestions, fetchSummary } from "@/lib/api";
import { CompareClient } from "./compare-client";
import { parseCompareParams, type CompareSearchParams } from "./compare-ui-state";

const SKILLS = ["docx", "internal-comms", "slack-gif-creator"] as const;

export default async function ComparePage({
  searchParams,
}: {
  searchParams?: Promise<CompareSearchParams>;
}) {
  const initialState = parseCompareParams(await (searchParams || Promise.resolve({})), SKILLS, "docx");
  const [summaries, casesBySkillEntries, suggestionsBySkillEntries] = await Promise.all([
    Promise.all(SKILLS.map(fetchSummary)),
    Promise.all(SKILLS.map(async (skill) => [skill, await fetchCompareCases(skill)] as const)),
    Promise.all(SKILLS.map(async (skill) => [skill, await fetchCompareSuggestions(skill)] as const)),
  ]);
  const casesBySkill = Object.fromEntries(casesBySkillEntries);
  const suggestionsBySkill = Object.fromEntries(suggestionsBySkillEntries);

  return (
    <>
      <TopBar
        crumbs={[
          { label: <Bi vi="Tổng quan" en="Overview" />, href: "/" },
          { label: <Bi vi="So sánh" en="Compare" /> },
        ]}
      />
      <CompareClient
        summaries={summaries}
        casesBySkill={casesBySkill}
        suggestionsBySkill={suggestionsBySkill}
        initialState={initialState}
      />
    </>
  );
}
