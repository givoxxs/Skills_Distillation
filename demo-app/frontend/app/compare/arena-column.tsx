"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import type { CompareResult, CompareSideState } from "@/lib/types";
import { ArtifactView } from "./artifact-view";
import { compareSidePhaseSteps } from "./compare-ui-state";
import { StepCard } from "./step-card";

function fmt(v: number | null | undefined): string {
  return typeof v === "number" ? v.toFixed(3) : "n/a";
}

function emptyCopy(mode: "replay" | "live", status: CompareSideState["status"]): string {
  if (status === "error") return "This side failed. Check the stream error above.";
  if (status === "done") return "No viewable artifact was emitted for this side.";
  if (mode === "replay") return "Ready to load stored artifacts and saved scores.";
  return "Run live arena to stream tool calls and generated outputs.";
}

type ArenaTab = "preview" | "steps" | "scores" | "files";

function tabLabel(tab: ArenaTab, state: CompareSideState, ruleCount: number): string {
  if (tab === "preview") return `Preview ${state.artifacts.length}`;
  if (tab === "steps") return `Steps ${state.steps.length}`;
  if (tab === "scores") return `Scores ${ruleCount}`;
  return "Files";
}

export function ArenaColumn({
  title,
  mode,
  state,
  result,
  whichSide,
}: {
  title: string;
  mode: "replay" | "live";
  state: CompareSideState;
  result: CompareResult | null;
  whichSide: "original" | "peak";
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [activeTab, setActiveTab] = useState<ArenaTab>("preview");
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state.steps.length]);

  const side = result?.[whichSide];
  const liveScore = whichSide === "original" ? result?.score_original : result?.score_peak;
  const ruleChecks = side?.rule_checks || [];
  const phaseSteps = compareSidePhaseSteps({
    status: state.status,
    artifactCount: state.artifacts.length,
    hasScores: Boolean(side || typeof liveScore === "number"),
  });

  return (
    <article className={`arena-side panel arena-side-${whichSide}`}>
      <div className="arena-side-head">
        <div>
          <div className="arena-side-kicker">{whichSide === "original" ? "A side" : "B side"}</div>
          <h3 className="panel-title">{title}</h3>
        </div>
        <div className="arena-side-status">
          <span className={`badge arena-status-${state.status}`}>{state.status}</span>
          <span className="badge">{state.artifacts.length} artifacts</span>
        </div>
      </div>

      <div className="side-phase-strip" aria-label={`${title} progress`}>
        {phaseSteps.map((step) => (
          <div key={step.key} className={`side-phase side-phase-${step.state}`}>
            <span className="phase-dot" />
            <span>{step.label}</span>
          </div>
        ))}
      </div>

      <div className="arena-score-strip">
        <div className="stat"><div className="stat-label">Hybrid</div><div className="stat-value">{fmt(side?.hybrid_score ?? liveScore)}</div></div>
        <div className="stat"><div className="stat-label">Rule</div><div className="stat-value">{fmt(side?.rule_score)}</div></div>
        <div className="stat"><div className="stat-label">Judge</div><div className="stat-value">{fmt(side?.llm_judge_score)}</div></div>
      </div>

      <div className="arena-tabs" role="tablist" aria-label={`${title} views`}>
        {(["preview", "steps", "scores", "files"] as ArenaTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            className={activeTab === tab ? "active" : ""}
            onClick={() => setActiveTab(tab)}
          >
            {tabLabel(tab, state, ruleChecks.length)}
          </button>
        ))}
      </div>

      <div className="panel-body arena-tab-panel">
        {activeTab === "preview" && (
          <div className="stack-sm">
            {state.artifacts.length > 0 ? (
              <ArtifactView artifacts={state.artifacts} />
            ) : (
              <div className="arena-empty">
                <Icon name="doc" size={16} />
                <span>{emptyCopy(mode, state.status)}</span>
              </div>
            )}
          </div>
        )}

        {activeTab === "steps" && (
          <div ref={ref} className="step-timeline">
            {state.steps.length === 0 && (
              <div className="arena-empty">
                <Icon name="play" size={16} />
                <span>{mode === "replay" ? "Replay mode loads stored outputs without live tool steps." : emptyCopy(mode, state.status)}</span>
              </div>
            )}
            {state.steps.map((s, i) => <StepCard key={i} step={s} />)}
          </div>
        )}

        {activeTab === "scores" && (
          <div className="stack-sm">
            {ruleChecks.length > 0 ? (
              <div className="rule-list">
                {ruleChecks.map((c) => (
                  <div key={c.name} className="rule-row">
                    <span className={c.passed ? "dot dot-ok" : "dot dot-bad"} />
                    <span>{c.name}</span>
                    <span>{fmt(c.score)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="arena-empty">
                <Icon name="table" size={16} />
                <span>Scores will appear after judge output is available.</span>
              </div>
            )}
          </div>
        )}

        {activeTab === "files" && (
          <div className="file-list">
            {state.outputDir && (
              <code className="output-path" title="Saved run folder (logs/ + outputs/)">
                {state.outputDir}
              </code>
            )}
            {state.artifacts.map((artifact) => (
              <div key={`${artifact.kind}-${artifact.label}`} className="file-row">
                <Icon name={artifact.kind === "docx" || artifact.kind === "pdf" ? "doc" : "external"} size={15} />
                <span>
                  <span className="mono">{artifact.kind}</span> · {artifact.label}
                </span>
              </div>
            ))}
            {!state.outputDir && state.artifacts.length === 0 && (
              <div className="arena-empty">
                <Icon name="doc" size={16} />
                <span>No file path has been emitted yet.</span>
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
