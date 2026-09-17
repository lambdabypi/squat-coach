# Coverage: what a side view can and cannot judge

<!-- GENERATED from squat_standards.yaml by scripts/gen_skill_docs.py. Do not edit. -->

Of **11 criteria** drawn from the reference document: **5 fully assessable** from a single side-view video, **3 partially assessable**, and **3 not assessable at all**.

The document's own closing checklist (ref p.35) names eight faults. Three of those eight are invisible to a sagittal camera. This page exists so that absence is stated rather than inferred from a missing row.

| Criterion | Side view | Source | Measured how / why not |
|---|---|---|---|
| Squat depth | **Yes** | ref p. 2, 16, 18, 22, 33 · Fig 2-1, 2-10 | Signed vertical offset of the hip landmark below the top of the patella at the bottom frame, normalised by shin length. Positive means the hip is lower than the knee. |
| Back angle | **Yes** | ref p. 9, 11, 23, 32, 35 · Fig 2-5, 2-13, 2-22 | Angle between the shoulder->hip vector and the horizontal, at the bottom frame. |
| Bar path over the midfoot | **Yes** | ref p. 6, 8, 9, 11, 12 · Fig 2-5, 2-7 | Maximum absolute horizontal distance between the tracked bar centre and the midfoot x across the repetition, normalised by shin length. |
| Hip drive out of the bottom | **Yes** | ref p. 1, 23, 24, 35 · Fig 2-14 | Ratio of hip vertical rise to shoulder vertical rise over the first 150 ms of the ascent. A value >= 1 means the hips led. Below 1 means the chest rose first. |
| Knee position at the bottom (sagittal) | **Yes** | ref p. 23 · Fig 2-13 | Horizontal offset of the knee ahead of the toe at the bottom, normalised by shin length. |
| Heels flat on the floor | Partial | ref p. 23 · Fig 2-13 | Heel landmarks are frequently occluded by the far leg and by footwear, and a few pixels of rise is within noise. Reported at reduced confidence, and `cannot_assess` when the foot is occluded. |
| Bar placement on the back | Partial | ref p. 13, 30, 31, 35 · Fig 2-19 | We can distinguish grossly high bar placement from plausible placement, and nothing finer. Never returns a confident "meets standard"; at best "consistent with low-bar placement". |
| Eye gaze direction | Partial | ref p. 24, 25, 27, 35 · Fig 2-15, 2-16 | Gaze is not observable; head orientation is. The head is also routinely occluded by the plate in a side view - it is in the common sample. Reports only a clear upward-directed head, otherwise `cannot_assess`. |
| Knees shoved out | **No** | ref p. 14, 22, 33, 35 | Knees-out is displacement in the frontal plane, perpendicular to the camera. A sagittal view contains no information about it. Requires a front or 45-degree camera. |
| Stance width and toe angle | **No** | ref p. 14, 20, 21, 32, 35 · Fig 2-12 | Stance width is a frontal-plane measurement and toe angle is a transverse-plane measurement. Neither is recoverable from a single sagittal view. The document's own illustration of the standard (Figure 2-12) is an overhead view. |
| Rack height and unracking procedure | **No** | ref p. 28, 31, 35 | A property of the setup before the set, not of a repetition. The rack and the unracking are typically outside the frame of an uploaded squat clip, and our analysis is rep-scoped. |

## What would be needed for the unassessable criteria

### Knees shoved out

*ref p. 14, 22, 33, 35*

> You will fail to shove your knees out as you start down. This will make correct depth hard to attain and will kill your hip drive.

**Why not:** Knees-out is displacement in the frontal plane, perpendicular to the camera. A sagittal view contains no information about it. Requires a front or 45-degree camera.

**Needed:** A front-facing or 45-degree camera angle.

**Note:** This is the document's single most-emphasised fault and we cannot see it. Worth telling the user directly rather than omitting the criterion.

### Stance width and toe angle

*ref p. 14, 20, 21, 32, 35 · Fig 2-12*

> We will use a fairly neutral foot placement, with the heels about shoulder width apart and the toes pointed out at about 30 degrees.

**Why not:** Stance width is a frontal-plane measurement and toe angle is a transverse-plane measurement. Neither is recoverable from a single sagittal view. The document's own illustration of the standard (Figure 2-12) is an overhead view.

**Needed:** A front or overhead camera angle.

### Rack height and unracking procedure

*ref p. 28, 31, 35*

> Set the rack height so that the bar in the rack is at about the level of your mid-sternum.

**Why not:** A property of the setup before the set, not of a repetition. The rack and the unracking are typically outside the frame of an uploaded squat clip, and our analysis is rep-scoped.

**Needed:** Footage of the unrack, with the rack uprights and the lifter both in frame.

## Confidence caps

| Criterion | Capped at | Reason |
|---|---|---|
| Heels flat on the floor | medium | Heel landmarks are frequently occluded by the far leg and by footwear, and a few pixels of rise is within noise. Reported at reduced confidence, and `cannot_assess` when the foot is occluded. |
| Bar placement on the back | low | We can distinguish grossly high bar placement from plausible placement, and nothing finer. Never returns a confident "meets standard"; at best "consistent with low-bar placement". |
| Eye gaze direction | low | Gaze is not observable; head orientation is. The head is also routinely occluded by the plate in a side view - it is in the common sample. Reports only a clear upward-directed head, otherwise `cannot_assess`. |
