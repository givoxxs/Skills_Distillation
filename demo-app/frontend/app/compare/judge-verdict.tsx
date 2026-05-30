import type { CompareResult } from "@/lib/types";

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
    <section className="judge-verdict panel">
      <div className="panel-header">
        <h3 className="panel-title">Judge verdict</h3>
        <span className="badge badge-success">{label}</span>
      </div>
      <div className="panel-body stack-sm">
        <div className="row" style={{ gap: 16 }}>
          <span>A · original: <b>{fmt(so)}</b></span>
          <span>B · peak: <b>{fmt(sp)}</b></span>
          {result.judge_model && <span className="muted">judge {result.judge_model}</span>}
          {typeof result.elapsed_s === "number" && <span className="muted">{result.elapsed_s}s</span>}
        </div>
        {(result.rationale || result.peak?.judge_rationale) && (
          <p className="muted">{result.rationale || result.peak?.judge_rationale}</p>
        )}
      </div>
    </section>
  );
}
