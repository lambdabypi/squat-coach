# Demo script - 10 minutes, 5 in reserve

The brief asks for a 15-minute walkthrough. This script fills **10**, leaving 5 for their
questions, for the new video they may hand you, and for the rule change they may ask for. Running
short is the correct failure mode: a walkthrough that overruns cannot be rescued live.

`DEMO.md` is the reference notes and setup. This is the thing you speak.

**Spoken lines are in quotes.** Everything in brackets is a stage direction, not to be read aloud.

---

## Before you press record

- Local pair running (`DEMO.md` "Before you start"). **No `ANTHROPIC_API_KEY` set.**
- `/health` on the deployed backend hit once, so Cloud Run is awake.
- Two browser tabs: **A** the local app on the upload screen, **B** a finished report from a
  pre-warmed run of the common sample.
- `skill/squat_standards.yaml` open in an editor, scrolled to `back_angle` (line 118).
- `git diff skill/` clean.
- Common sample and `EVIDENCE/hard-sample/hard_frontview_20s.mp4` in an easy-to-reach folder.

---

## 0:00 - 1:00  The problem

> "Someone films their squat from the side and asks one question: was that deep enough?
>
> Today they get a coach at eighty dollars an hour, a forum thread, or an app that says 'your
> depth score is 87 percent' - confident, unsourced, impossible to argue with.
>
> That last one is the interesting failure. It isn't wrong because the number is inaccurate. It's
> wrong because there's nothing behind it you can check."

## 1:00 - 2:00  What this does differently

> "Squat Coach assesses a side-view squat against one specific text - the squat chapter from
> Starting Strength - and cites the page behind every verdict. You can disagree with it, follow it
> back to the source, and decide for yourself. That's a different product from a score.
>
> The second difference matters more, and it's the thing I'd want a customer to notice."

[Tab A, landing page. Point at the coverage table.]

> "Eleven criteria come out of that document. Eight of them a side-on camera can judge. Three -
> knees tracking out, stance width, rack height - are side-to-side or rotational. No camera
> pointed at your profile can see them, on any video, ever.
>
> So the app says so, up front, before you upload anything. Most tools in this space quietly score
> them anyway."

> "A tool that tells you what it cannot see is one you can trust about what it can."

## 2:00 - 3:15  Run it live on a new file

[Start the upload NOW so it processes while you talk. Narrate over the progress.]

> "I'm uploading a clip it hasn't seen in this session, so this is a real run, not a replay.
>
> What's happening right now is worth a sentence. The pose estimation is running **in this
> browser**, frame by frame. The video never leaves the laptop - what goes to the server is a few
> hundred landmark coordinates and a handful of small frames for the barbell detector.
>
> Server-side, this same analysis took about five minutes on the free tier. In the browser it's
> under a minute, and the file staying local is a privacy answer I get for free."

[Land on the report.]

## 3:15 - 5:00  The evidence

> "Every repetition is assessed separately. Here's the first one."

[Toggle the skeleton and bar path.]

> "Green landmarks were actually seen by the model. Orange ones were inferred - the model's best
> guess at a joint it couldn't observe. The barbell marker is solid where the plate was genuinely
> detected in pixels, and dashed where its position is estimated from the shoulder.
>
> That distinction isn't decoration. It runs all the way through to the findings: a measurement
> built on an estimated bar position is labelled as such and its confidence is capped."

[Click a finding's timestamp.]

> "Click any finding and the player jumps to the exact frame the measurement came from. You're
> never asked to take a number on faith."

[Click a citation pill.]

> "And the citation is the verbatim text from the source, with its page."

[Point at a tolerance pill.]

> "This one matters. The document is a coaching text - it states almost **no** numbers. It says
> your back should be 'at about a forty-five degree angle', and never says plus or minus what.
>
> So every number here is tagged. 'Per document' means the text says it. 'Our tolerance' means I
> chose it. They're never mixed, and in a minute I'll show you the code refusing to let them be."

## 5:00 - 6:00  The most counter-intuitive result

[Open the depth finding. It reads *cannot assess* on both reps.]

> "Depth is the headline question, and on the reference clip this tool refuses to answer it. That's
> the best argument for the whole design.
>
> Two reasons. The hip and knee landmarks are within two hundredths of a shin-length at the bottom,
> inside my own measurement tolerance. And the document defines depth at the hip **crease**, while
> pose estimation gives me a hip **joint centre** a couple of centimetres higher - a systematic
> bias, in the direction of calling people shallow.
>
> I could have picked a side. It would have looked more impressive and it would have been invented."

[Show the annotated still.]

> "You can see he really is at about parallel. The honest answer is 'too close to call', and it
> tells you exactly how close."

## 6:00 - 7:30  Change a rule live

> "You said you might want to change a rule during the review. Let's do it."

[Editor, `skill/squat_standards.yaml`, `back_angle` tolerance. Change `15` to `5`. Save.]

> "Back angle: the document says about forty-five degrees. My tolerance around that is plus or
> minus fifteen. This lifter measured fifty-nine and fifty-eight degrees - inside it, so both
> repetitions pass.
>
> I'll tighten it to five."

[Re-run the analysis.]

> "Both repetitions now fail. **No application code changed** - the skill is a YAML file the
> backend re-reads on every request. That's the point of parsing the document into a skill rather
> than hard-coding its rules."

[Now change that tolerance's `provenance` to `document_stated`. Restart the backend.]

> "Now the other direction. I'll claim this tolerance came from the document."

[It refuses to start.]

> "It won't boot. A tolerance is a margin I invented, the document states none, so that edit is
> always a lie and it fails loudly instead of quietly relabelling my number as the book's.
>
> That's the 'do not present unsupported thresholds as document requirements' requirement,
> enforced by the loader rather than promised in a README."

[Revert both edits. `git diff skill/` to confirm clean.]

## 7:30 - 8:30  A video it should refuse

[Upload `hard_frontview_20s.mp4`.]

> "Last one. A front-view squat - perfectly good video, wrong angle.
>
> Note what doesn't happen: it doesn't fail to find a person. Pose detection actually gets
> **better** when someone faces the camera. Detection is high, repetitions are found, everything
> looks healthy - and it still refuses, on camera angle alone, with instructions to re-record.
>
> That's the case I was most worried about, because every normal signal of a bad upload looks
> fine. The gate measures how far apart the left and right landmarks sit - a true side view
> collapses them onto each other. This one's at point five three; past point four, nothing is
> assessed."

## 8:30 - 9:30  What I verified, and what broke

> "A minute on how I know any of this works.
>
> Everything was verified through Python, and it all passed. Then I wrote one test that drives a
> real browser - uploads a real file, lets the browser's own WebAssembly build do the pose work,
> and compares every verdict to the verified baseline.
>
> It failed on the first run. The browser published a confident 'you did this wrong' on hip drive
> where the server abstained. Same video, same rules.
>
> My first diagnosis was wrong. I decided it was pixel noise near a threshold, raised the
> threshold, re-ran, and got the identical number back - which disproved my own explanation. So I
> reverted it.
>
> The real cause: the bottom of a squat is the peak of a nearly flat curve, so which frame *is*
> the bottom is only good to a frame or two, and that metric read a fixed window starting there. A
> two-frame shift changed the measurement ninefold.
>
> Checking properly, the other repetition ranged from zero point three six to one point eight five
> depending on that frame - straddling the pass/fail line. It had been shipping as a confident
> failure. It now abstains."

> "That's the one I'd want you to judge me on. Not that it was broken - that using the product
> found what the test suite couldn't, and the fix made the tool quieter rather than louder."

## 9:30 - 10:00  Close

> "Five and a half hours, deployed, with the reference document parsed into a skill you can edit
> without touching a line of application code.
>
> What I'd do next, in order: a labelled set of clips so those tolerances stop being my judgement
> and start being measured; anchor that hip-drive window by displacement so the criterion can
> report again instead of abstaining; and a front-camera pass to pick up the three criteria this
> one honestly can't see.
>
> Happy to take it anywhere you want - a new video, a different rule, or into the code."

---

## If you are running long

Cut in this order. Each is self-contained.

1. **8:30 block** down to two sentences: "a browser test found a verdict that depended on which
   frame we called the bottom; it had been shipping as a confident failure and now abstains."
2. **b) evidence** - drop the citation pill, keep observed-vs-inferred and jump-to-frame.
3. **7:30 refusal** - describe it instead of uploading.

Never cut 5:00 (why depth abstains) or 6:00 (the live rule change). The first is the argument for
the product, the second is the thing they explicitly asked to see.

## If they interrupt with their own video

Say this while it processes:

> "Worth watching the gates while this runs. If the angle is off, or it can't find a repetition,
> it will tell you rather than produce numbers anyway."

Then narrate whatever comes back honestly, including a refusal. **A refusal on their video is a
good demo, not a failed one** - it is the behaviour the whole design is for. If a verdict looks
wrong, say so and open the frame it came from; investigating an incorrect result live is on their
list of things to see.

## Numbers you may be asked for

| | |
|---|---|
| Build time | 5.6 hours |
| Criteria | 11 total, 8 assessable from a side view, 3 not |
| Common sample verdicts | 6 meet, 2 do not, 14 cannot assess |
| Back angle measured | 59.2 and 58.5 degrees, against "about 45" |
| Depth margin | within 0.02 shin-lengths, inside tolerance |
| Bar path | 0.27 and 0.24 shin-lengths off the midfoot, about 9 cm |
| Deployed analysis | about 53 seconds, pose in the browser |
| Server-side equivalent | about 302 seconds on the free tier |
| Front-view gate | refused at 0.53; threshold is 0.40 |
| Cost per video | zero as deployed; the language model is off and the rule engine produces every verdict |
