import { Bi } from "@/components/bi";
import { TopBar } from "@/components/topbar";
import { RunClient } from "./run-client";
import { parseRunParams, type RunSearchParams } from "./run-ui-state";

const SKILLS = ["docx", "internal-comms", "slack-gif-creator"] as const;

export default async function RunPage({
  searchParams,
}: {
  searchParams?: Promise<RunSearchParams>;
}) {
  const initialState = parseRunParams(await (searchParams || Promise.resolve({})), SKILLS, "docx");

  return (
    <>
      <TopBar
        crumbs={[
          { label: <Bi vi="Tổng quan" en="Overview" />, href: "/" },
          { label: <Bi vi="Chạy thử" en="Live run" /> },
        ]}
      />
      <RunClient initialSkill={initialState.skill} />
    </>
  );
}
