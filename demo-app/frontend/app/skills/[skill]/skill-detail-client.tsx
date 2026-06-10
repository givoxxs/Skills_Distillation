"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Bi } from "@/components/bi";
import { Icon } from "@/components/icon";
import { LearningCurve } from "@/components/charts/learning-curve";
import { CostStackedBar } from "@/components/charts/cost-stacked-bar";
import { DiffViewer } from "@/components/diff-viewer";
import type { ApiCall, EvalEntry, SkillSummary } from "@/lib/types";
import {
  buildSkillDetailQuery,
  type SkillDetailQueryState,
  type SkillDetailSortKey,
} from "./skill-detail-ui-state";

function statusBadge(score: number) {
  if (score >= 0.85)
    return (
      <span className="badge badge-success">
        <span className="dot" /> pass
      </span>
    );
  if (score >= 0.65)
    return (
      <span className="badge badge-accent">
        <span className="dot" /> partial
      </span>
    );
  return (
    <span className="badge badge-danger">
      <span className="dot" /> fail
    </span>
  );
}

function Stat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div className="stack-sm" style={{ gap: 4 }}>
      <span className="stat-label">{label}</span>
      <span
        className="mono tnum"
        style={{ fontSize: 20, fontWeight: 600, color: accent ? "var(--accent)" : "var(--fg)" }}
      >
        {value}
        {sub && (
          <span className="faint" style={{ fontSize: 12, fontWeight: 400, marginLeft: 6 }}>
            {sub}
          </span>
        )}
      </span>
    </div>
  );
}

export function SkillDetailClient({
  summary,
  workflows,
  evalByRound,
  apiCalls,
  skillMdByRound,
  bilingual,
  initialState,
}: {
  summary: SkillSummary;
  workflows: string[];
  evalByRound: Record<number, EvalEntry[]>;
  apiCalls: ApiCall[];
  skillMdByRound: Record<number, string>;
  bilingual: boolean;
  initialState: SkillDetailQueryState;
}) {
  const r1 = summary.score_history[0].avg_score;
  const improvement = ((summary.best_score - r1) / r1) * 100;

  const [fromRound, setFromRound] = useState(initialState.fromRound);
  const [toRound, setToRound] = useState(initialState.toRound);
  const leftMd = skillMdByRound[fromRound] || "";
  const rightMd = skillMdByRound[toRound] || "";

  const [evalRound, setEvalRound] = useState(initialState.evalRound);
  const [sortKey, setSortKey] = useState<{ key: SkillDetailSortKey; dir: "asc" | "desc" }>({
    key: initialState.sortKey,
    dir: initialState.sortDir,
  });
  const [activeTc, setActiveTc] = useState<EvalEntry | null>(() => {
    if (!initialState.testCaseId) return null;
    return (evalByRound[initialState.evalRound] || []).find((row) => row.test_case_id === initialState.testCaseId) || null;
  });
  // Dedupe by test_case_id — defensive in case upstream JSONL ever ships
  // multiple records per (round, test_case_id) (e.g. ensemble runs).
  const rows = useMemo(() => {
    const seen = new Map<string, EvalEntry>();
    for (const r of evalByRound[evalRound] || []) {
      const prev = seen.get(r.test_case_id);
      // Keep the highest hybrid_score across duplicates.
      if (!prev || r.hybrid_score > prev.hybrid_score) {
        seen.set(r.test_case_id, r);
      }
    }
    return [...seen.values()];
  }, [evalByRound, evalRound]);

  const sortedRows = useMemo(() => {
    const a = [...rows];
    a.sort((x, y) => {
      const xv: number | string | null =
        x[sortKey.key] === null ? -Infinity : (x[sortKey.key] as number | string);
      const yv: number | string | null =
        y[sortKey.key] === null ? -Infinity : (y[sortKey.key] as number | string);
      if (typeof xv === "string" && typeof yv === "string") {
        return sortKey.dir === "asc" ? xv.localeCompare(yv) : yv.localeCompare(xv);
      }
      const xn = typeof xv === "number" ? xv : Number.NEGATIVE_INFINITY;
      const yn = typeof yv === "number" ? yv : Number.NEGATIVE_INFINITY;
      return sortKey.dir === "asc" ? xn - yn : yn - xn;
    });
    return a;
  }, [rows, sortKey]);

  function setSort(key: SkillDetailSortKey) {
    setSortKey((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "desc" }
    );
  }

  const [wfFilter, setWfFilter] = useState<string>(initialState.workflow);
  const visibleRows = wfFilter === "all" ? sortedRows : sortedRows.filter((r) => r.workflow === wfFilter);

  const totalCost = apiCalls.reduce((a, c) => a + c.cost_usd, 0);
  const totalWallClockMin = Math.round(apiCalls.reduce((a, c) => a + c.latency_ms, 0) / 1000 / 60);

  const curveRef = useRef<HTMLDivElement | null>(null);
  const costRef = useRef<HTMLDivElement | null>(null);

  function exportPanelPng(ref: React.RefObject<HTMLDivElement | null>, filename: string) {
    const node = ref.current;
    if (!node) return;
    const svg = node.querySelector("svg");
    if (!svg) return;
    const xml = new XMLSerializer().serializeToString(svg);
    const svg64 = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      const scale = 2;
      c.width = (svg as SVGSVGElement).clientWidth * scale;
      c.height = (svg as SVGSVGElement).clientHeight * scale;
      const ctx = c.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle =
        getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() || "#fff";
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      const a = document.createElement("a");
      a.href = c.toDataURL("image/png");
      a.download = filename;
      a.click();
    };
    img.src = svg64;
  }

  useEffect(() => {
    if (typeof window === "undefined") return;
    const nextSearch = buildSkillDetailQuery({
      fromRound,
      toRound,
      evalRound,
      workflow: wfFilter,
      sortKey: sortKey.key,
      sortDir: sortKey.dir,
      testCaseId: activeTc?.test_case_id,
    });
    if (window.location.search !== nextSearch) {
      window.history.replaceState(null, "", `${window.location.pathname}${nextSearch}`);
    }
  }, [activeTc?.test_case_id, evalRound, fromRound, sortKey.dir, sortKey.key, toRound, wfFilter]);

  return (
    <div className="page stack-lg">
      <div className="stack-sm">
        <div className="eyebrow">
          <Bi vi="Chi tiết skill" en={bilingual ? "Skill detail" : null} showEn={bilingual} /> ·{" "}
          <span className="mono" style={{ textTransform: "none", letterSpacing: 0 }}>
            {summary.skill}
          </span>
        </div>
        <h1 className="h1">
          <Bi vi={summary.vi} en={summary.en || summary.vi} />
        </h1>
        <div className="row" style={{ gap: 24, marginTop: 8, flexWrap: "wrap" }}>
          <Stat label="Rounds run" value={summary.rounds_run} />
          <Stat label="R1" value={summary.score_history[0].avg_score.toFixed(3)} />
          <Stat label="Peak" value={summary.best_score.toFixed(3)} sub={`R${summary.best_round}`} accent />
          <Stat label="Final" value={summary.final_score.toFixed(3)} sub={`R${summary.rounds_run}`} />
          <Stat label="Δ R1 → Peak" value={`+${improvement.toFixed(1)}%`} accent />
        </div>
      </div>

      <div className="grid-2" style={{ alignItems: "stretch" }}>
        {/* Panel 1 — Learning curve */}
        <div className="panel" style={{ gridColumn: "1 / -1" }}>
          <div className="panel-header">
            <div>
              <h3 className="panel-title">
                <Bi vi="Đường học" en={bilingual ? "Learning curve" : null} showEn={bilingual} />
              </h3>
              <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>
                <Bi
                  vi="Avg hybrid score qua các round, peak được đánh dấu vàng."
                  en="Average hybrid score per round, peak highlighted in amber."
                />
              </div>
            </div>
            <div className="row">
              <span className="badge">
                <span className="mono">y ∈ [0.6, 1.0]</span>
              </span>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => exportPanelPng(curveRef, `${summary.skill}-curve.png`)}
              >
                <Icon name="download" size={14} /> PNG
              </button>
            </div>
          </div>
          <div className="panel-body" ref={curveRef}>
            <LearningCurve
              data={summary.score_history}
              peakRound={summary.best_round}
              variant="smooth"
              height={320}
              showThreshold={true}
            />
          </div>
          <div className="panel-footer">
            <span>
              Teacher rewrites kicked in after round 1 dropped under the rubric ceiling. Peak{" "}
              {summary.best_score.toFixed(3)} hit at R{summary.best_round}; subsequent rounds show
              mild regression — likely rubric overfit.
            </span>
          </div>
        </div>

        {/* Panel 2 — Diff (full-width row) */}
        <div className="panel" style={{ gridColumn: "1 / -1" }}>
          <div className="panel-header">
            <div>
              <h3 className="panel-title">
                <Bi vi="Diff SKILL.md" en={bilingual ? "SKILL.md diff" : null} showEn={bilingual} />
              </h3>
              <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>
                <Bi
                  vi="So sánh hai phiên bản của tài liệu hướng dẫn."
                  en="Compare two versions of the SKILL.md document."
                />
              </div>
            </div>
            <div className="row">
              <label className="row" style={{ gap: 6, fontSize: 12, color: "var(--fg-subtle)" }}>
                From
                <select
                  className="select"
                  value={fromRound}
                  onChange={(e) => setFromRound(+e.target.value)}
                >
                  {Array.from({ length: summary.rounds_run + 1 }, (_, i) => i).map((r) => (
                    <option key={r} value={r}>
                      R{r}
                      {r === 0 ? " · original" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="row" style={{ gap: 6, fontSize: 12, color: "var(--fg-subtle)" }}>
                To
                <select
                  className="select"
                  value={toRound}
                  onChange={(e) => setToRound(+e.target.value)}
                >
                  {Array.from({ length: summary.rounds_run + 1 }, (_, i) => i).map((r) => (
                    <option key={r} value={r}>
                      R{r}
                      {r === summary.best_round ? " · peak" : ""}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <div className="panel-body">
            <DiffViewer
              leftLabel={`SKILL_round_${fromRound}.md`}
              rightLabel={`SKILL_round_${toRound}.md`}
              left={leftMd}
              right={rightMd}
            />
          </div>
        </div>

        {/* Panel 3 — Test case explorer */}
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3 className="panel-title">
                <Bi vi="Bảng test case" en={bilingual ? "Test cases" : null} showEn={bilingual} />
              </h3>
              <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>
                <Bi
                  vi="Click một dòng để xem prompt · output_dir · rationale."
                  en="Click a row to view prompt · output_dir · rationale."
                />
              </div>
            </div>
            <div className="row">
              <label className="row" style={{ gap: 6, fontSize: 12, color: "var(--fg-subtle)" }}>
                Round
                <select
                  className="select"
                  value={evalRound}
                  onChange={(e) => setEvalRound(+e.target.value)}
                >
                  {summary.score_history.map((h) => (
                    <option key={h.round} value={h.round}>
                      R{h.round} · {h.avg_score.toFixed(3)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <div style={{ padding: "12px 24px 0", display: "flex", flexWrap: "wrap", gap: 6 }}>
            <button
              type="button"
              className={"badge " + (wfFilter === "all" ? "badge-primary" : "")}
              onClick={() => setWfFilter("all")}
            >
              all
            </button>
            {workflows.map((wf) => (
              <button
                key={wf}
                type="button"
                className={"badge " + (wfFilter === wf ? "badge-primary" : "")}
                onClick={() => setWfFilter(wf)}
              >
                <span className="mono" style={{ fontSize: 11 }}>
                  {wf}
                </span>
              </button>
            ))}
          </div>
          <div
            className="panel-body-flush table-wrap"
            style={{ maxHeight: 360, overflow: "auto", padding: "12px 0 0" }}
          >
            <table className="table">
              <thead>
                <tr>
                  <th onClick={() => setSort("test_case_id")} style={{ cursor: "pointer" }}>
                    id
                  </th>
                  <th onClick={() => setSort("workflow")} style={{ cursor: "pointer" }}>
                    workflow
                  </th>
                  <th
                    onClick={() => setSort("rule_score")}
                    style={{ cursor: "pointer", textAlign: "right" }}
                  >
                    rule
                  </th>
                  <th
                    onClick={() => setSort("llm_judge_score")}
                    style={{ cursor: "pointer", textAlign: "right" }}
                  >
                    judge
                  </th>
                  <th
                    onClick={() => setSort("hybrid_score")}
                    style={{ cursor: "pointer", textAlign: "right" }}
                  >
                    hybrid
                  </th>
                  <th>status</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr
                    key={`${row.round}-${row.test_case_id}`}
                    onClick={() => setActiveTc(row)}
                    className={activeTc && activeTc.test_case_id === row.test_case_id ? "active" : ""}
                  >
                    <td className="id">{row.test_case_id}</td>
                    <td>
                      <span className="mono" style={{ fontSize: 12, color: "var(--fg-muted)" }}>
                        {row.workflow}
                      </span>
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {row.rule_score.toFixed(3)}
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {row.llm_judge_score === null ? (
                        <span className="faint">—</span>
                      ) : (
                        row.llm_judge_score.toFixed(3)
                      )}
                    </td>
                    <td
                      className="num"
                      style={{ textAlign: "right", color: "var(--fg)", fontWeight: 600 }}
                    >
                      {row.hybrid_score.toFixed(3)}
                    </td>
                    <td>{statusBadge(row.hybrid_score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="panel-footer">
            <span>
              {visibleRows.length} / {rows.length} test cases — round {evalRound}
            </span>
            <span>
              Sorted by {sortKey.key} {sortKey.dir === "desc" ? "↓" : "↑"}
            </span>
          </div>
        </div>

        {/* Panel 4 — Cost */}
        <div className="panel" style={{ gridColumn: "1 / -1" }}>
          <div className="panel-header">
            <div>
              <h3 className="panel-title" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                <Bi vi="Chi phí & thời gian" en={bilingual ? "Cost & timing" : null} showEn={bilingual} />
                <span
                  className="badge badge-accent"
                  title="distillation_v2 chưa sinh api_calls.jsonl — chi phí bên dưới là ước lượng từ pricing OpenRouter/Anthropic."
                >
                  demo data
                </span>
              </h3>
              <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>
                <Bi
                  vi="Phân bổ chi phí theo round, stack theo stage."
                  en="Cost breakdown per round, stacked by pipeline stage."
                />
              </div>
            </div>
            <div className="row">
              <span className="badge">
                <Icon name="coins" size={12} />
                Total{" "}
                <span className="mono tnum" style={{ marginLeft: 4 }}>
                  ${totalCost.toFixed(2)}
                </span>
              </span>
              <span className="badge">
                <span className="mono tnum">{totalWallClockMin} min</span> wall-clock
              </span>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => exportPanelPng(costRef, `${summary.skill}-cost.png`)}
              >
                <Icon name="download" size={14} /> PNG
              </button>
            </div>
          </div>
          <div className="panel-body" ref={costRef}>
            <CostStackedBar apiCalls={apiCalls} height={280} />
          </div>
        </div>
      </div>

      {/* Drawer */}
      <div
        className={"drawer-backdrop " + (activeTc ? "open" : "")}
        onClick={() => setActiveTc(null)}
      />
      <aside className={"drawer " + (activeTc ? "open" : "")} aria-hidden={!activeTc}>
        {activeTc && (
          <>
            <div className="drawer-header">
              <div className="stack-sm">
                <div className="row" style={{ gap: 8 }}>
                  <span className="id mono" style={{ color: "var(--fg-muted)" }}>
                    {activeTc.test_case_id}
                  </span>
                  <span className="badge">
                    <span className="mono">{activeTc.workflow}</span>
                  </span>
                  {statusBadge(activeTc.hybrid_score)}
                </div>
                <h3 className="panel-title">
                  <Bi vi="Chi tiết test case" en="Test case detail" />
                </h3>
              </div>
              <button
                type="button"
                className="btn btn-icon"
                onClick={() => setActiveTc(null)}
                aria-label="Close"
              >
                <Icon name="x" size={16} />
              </button>
            </div>
            <div className="drawer-body">
              <div className="drawer-section">
                <div className="drawer-section-title">
                  <Bi vi="Điểm số" en="Scores" />
                </div>
                <div className="row" style={{ gap: 24, fontVariantNumeric: "tabular-nums" }}>
                  <div className="stack-sm" style={{ gap: 2 }}>
                    <span className="stat-label">Rule</span>
                    <span className="mono">{activeTc.rule_score.toFixed(3)}</span>
                  </div>
                  <div className="stack-sm" style={{ gap: 2 }}>
                    <span className="stat-label">Judge</span>
                    <span className="mono">
                      {activeTc.llm_judge_score === null
                        ? "—"
                        : activeTc.llm_judge_score.toFixed(3)}
                    </span>
                  </div>
                  <div className="stack-sm" style={{ gap: 2 }}>
                    <span className="stat-label">Hybrid</span>
                    <span
                      className="mono"
                      style={{ fontWeight: 600, color: "var(--primary)" }}
                    >
                      {activeTc.hybrid_score.toFixed(3)}
                    </span>
                  </div>
                </div>
              </div>
              <div className="drawer-section">
                <div className="drawer-section-title">Prompt</div>
                <div className="code-block">{activeTc.prompt || "—"}</div>
              </div>
              <div className="drawer-section">
                <div className="drawer-section-title">Output (artifacts) · stored at</div>
                <div className="code-block" style={{ maxHeight: 80 }}>
                  {activeTc.output || "—"}
                </div>
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  <Bi
                    vi={
                      <>
                        Artifacts (output.docx, screenshots…) nằm tại đường dẫn trên trong{" "}
                        <span className="mono">distillation_v2/</span> — không inline để giữ payload nhẹ.
                      </>
                    }
                    en={
                      <>
                        Artifacts (output.docx, screenshots…) live at the path above inside{" "}
                        <span className="mono">distillation_v2/</span> — not inlined to keep payload small.
                      </>
                    }
                  />
                </div>
              </div>
              <div className="drawer-section">
                <div className="drawer-section-title">
                  <Bi vi="Judge rationale (lý do của Judge)" en="Judge rationale" />
                </div>
                <p
                  style={{
                    margin: 0,
                    fontSize: 14,
                    lineHeight: 1.6,
                    color: "var(--fg)",
                  }}
                >
                  {activeTc.judge_rationale}
                </p>
              </div>
              <div className="drawer-section">
                <div className="drawer-section-title">
                  <Bi vi="Rule checks (kiểm tra rule)" en="Rule checks" />
                </div>
                <ul
                  style={{
                    listStyle: "none",
                    padding: 0,
                    margin: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                  }}
                >
                  {activeTc.rule_checks.map((c, i) => (
                    <li
                      key={i}
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: 10,
                        fontSize: 13,
                        lineHeight: 1.5,
                      }}
                    >
                      <span style={{ flex: "none", marginTop: 2 }}>
                        {c.passed ? (
                          <Icon name="check" size={14} className="status-ok" />
                        ) : (
                          <Icon name="x" size={14} className="status-bad" />
                        )}
                      </span>
                      <div>
                        <div
                          className="mono"
                          style={{
                            fontSize: 12,
                            color: c.passed ? "var(--success)" : "var(--danger)",
                          }}
                        >
                          {c.name}
                        </div>
                        <div className="muted" style={{ fontSize: 13 }}>
                          {c.reason}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
