import { compareArtifactUrl } from "@/lib/api";
import type { CompareArtifact } from "@/lib/types";

export function ArtifactView({ artifacts }: { artifacts: CompareArtifact[] }) {
  const pdf = artifacts.find((a) => a.kind === "pdf");
  const docxFiles = artifacts.filter((a) => a.kind === "docx");
  const images = artifacts.filter((a) => a.kind === "image" || a.kind === "png");
  const texts = artifacts.filter((a) => a.kind === "text");

  return (
    <div className="artifact-view stack-sm">
      {pdf?.url && (
        <iframe
          className="artifact-pdf"
          src={compareArtifactUrl(pdf.url)}
          title={`Document ${pdf.label}`}
        />
      )}

      {images.map((img) =>
        img.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={img.label}
            className="artifact-img"
            src={compareArtifactUrl(img.url)}
            alt={img.label}
          />
        ) : null
      )}

      {texts.map((t, i) => (
        <details key={t.label} className="artifact-text" open={i === 0}>
          <summary>{t.label}</summary>
          <pre>{t.text}</pre>
        </details>
      ))}

      {docxFiles.map((d) =>
        d.url ? (
          <a key={d.label} className="btn btn-sm" href={compareArtifactUrl(d.url)} download>
            Tải {d.label}
          </a>
        ) : null
      )}

      {artifacts.length === 0 && <div className="muted">No output produced.</div>}
    </div>
  );
}
