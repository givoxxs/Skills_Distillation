import type { CompareResult } from "@/lib/types";
import { scoreDeltaLabel } from "./compare-ui-state";

function fmt(v: number | null | undefined): string {
  return typeof v === "number" ? v.toFixed(3) : "n/a";
}

export function JudgeVerdict({ result }: { result: CompareResult | null }) {
  if (!result) return null;
  const label = result.winner === "peak" ? "Peak wins"
    : result.winner === "original" ? "Original wins" : "Tie";
  // Replay carries side payloads; live carries score_original/score_peak.
  const so = result.score_original ?? result.original?.hybrid_score;
  const sp = result.score_peak ?? result.peak?.hybrid_score;
  return (
    <section className={`judge-verdict panel verdict-${result.winner}`}>
      <div className="verdict-head">
        <div>
          <div className="eyebrow">Judge verdict</div>
          <h3 className="verdict-title">{scoreDeltaLabel(result)}</h3>
        </div>
        <span className="badge badge-success">{label}</span>
      </div>
      <div className="panel-body stack-sm">
        <div className="verdict-metrics">
          <span>A original <b>{fmt(so)}</b></span>
          <span>B peak <b>{fmt(sp)}</b></span>
          {result.judge_model && <span>judge <b>{result.judge_model}</b></span>}
          {typeof result.elapsed_s === "number" && <span>elapsed <b>{result.elapsed_s}s</b></span>}
        </div>
        {(result.rationale || result.peak?.judge_rationale) && (
          <p className="muted">{result.rationale || result.peak?.judge_rationale}</p>
        )}
      </div>
    </section>
  );
}
