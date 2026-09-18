"use client";

import { useState } from "react";
import { presentMeasurement } from "@/lib/present";
import type { Finding, Report } from "@/lib/types";

const LABEL: Record<string, string> = {
  meets_standard: "meets standard",
  does_not_meet_standard: "does not meet",
  cannot_assess: "cannot assess",
};

export default function FindingCard({
  finding,
  report,
  onSeek,
}: {
  finding: Finding;
  report: Report;
  onSeek: (t: number | null, frame: number | null) => void;
}) {
  const [showQuote, setShowQuote] = useState(false);
  const presented = presentMeasurement(finding, report);
  const m = finding.measurement;

  return (
    <div className={`finding ${finding.verdict}`}>
      <div className="top">
        <span className="name">{finding.criterion_name}</span>
        <span className={`verdict-badge v-${finding.verdict}`}>{LABEL[finding.verdict]}</span>
      </div>

      <p className="exp">{finding.explanation}</p>

      <div className="meta">
        {presented && (
          <span
            className={`pill ${m?.basis === "estimated" ? "est" : "obs"}`}
            title={
              presented.secondary
                ? `${presented.secondary}${presented.scaled ? ", converted using the barbell plate as a scale reference" : ""}`
                : undefined
            }
          >
            {presented.primary}
            {presented.secondary && (
              <span className="pill-sub"> ({presented.secondary})</span>
            )}
          </span>
        )}
        {m?.basis === "estimated" && <span className="pill est">estimated</span>}

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
            onClick={() => onSeek(finding.timestamp_s, finding.frame_index)}
          >
            {finding.timestamp_s.toFixed(2)}s
          </span>
        )}

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
