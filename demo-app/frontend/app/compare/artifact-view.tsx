import { compareArtifactUrl } from "@/lib/api";
import type { CompareArtifact } from "@/lib/types";

export function ArtifactView({ artifacts }: { artifacts: CompareArtifact[] }) {
  const pdf = artifacts.find((a) => a.kind === "pdf");
  const docx = artifacts.find((a) => a.kind === "docx");
  const texts = artifacts.filter((a) => a.kind === "text");
  const png = artifacts.find((a) => a.kind === "png");

  return (
    <div className="artifact-view stack-sm">
      {pdf?.url && (
        <iframe className="artifact-pdf" src={compareArtifactUrl(pdf.url)} title={`Document ${pdf.label}`} />
      )}
      {!pdf && png?.url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="artifact-img" src={compareArtifactUrl(png.url)} alt={png.label} />
      )}
      {docx?.url && (
        <a className="btn btn-sm" href={compareArtifactUrl(docx.url)} download>
          Tải {docx.label}
        </a>
      )}
      {texts.map((t, i) => (
        <details key={i} className="artifact-text" open={i === 0}>
          <summary>{t.label}</summary>
          <pre>{t.text}</pre>
        </details>
      ))}
      {artifacts.length === 0 && <div className="muted">No output produced.</div>}
    </div>
  );
}
