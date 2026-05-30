"use client";

import { useMemo, useRef, useState } from "react";
import { Bi } from "@/components/bi";
import { Icon } from "@/components/icon";
import {
  compareLiveStreamUrl,
  compareReplayStreamUrl,
  createCompareLiveRun,
  createCompareReplayRun,
  type RealSummary,
} from "@/lib/api";
import type {
  CompareArtifact,
  CompareCase,
  ComparePhase,
  CompareResult,
  CompareSideState,
  CompareStep,
} from "@/lib/types";
import { ArenaColumn } from "./arena-column";
import { JudgeVerdict } from "./judge-verdict";

type Props = { summaries: RealSummary[]; casesBySkill: Record<string, CompareCase[]> };
const SKILLS = ["docx", "internal-comms", "slack-gif-creator"] as const;
const EMPTY_SIDE: CompareSideState = { steps: [], artifacts: [], status: "idle" };

export function CompareClient({ summaries, casesBySkill }: Props) {
  const [skill, setSkill] = useState("docx");
  const [mode, setMode] = useState<"replay" | "live">("replay");
  const [promptMode, setPromptMode] = useState<"test_case" | "custom">("test_case");
  const [testCaseId, setTestCaseId] = useState(casesBySkill.docx?.[0]?.id || "");
  const [customPrompt, setCustomPrompt] = useState("");
  const [fixtureFile, setFixtureFile] = useState("");
  const [phase, setPhase] = useState<ComparePhase>("idle");
  const [original, setOriginal] = useState<CompareSideState>(EMPTY_SIDE);
  const [peak, setPeak] = useState<CompareSideState>(EMPTY_SIDE);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState("");
  const esRef = useRef<EventSource | null>(null);

  const summary = summaries.find((s) => s.skill === skill) || summaries[0];
  const cases = useMemo(() => casesBySkill[skill] || [], [casesBySkill, skill]);
  const activeCase = cases.find((c) => c.id === testCaseId) || cases[0];
  const fixtures = useMemo(() => {
    const seen = new Set<string>();
    for (const c of cases) for (const f of c.fixture_files) seen.add(f);
    return [...seen].sort();
  }, [cases]);

  const setSide = (s: "original" | "peak") => (s === "original" ? setOriginal : setPeak);

  function resetRun() {
    setOriginal(EMPTY_SIDE);
    setPeak(EMPTY_SIDE);
    setResult(null);
    setError("");
    setPhase("idle");
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
  }

  function attachStream(url: string) {
    const es = new EventSource(url);
    esRef.current = es;
    es.addEventListener("status", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as { phase: ComparePhase };
      setPhase(d.phase);
      if (d.phase === "run_original") setOriginal((p) => ({ ...p, status: "running" }));
      if (d.phase === "run_peak") {
        setOriginal((p) => (p.status === "running" ? { ...p, status: "done" } : p));
        setPeak((p) => ({ ...p, status: "running" }));
      }
      if (d.phase === "done" || d.phase === "error") {
        setOriginal((p) => ({ ...p, status: d.phase === "error" ? "error" : "done" }));
        setPeak((p) => ({ ...p, status: d.phase === "error" ? "error" : "done" }));
        es.close();
      }
    });
    es.addEventListener("step", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as CompareStep;
      setSide(d.side)((p) => ({ ...p, steps: [...p.steps, d] }));
    });
    es.addEventListener("artifact", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as CompareArtifact;
      setSide(d.side)((p) => ({ ...p, artifacts: [...p.artifacts, d] }));
    });
    es.addEventListener("result", (e) => {
      setResult(JSON.parse((e as MessageEvent).data) as CompareResult);
    });
    es.addEventListener("complete", () => es.close());
    es.onerror = () => { setError("Stream closed. Is the backend running?"); es.close(); };
  }

  async function runCompare() {
    resetRun();
    try {
      if (mode === "replay") {
        const created = await createCompareReplayRun(skill, activeCase.id);
        attachStream(compareReplayStreamUrl(created.run_id));
        return;
      }
      const created = await createCompareLiveRun({
        skill,
        prompt_mode: promptMode,
        test_case_id: promptMode === "test_case" ? activeCase.id : undefined,
        custom_prompt: promptMode === "custom" ? customPrompt : undefined,
        fixture_file: fixtureFile || undefined,
      });
      attachStream(compareLiveStreamUrl(created.run_id));
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const canRun = mode === "replay" || promptMode === "test_case" || customPrompt.trim().length > 0;
  const running = phase !== "idle" && phase !== "done" && phase !== "error";

  return (
    <div className="page stack-lg">
      <section className="compare-header">
        <div>
          <div className="eyebrow">Arena Compare</div>
          <h1 className="h1"><Bi vi="So sánh skill original với skill peak." en="Compare original vs peak skill." /></h1>
          <p className="muted" style={{ maxWidth: 760 }}>
            <Bi vi="Replay hiện artifact thật; Live chạy 2 version skill, stream từng bước rồi judge."
                en="Replay shows real artifacts; Live runs both versions, streams each step, then judges." />
          </p>
        </div>
        <div className="compare-status"><span className="badge">{phase}</span></div>
      </section>

      <section className="compare-controls">
        <label>Skill
          <select className="select" value={skill} onChange={(e) => {
            const next = e.target.value; setSkill(next);
            setTestCaseId(casesBySkill[next]?.[0]?.id || ""); resetRun();
          }}>
            {SKILLS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <div className="segmented">
          <button className={mode === "replay" ? "active" : ""} onClick={() => setMode("replay")}>Replay</button>
          <button className={mode === "live" ? "active" : ""} onClick={() => setMode("live")}>Live judge</button>
        </div>
        <label>Test case
          <select className="select" value={activeCase?.id || ""} onChange={(e) => setTestCaseId(e.target.value)}>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}
          </select>
        </label>
        <button className="btn btn-primary" disabled={!canRun || running} onClick={runCompare}>
          <Icon name="play" size={16} />{mode === "replay" ? "Replay comparison" : "Run live arena"}
        </button>
      </section>

      {mode === "live" && (
        <section className="compare-live-controls">
          <div className="segmented">
            <button className={promptMode === "test_case" ? "active" : ""} onClick={() => setPromptMode("test_case")}>Existing test case</button>
            <button className={promptMode === "custom" ? "active" : ""} onClick={() => setPromptMode("custom")}>Custom prompt</button>
          </div>
          {promptMode === "custom" && (
            <textarea className="textarea" value={customPrompt} onChange={(e) => setCustomPrompt(e.target.value)} aria-label="Custom prompt" />
          )}
          <label>Fixture
            <select className="select" value={fixtureFile} onChange={(e) => setFixtureFile(e.target.value)}>
              <option value="">No fixture / auto from test case</option>
              {fixtures.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </label>
        </section>
      )}

      <section className="compare-prompt panel">
        <div className="panel-header"><h3 className="panel-title">Prompt</h3><span className="badge">best R{summary.best_round}</span></div>
        <div className="panel-body"><p>{promptMode === "custom" && customPrompt.trim() ? customPrompt : activeCase?.prompt}</p></div>
      </section>

      {error && <div className="compare-error">{error}</div>}

      <section className="arena-grid">
        <ArenaColumn title="A · Original Skill (R0)" mode={mode} state={original} result={result} whichSide="original" />
        <ArenaColumn title={`B · Peak Skill R${summary.best_round}`} mode={mode} state={peak} result={result} whichSide="peak" />
      </section>

      <JudgeVerdict result={result} />
    </div>
  );
}
