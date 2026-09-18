# The squat assessment skill

This directory *is* the assessment standard. The application contains no squat knowledge of its
own - it measures geometry and hands the numbers to an agent that reasons against these rules.
Change a rule here and the assessment changes, with no application code touched.

| File | What it is |
|---|---|
| `squat_standards.yaml` | The machine-readable skill. The single source of truth. |
| `SKILL.md` | This file - the same rules in prose, readable in three minutes. |
| `coverage.md` | What a side view can and cannot judge. **Generated** from the YAML. |
| `CITATIONS.md` | Criterion → reference page index. **Generated** from the YAML. |

Source: *The Squat*, Starting Strength, reference pages 1-35 (combined PDF pages 4-38).
Reference page N = combined PDF page N+3.

---

## The one rule that matters most

**The reference document states almost no numbers.**

It defines depth geometrically ("hips dropping below level with the top of the patellas"), gives
"about 30 degrees" for toe angle, "about a 45-degree angle" for the back, "4 or 5 feet" for gaze
distance, and heels "about shoulder width". That is very nearly the complete list of figures in
thirty-five pages.

Everything else the document expresses as direction, geometry or anatomy. So every number this
system uses carries a `provenance` tag:

- **`document_stated`** - the document requires this. Citable to the user as a standard.
- **`engineering_tolerance`** - *our* margin, for landmark noise and measurement limits. It is
  never presented as something the document requires.

`loader.py` enforces this: a `tolerance` block that claims `document_stated` provenance raises at
load time. A tolerance is by definition a measurement margin, and the document states none, so such
an edit is always a mistake.

This is the difference between "your depth does not meet the standard on ref p.16" and "your hip
was 0.03 shin-lengths above the threshold" - the first is grounded, the second would be inventing a
requirement and attributing it to the book.

---

## Where the criteria come from

The document ends, on reference page 35, with its own checklist - *The Important Things You're
Going to Do Wrong*:

> **Depth · Knee position · Stance · Eye gaze · Back angle · Hip drive · Bar placement · Rack height**

Those eight headings are the backbone of this skill. The preceding thirty-four pages supply the
rationale and the citable language for each.

**Three of the eight cannot be assessed from the required input.** Knees-out and stance are
frontal-plane properties; a sagittal camera contains no information about them. Rack height is a
property of the setup, usually outside the frame. The system says so plainly rather than quietly
dropping them - and knees-out is the fault the document emphasises most, which makes staying silent
about it the worst option.

---

## The criteria in brief

### Fully assessable from a side view

**Depth** (ref p.2, 16, 18 · Fig 2-1, 2-10) - the hip landmark must drop below the top of the
patella at the bottom of the rep. Geometric, not numeric. *Known bias:* the document's landmark is
the hip **crease**; pose estimation gives a hip **joint centre**, which sits higher, biasing us
toward reporting "not deep enough". Stated on the finding, not absorbed into the tolerance.

**Back angle** (ref p.9, 11, 23, 32 · Fig 2-5, 2-13, 2-22) - angle of the torso to horizontal.
The document says "about a 45-degree angle, not at all vertical". *"About" is the document's own
word,* so this is a reference posture, not a pass/fail line. We flag only clear departures: too
vertical, or too horizontal.

**Bar path over the midfoot** (ref p.6, 8, 9, 11 · Fig 2-5, 2-7) - the bar should travel a
vertical line over the middle of the foot. The *requirement* is document-stated; the *size* of an
acceptable deviation is not, because the document ties allowable deviation to load, which video
cannot tell us.

**Hip drive** (ref p.23, 24 · Fig 2-14) - "driving your butt straight up in the air. Up, not
forward." Measured as hip rise versus shoulder rise over the first 150 ms of the ascent. Chest
first means the hips did not lead.

**Knee position, front-back only** (ref p.23 · Fig 2-13) - "the knees are just a little forward of
the toes". Note this is *only* the sagittal component; the document's actual knee fault is a
frontal-plane one and is listed as unassessable.

### Partially assessable - reduced confidence, and we say why

**Heels flat** (ref p.23) - heel landmarks are often occluded by the far leg and by footwear.
Capped at medium confidence.

**Bar placement** (ref p.13, 30, 31 · Fig 2-19) - the standard is anatomical, "right below the
spine of the scapula". There is no scapular-spine landmark, and correct versus incorrect is about
two centimetres on the athlete. We can spot a grossly high bar and nothing finer, so this never
returns a confident pass. Capped at low confidence.

**Eye gaze** (ref p.24, 25, 27) - gaze is not observable; head orientation is, via an ear→nose
pitch proxy. The head is also routinely hidden behind the plate in a side view - it is in the
common sample. Reports only a clearly upward-directed head; otherwise `cannot_assess`.

### Not assessable from a side view

**Knees out** (ref p.14, 22, 33) · **Stance width and toe angle** (ref p.14, 20, 21 · Fig 2-12) ·
**Rack height** (ref p.28, 31). Each records what camera angle *would* be needed. See `coverage.md`.

---

## Global gates

Checked before any criterion is evaluated. If one fails, criteria return `cannot_assess` with the
reason named rather than a guess:

- **Sagittal view** - is the camera actually side-on? Tested by how far the left and right shoulder
  and hip landmarks separate horizontally relative to torso length; a true side view collapses them.
  The document's own depth standard is defined on the profile view (Fig 2-1).
- **Landmark visibility** - required landmarks must clear a 0.6 visibility floor at the frame of
  interest, or that criterion names the occluded landmark and abstains.
- **Rep detected** - at least one bottom position must be found.
- **Framing** - feet and bar both in frame, for depth and bar-path.

---

## Editing this skill

1. Edit `squat_standards.yaml`.
2. Run `python -m app.skill.loader` from `backend/` - it validates and prints every criterion with
   its provenance. A malformed edit fails here, loudly.
3. Re-run the analysis. No application code changes.

Adding a criterion requires: an `id`, at least one `source.pages` entry, a verbatim `quote`, an
`assessable_from_side_view` value, and - unless it is `none` - a `measure` and a `rule`. Anything
assessable needs a measurement the vision layer actually produces; unmapped measure ids are
reported at load time.
