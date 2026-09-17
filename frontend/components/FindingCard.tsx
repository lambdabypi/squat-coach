"use client";

import { useState } from "react";
import type { Finding } from "@/lib/types";

const LABEL: Record<string, string> = {
  meets_standard: "meets standard",
  does_not_meet_standard: "does not meet",
  cannot_assess: "cannot assess",
};

function formatValue(f: Finding): string | null {
  const m = f.measurement;
  if (!m || m.value == null) return null;
  const unit = m.unit === "shin_lengths" ? "shin" : m.unit === "degrees" ? "°" : "";
  const v = m.unit === "degrees" ? m.value.toFixed(0) : m.value.toFixed(2);
  return `${v}${unit === "°" ? "" : " "}${unit}`;
}

export default function FindingCard({
  finding,
  onSeek,
}: {
  finding: Finding;
  onSeek: (t: number, frame: number | null) => void;
}) {
  const [showQuote, setShowQuote] = useState(false);
  const value = formatValue(finding);
  const m = finding.measurement;

  return (
    <div className={`finding ${finding.verdict}`}>
      <div className="top">
        <span className="name">{finding.criterion_name}</span>
        <span className={`verdict-badge v-${finding.verdict}`}>{LABEL[finding.verdict]}</span>
      </div>

      <p className="exp">{finding.explanation}</p>

      <div className="meta">
        {value && (
          <span className={`pill ${m?.basis === "estimated" ? "est" : "obs"}`}>
            {value} · {m?.basis === "estimated" ? "estimated" : "observed"}
          </span>
        )}

        {finding.threshold_value != null && (
          <span
            className={`pill ${finding.threshold_provenance === "document_stated" ? "doc" : "eng"}`}
            title={
              finding.threshold_provenance === "document_stated"
                ? "This value is stated in the reference document."
                : "This is our measurement tolerance, not a requirement from the document."
            }
          >
            ±{finding.threshold_value}{" "}
            {finding.threshold_provenance === "document_stated" ? "per document" : "our tolerance"}
          </span>
        )}

        {finding.timestamp_s != null && (
          <span
            className="pill time"
            onClick={() => onSeek(finding.timestamp_s!, finding.frame_index)}
          >
            ▸ {finding.timestamp_s.toFixed(2)}s
          </span>
        )}

        <span className="pill">{finding.confidence} confidence</span>

        <span
          className="pill"
          style={{ cursor: "pointer" }}
          onClick={() => setShowQuote((v) => !v)}
          title="Show the source text this criterion comes from"
        >
          {finding.citation}
        </span>
      </div>

      {showQuote && finding.quote && <p className="quote">&ldquo;{finding.quote}&rdquo;</p>}

      {finding.feedback && <div className="feedback">{finding.feedback}</div>}

      {finding.uncertainty && (
        <div className="uncertain">
          <strong>Uncertainty:</strong> {finding.uncertainty}
        </div>
      )}
    </div>
  );
}
