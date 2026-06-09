"use client";

import { useEffect, useRef } from "react";
import { Icon } from "@/components/icon";
import type { CompareResult, CompareSideState } from "@/lib/types";
import { ArtifactView } from "./artifact-view";
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
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state.steps.length]);

  const side = result?.[whichSide];
  const liveScore = whichSide === "original" ? result?.score_original : result?.score_peak;

  return (
    <article className="arena-side panel">
      <div className="panel-header">
        <h3 className="panel-title">{title}</h3>
        <span className="badge">{state.status}</span>
      </div>
      <div className="panel-body stack-sm">
        <div className="grid-3">
          <div className="stat"><div className="stat-label">Hybrid</div><div className="stat-value">{fmt(side?.hybrid_score ?? liveScore)}</div></div>
          <div className="stat"><div className="stat-label">Rule</div><div className="stat-value">{fmt(side?.rule_score)}</div></div>
          <div className="stat"><div className="stat-label">Judge</div><div className="stat-value">{fmt(side?.llm_judge_score)}</div></div>
        </div>

        {mode === "live" && (
          <div ref={ref} className="step-timeline">
            {state.steps.length === 0 && (
              <div className="arena-empty">
                <Icon name="play" size={16} />
                <span>{emptyCopy(mode, state.status)}</span>
              </div>
            )}
            {state.steps.map((s, i) => <StepCard key={i} step={s} />)}
          </div>
        )}

        {mode === "replay" && state.artifacts.length === 0 && !side?.rule_checks && (
          <div className="arena-empty">
            <Icon name="doc" size={16} />
            <span>{emptyCopy(mode, state.status)}</span>
          </div>
        )}

        {state.artifacts.length > 0 && <ArtifactView artifacts={state.artifacts} />}

        {state.outputDir && (
          <code className="output-path" title="Saved run folder (logs/ + outputs/)">
            {state.outputDir}
          </code>
        )}

        {side?.rule_checks && (
          <div className="rule-list">
            {side.rule_checks.slice(0, 8).map((c) => (
              <div key={c.name} className="rule-row">
                <span className={c.passed ? "dot dot-ok" : "dot dot-bad"} />
                <span>{c.name}</span>
                <span>{fmt(c.score)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
