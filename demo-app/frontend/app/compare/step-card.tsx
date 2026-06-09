import type { CompareStep } from "@/lib/types";

export function StepCard({ step }: { step: CompareStep }) {
  const it = step.iteration != null ? `#${step.iteration}` : "";
  if (step.kind === "tool_call") {
    return (
      <div className="step step-tool">
        <div className="step-head"><span className="step-kind">tool · {step.tool}</span><span className="step-it">{it}</span></div>
        {step.args?.description && <div className="step-desc">{step.args.description}</div>}
        {step.args?.command && <pre className="step-code">{step.args.command}</pre>}
      </div>
    );
  }
  if (step.kind === "tool_result") {
    return (
      <details className="step step-result">
        <summary><span className="step-kind">result · {step.tool}</span><span className="step-it">{it}</span></summary>
        <pre className="step-code">{step.result}</pre>
      </details>
    );
  }
  if (step.kind === "assistant_text") {
    return (
      <div className="step step-assistant">
        <div className="step-head"><span className="step-kind">assistant</span><span className="step-it">{it}</span></div>
        <div className="step-text">{step.text}</div>
      </div>
    );
  }
  if (step.kind === "end") {
    return (
      <div className="step step-end">
        <span className="step-kind">end · {step.stop_reason}</span>
        <span className="muted"> {step.duration_seconds}s · {step.tokens?.total ?? "?"} tok</span>
      </div>
    );
  }
  if (step.kind === "api_error") {
    return (
      <div className="step step-error">
        <div className="step-head"><span className="step-kind">api_error</span><span className="step-it">{it}</span></div>
        <pre className="step-code">{step.error || step.text || "No error detail was provided."}</pre>
      </div>
    );
  }
  if (step.kind === "start" || step.kind === "cli_init") {
    return <div className="step step-meta"><span className="step-kind">{step.kind}</span></div>;
  }
  return (
    <div className="step step-meta">
      <span className="step-kind">{step.kind}</span> <span className="muted">{step.text || step.result || ""}</span>
    </div>
  );
}
