import { Bi } from "@/components/bi";
import { TopBar } from "@/components/topbar";
import { fetchCompareCases, fetchSummary } from "@/lib/api";
import { CompareClient } from "./compare-client";

const SKILLS = ["docx", "internal-comms", "slack-gif-creator"] as const;

export default async function ComparePage() {
  const [summaries, casesBySkillEntries] = await Promise.all([
    Promise.all(SKILLS.map(fetchSummary)),
    Promise.all(SKILLS.map(async (skill) => [skill, await fetchCompareCases(skill)] as const)),
  ]);
  const casesBySkill = Object.fromEntries(casesBySkillEntries);

  return (
    <>
      <TopBar
        crumbs={[
          { label: <Bi vi="Tổng quan" en="Overview" />, href: "/" },
          { label: <Bi vi="So sánh" en="Compare" /> },
        ]}
      />
      <CompareClient summaries={summaries} casesBySkill={casesBySkill} />
    </>
  );
}
