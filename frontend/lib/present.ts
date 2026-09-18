import type { Finding, Report } from "./types";

/**
 * Turning measurements into something a lifter reads.
 *
 * Two rules here:
 *   1. Lead with a real-world unit when we have a defensible scale, and keep the normalised
 *      figure alongside it. "0.27 shin" is an internal constant; "about 5 cm" is a distance.
 *   2. Never drop the provenance. A centimetre figure that depends on an assumed plate size
 *      has to say so somewhere, which is why `scaleNote` travels with it.
 */

export interface Presented {
  primary: string;
  secondary: string | null;
  scaled: boolean;
}

export function mmPerPx(report: Report): number | null {
  return report.scale?.mm_per_px ?? null;
}

/** Convert a shin-length distance into centimetres, if a scale exists. */
export function shinToCm(
  value: number,
  report: Report,
): number | null {
  const mm = mmPerPx(report);
  const shinPx = report.pose.shin_length_px;
  if (mm == null || !shinPx) return null;
  return (value * shinPx * mm) / 10;
}

export function presentMeasurement(f: Finding, report: Report): Presented | null {
  const m = f.measurement;
  if (!m || m.value == null) return null;

  if (m.unit === "degrees") {
    return { primary: `${m.value.toFixed(0)}°`, secondary: null, scaled: false };
  }
  if (m.unit === "ratio") {
    return { primary: m.value.toFixed(2), secondary: "ratio", scaled: false };
  }
  if (m.unit === "shin_lengths") {
    const cm = shinToCm(Math.abs(m.value), report);
    const shin = `${Math.abs(m.value).toFixed(2)} shin-lengths`;
    if (cm == null) return { primary: shin, secondary: null, scaled: false };
    const rounded = cm < 1 ? cm.toFixed(1) : Math.round(cm).toString();
    return { primary: `${rounded} cm`, secondary: shin, scaled: true };
  }
  return { primary: `${m.value}`, secondary: m.unit, scaled: false };
}

/** Plain-language headline for a repetition, built from its findings. */
export function headline(findings: Finding[]): string {
  const failed = findings.filter((f) => f.verdict === "does_not_meet_standard");
  const borderline = findings.filter(
    (f) => f.verdict === "cannot_assess" && f.measurement?.available,
  );
  const passed = findings.filter((f) => f.verdict === "meets_standard");

  if (failed.length === 0 && borderline.length === 0) {
    return "This repetition met every standard we could assess.";
  }
  if (failed.length === 0) {
    return `Nothing clearly went wrong, but ${borderline.length === 1 ? "one measurement was" : `${borderline.length} measurements were`} too close to call.`;
  }
  if (passed.length === 0) {
    return `${failed.length} thing${failed.length === 1 ? "" : "s"} to work on in this repetition.`;
  }
  return `${passed.length} thing${passed.length === 1 ? "" : "s"} going well, ${failed.length} to fix.`;
}

export interface Grouped {
  fix: Finding[];        // does not meet the standard
  good: Finding[];       // meets the standard
  borderline: Finding[]; // measured, inside tolerance
  unseen: Finding[];     // no measurement available at all
}

export function groupFindings(findings: Finding[]): Grouped {
  return {
    fix: findings.filter((f) => f.verdict === "does_not_meet_standard"),
    good: findings.filter((f) => f.verdict === "meets_standard"),
    borderline: findings.filter(
      (f) => f.verdict === "cannot_assess" && !!f.measurement?.available,
    ),
    unseen: findings.filter(
      (f) => f.verdict === "cannot_assess" && !f.measurement?.available,
    ),
  };
}
