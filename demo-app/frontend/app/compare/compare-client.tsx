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
  CompareCase,
  CompareLogEntry,
  ComparePhase,
  CompareResult,
  CompareSideResult,
} from "@/lib/types";

type Props = {
  summaries: RealSummary[];
  casesBySkill: Record<string, CompareCase[]>;
};

const SKILLS = ["docx", "internal-comms", "slack-gif-creator"] as const;

function fmtScore(v: number | null | undefined): string {
  return typeof v === "number" ? v.toFixed(3) : "n/a";
}

function winnerLabel(winner?: string): string {
  if (winner === "peak") return "Peak wins";
  if (winner === "original") return "Original wins";
  if (winner === "tie") return "Tie";
  return "No result";
}

export function CompareClient({ summaries, casesBySkill }: Props) {
  const [skill, setSkill] = useState<string>("docx");
  const [mode, setMode] = useState<"replay" | "live">("replay");
  const [promptMode, setPromptMode] = useState<"test_case" | "custom">("test_case");
  const [testCaseId, setTestCaseId] = useState<string>(casesBySkill.docx?.[0]?.id || "");
  const [customPrompt, setCustomPrompt] = useState("");
  const [fixtureFile, setFixtureFile] = useState("");
  const [phase, setPhase] = useState<ComparePhase>("idle");
  const [logs, setLogs] = useState<CompareLogEntry[]>([]);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);

  const summary = summaries.find((s) => s.skill === skill) || summaries[0];
  const cases = useMemo(() => casesBySkill[skill] || [], [casesBySkill, skill]);
  const activeCase = cases.find((c) => c.id === testCaseId) || cases[0];
  const fixtures = useMemo(() => {
    const seen = new Set<string>();
    for (const c of cases) for (const f of c.fixture_files) seen.add(f);
    return [...seen].sort();
  }, [cases]);

  function resetRun() {
    setLogs([]);
    setResult(null);
    setError("");
    setPhase("idle");
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }

  function attachStream(url: string) {
    const es = new EventSource(url);
    eventSourceRef.current = es;
    es.addEventListener("status", (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { phase: ComparePhase };
      setPhase(data.phase);
      if (data.phase === "done" || data.phase === "error") es.close();
    });
    es.addEventListener("log", (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { side: string; tag: string; line: string };
      setLogs((prev) => [...prev, { kind: "log", ...data }]);
    });
    es.addEventListener("jsonl", (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { source: string; side: string; record: unknown };
      setLogs((prev) => [...prev, { kind: "jsonl", ...data }]);
    });
    es.addEventListener("result", (e) => {
      setResult(JSON.parse((e as MessageEvent).data) as CompareResult);
    });
    es.addEventListener("complete", () => es.close());
    es.onerror = () => {
      setError("Stream closed. Check that the backend is still running.");
      es.close();
    };
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

  const canRun =
    mode === "replay" ||
    promptMode === "test_case" ||
    customPrompt.trim().length > 0;

  return (
    <div className="page stack-lg">
      <section className="compare-header">
        <div>
          <div className="eyebrow">Arena Compare</div>
          <h1 className="h1">
            <Bi vi="So sánh skill original với skill peak." en="Compare original skill against peak skill." />
          </h1>
          <p className="muted" style={{ maxWidth: 760 }}>
            <Bi
              vi="Replay dùng log JSONL có sẵn; Live chạy thật hai version skill rồi gọi judge."
              en="Replay uses existing JSONL logs; Live runs both skill versions and calls the judge."
            />
          </p>
        </div>
        <div className="compare-status">
          <span className="badge">{phase}</span>
          {result && <span className="badge badge-success">{winnerLabel(result.winner)}</span>}
        </div>
      </section>

      <section className="compare-controls">
        <label>
          Skill
          <select
            className="select"
            value={skill}
            onChange={(e) => {
              const next = e.target.value;
              setSkill(next);
              setTestCaseId(casesBySkill[next]?.[0]?.id || "");
              resetRun();
            }}
          >
            {SKILLS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>

        <div className="segmented">
          <button className={mode === "replay" ? "active" : ""} onClick={() => setMode("replay")}>Replay</button>
          <button className={mode === "live" ? "active" : ""} onClick={() => setMode("live")}>Live judge</button>
        </div>

        <label>
          Test case
          <select className="select" value={activeCase?.id || ""} onChange={(e) => setTestCaseId(e.target.value)}>
            {cases.map((c) => (
              <option key={c.id} value={c.id}>{c.id} · {c.name}</option>
            ))}
          </select>
        </label>

        <button className="btn btn-primary" disabled={!canRun || phase === "queued"} onClick={runCompare}>
          <Icon name="play" size={16} />
          {mode === "replay" ? "Replay comparison" : "Run live arena"}
        </button>
      </section>

      {mode === "live" && (
        <section className="compare-live-controls">
          <div className="segmented">
            <button className={promptMode === "test_case" ? "active" : ""} onClick={() => setPromptMode("test_case")}>Existing test case</button>
            <button className={promptMode === "custom" ? "active" : ""} onClick={() => setPromptMode("custom")}>Custom prompt</button>
          </div>
          {promptMode === "custom" && (
            <textarea
              className="textarea"
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              aria-label="Custom prompt for both skill versions"
            />
          )}
          <label>
            Fixture
            <select className="select" value={fixtureFile} onChange={(e) => setFixtureFile(e.target.value)}>
              <option value="">No fixture / auto from test case</option>
              {fixtures.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </label>
        </section>
      )}

      <section className="compare-prompt panel">
        <div className="panel-header">
          <h3 className="panel-title">Prompt</h3>
          <span className="badge">best R{summary.best_round}</span>
        </div>
        <div className="panel-body">
          <p>{promptMode === "custom" && customPrompt.trim() ? customPrompt : activeCase?.prompt}</p>
        </div>
      </section>

      {error && <div className="compare-error">{error}</div>}

      <section className="arena-grid">
        <CompareSide title="A · Original Skill" result={result?.original} liveScore={result?.score_original} files={result?.original_output_files} />
        <CompareSide title={`B · Peak Skill R${summary.best_round}`} result={result?.peak} liveScore={result?.score_peak} files={result?.peak_output_files} />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h3 className="panel-title">JSONL log</h3>
          <span className="badge">{logs.length} events</span>
        </div>
        <div className="compare-log">
          {logs.map((entry, idx) =>
            entry.kind === "log" ? (
              <div key={idx} className="log-line"><span>{entry.side}</span><span>{entry.tag}</span><code>{entry.line}</code></div>
            ) : (
              <details key={idx} className="log-json">
                <summary>{entry.side} · {entry.source}</summary>
                <pre>{JSON.stringify(entry.record, null, 2)}</pre>
              </details>
            )
          )}
        </div>
      </section>
    </div>
  );
}

function CompareSide({
  title,
  result,
  liveScore,
  files,
}: {
  title: string;
  result?: CompareSideResult;
  liveScore?: number;
  files?: string[];
}) {
  return (
    <article className="arena-side panel">
      <div className="panel-header">
        <h3 className="panel-title">{title}</h3>
        <span className="badge">{result ? `R${result.skill_md_round}` : "waiting"}</span>
      </div>
      <div className="panel-body stack">
        <div className="grid-3">
          <div className="stat"><div className="stat-label">Hybrid</div><div className="stat-value">{fmtScore(result?.hybrid_score ?? liveScore)}</div></div>
          <div className="stat"><div className="stat-label">Rule</div><div className="stat-value">{fmtScore(result?.rule_score)}</div></div>
          <div className="stat"><div className="stat-label">Judge</div><div className="stat-value">{fmtScore(result?.llm_judge_score)}</div></div>
        </div>
        {result?.judge_rationale && <p className="muted">{result.judge_rationale}</p>}
        {result?.rule_checks && (
          <div className="rule-list">
            {result.rule_checks.slice(0, 8).map((c) => (
              <div key={c.name} className="rule-row">
                <span className={c.passed ? "dot dot-ok" : "dot dot-bad"} />
                <span>{c.name}</span>
                <span>{fmtScore(c.score)}</span>
              </div>
            ))}
          </div>
        )}
        {result?.output && <code className="output-path">{result.output}</code>}
        {files && files.length > 0 && (
          <div className="stack-sm">
            {files.map((f) => <code key={f} className="output-path">{f}</code>)}
          </div>
        )}
      </div>
    </article>
  );
}
