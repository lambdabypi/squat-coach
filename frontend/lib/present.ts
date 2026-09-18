import type { CoverageRow, Finding, Report } from "./types";

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
  fix: Finding[];         // does not meet the standard
  good: Finding[];        // meets the standard
  borderline: Finding[];  // measured, inside tolerance
  notMeasured: Finding[]; // a side view could judge this, but not in this clip
  outOfScope: Finding[];  // no side view can ever judge this
}

/**
 * Split the unmeasured findings by *why*, which the flat count hid.
 *
 * On the common sample 13 of 22 verdicts are `cannot_assess`, and presented as one number that
 * reads like the product failing. Three of the document's criteria - knees-out, stance width, rack
 * height - are frontal or transverse plane measurements that NO side view can recover. They are a
 * property of the assignment's chosen camera, identical on every upload, and lumping them in with
 * "we could not measure this one" overstates how much this particular clip defeated us.
 *
 * `coverage[].assessable === "none"` is the skill's own declaration of that, so the split is
 * driven by the document-derived skill rather than a hardcoded list here.
 */
export function groupFindings(findings: Finding[], coverage: CoverageRow[] = []): Grouped {
  const structural = new Set(
    coverage.filter((c) => c.assessable === "none").map((c) => c.id),
  );
  const unseen = findings.filter(
    (f) => f.verdict === "cannot_assess" && !f.measurement?.available,
  );
  return {
    fix: findings.filter((f) => f.verdict === "does_not_meet_standard"),
    good: findings.filter((f) => f.verdict === "meets_standard"),
    borderline: findings.filter(
      (f) => f.verdict === "cannot_assess" && !!f.measurement?.available,
    ),
    notMeasured: unseen.filter((f) => !structural.has(f.criterion_id)),
    outOfScope: unseen.filter((f) => structural.has(f.criterion_id)),
  };
}

/**
 * One line of scope, so the reader knows the denominator before reading any verdict.
 *
 * Without it the report opens on a set of verdicts with no indication that some criteria were
 * never in play, which makes an honest abstention look like a gap in the product.
 */
export function scopeLine(coverage: CoverageRow[]): string | null {
  if (!coverage.length) return null;
  const outside = coverage.filter((c) => c.assessable === "none").length;
  const inside = coverage.length - outside;
  if (!outside) return null;
  return (
    `${inside} of the document's ${coverage.length} criteria can be judged from a side view. ` +
    `The other ${outside} need a different camera angle and are listed below rather than guessed at.`
  );
}
