// Mirrors the backend Pydantic/dataclass shapes. Kept in one file so a backend change
// that breaks the contract shows up as a type error here.

export type Verdict = "meets_standard" | "does_not_meet_standard" | "cannot_assess";
export type Confidence = "high" | "medium" | "low";
export type Basis = "observed" | "estimated";

export interface Measurement {
  measure_id: string;
  value: number | null;
  unit: string;
  basis: Basis;
  frame: number | null;
  t: number | null;
  available: boolean;
  confidence: Confidence;
  reason: string | null;
  detail: Record<string, unknown> | null;
}

export interface Finding {
  rep_index: number;
  criterion_id: string;
  criterion_name: string;
  verdict: Verdict;
  measurement: Measurement | null;
  threshold_value: number | null;
  threshold_provenance: string | null;
  confidence: Confidence;
  explanation: string;
  feedback: string | null;
  uncertainty: string | null;
  citation: string;
  source_pages: number[];
  quote: string | null;
  timestamp_s: number | null;
  frame_index: number | null;
  narrated_by: "rules" | "agent";
}

export interface Rep {
  index: number;
  start_frame: number;
  bottom_frame: number;
  end_frame: number;
  start_t: number;
  bottom_t: number;
  end_t: number;
  confidence: Confidence;
}

export interface Gate {
  id: string;
  passed: boolean;
  severity: "ok" | "degraded" | "blocking";
  detail: string;
  value: number | null;
}

export interface CoverageRow {
  id: string;
  name: string;
  assessable: "full" | "partial" | "none";
  citation: string;
  reason: string | null;
  needed: string | null;
}

export interface Report {
  video: {
    filename: string;
    width: number;
    height: number;
    fps: number;
    duration_s: number;
    frame_count: number;
    codec: string;
  };
  skill: { version: string; document: string; source: string };
  pose: {
    side: string;
    side_confidence: number;
    shin_length_px: number;
    detection_fraction: number;
  };
  bar: { observed_fraction: number; median_radius_px: number | null; note: string | null };
  scale: {
    mm_per_px: number;
    basis: string;
    assumption: string;
    confidence: string;
  } | null;
  quality: {
    gates: Gate[];
    view_ratio: number;
    detection_fraction: number;
    is_assessable: boolean;
    blocking_reasons: string[];
  };
  reps: Rep[];
  rep_note: string | null;
  coverage: CoverageRow[];
  findings: Finding[];
  summary: string | null;
  blocked: boolean;
  agent_note: string | null;
  cost: Record<string, unknown> | null;
}

export interface Joint {
  x: number | null;
  y: number | null;
  v: number;
  visible: boolean;
}

export interface FrameAngles {
  back: number | null;      // torso to horizontal, degrees
  knee: number | null;      // femur-tibia interior angle, degrees
  hip: number | null;       // torso-femur interior angle, degrees
  bar_dev: number | null;   // signed bar offset from midfoot, shin-lengths
  midfoot_x: number | null; // pixels
}

export interface Target {
  reference: number | null;
  tolerance: number | null;
  tolerance_provenance: string | null;
  unit: string | null;
  citation: string;
}

export interface OverlayFrame {
  frame: number;
  t: number;
  joints: Record<string, Joint>;
  angles: FrameAngles;
  bar: { x: number | null; y: number | null; observed: boolean };
}

export interface Overlay {
  width: number;
  height: number;
  fps: number;
  duration_s: number;
  side: string;
  shin_length_px: number | null;
  skeleton: [string, string][];
  frames: OverlayFrame[];
  bar_path: { t: number; x: number | null; y: number | null; observed: boolean }[];
  reps: Rep[];
  targets: { back?: Target; bar_dev?: Target };
  target_poses: Record<string, TargetPose>;
}

export interface Correction {
  criterion_id: string;
  label: string;
  detail: string;
  provenance: string;
}

export interface TargetPose {
  frame: number;
  t: number;
  ankle: [number, number];
  knee: [number, number];
  hip: [number, number];
  shoulder: [number, number];
  bar: [number, number] | null;
  corrections: Correction[];
  solved: boolean;
  note: string | null;
}

export interface JobStatus {
  job_id: string;
  filename: string;
  status: "queued" | "processing" | "done" | "failed";
  stage: string;
  progress: number;
  error: string | null;
}

export interface Requirements {
  formats: string[];
  max_duration_s: number;
  max_upload_mb: number;
  min_fps: number;
  min_short_side_px: number;
  recording: string[];
  coverage: CoverageRow[];
}
