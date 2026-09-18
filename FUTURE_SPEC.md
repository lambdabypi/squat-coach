# Future spec: making this faster, and what it would cost

A 7.9-second clip currently takes about 85 seconds end to end. This document sets out where that
time goes, which speed-ups are safe, which are not, and what the alternatives cost.

Every performance figure below was **measured on the common sample on the development machine**
(CPU only, no GPU) using `scripts/bench_speed.py` and `scripts/bench_accuracy.py`. Figures taken
from vendors or third parties are labelled as such, with sources at the end.

---

## 1. Where the 85 seconds goes

| Stage | Time | Share |
|---|---:|---:|
| Probe (ffprobe) | <0.1s | negligible |
| Pose landmarks, 236 frames | 14.5s | 17% |
| Barbell detection (HoughCircles every frame) | 43.7s | **51%** |
| Reps, quality gates, rules, target pose | <1s | 1% |
| Agent narration | 25-33s | 31% |

The single largest cost is not the neural network. It is running a classical circle detector on
every one of 236 frames. Pose alone runs at 16.3 fps; adding per-frame Hough drops the pass to
4.1 fps.

## 2. What each change actually buys

Measured, same machine, same clip:

| Configuration | Seconds | vs realtime | Speed-up |
|---|---:|---:|---:|
| **Shipped:** heavy pose + Hough every frame | 58.2 | 7.3x | 1.0x |
| heavy + Hough every 5th frame | 23.6 | 3.0x | **2.5x** |
| heavy, no bar detection at all | 14.5 | 1.8x | 4.0x |
| full pose + Hough every 5th | 12.4 | 1.6x | 4.7x |
| lite pose + Hough every 5th | 12.7 | 1.6x | 4.6x |
| full pose + Hough every 5th, half resolution | 5.5 | 0.7x | 10.6x |
| lite pose + Hough every 5th, half resolution | 4.4 | **0.6x** | **13.2x** |

The bottom row is faster than real time on a laptop CPU. Pose detection stayed at 236/236 frames
in every configuration, and halving the resolution *improved* plate detection from 81% to 96%,
which is plausible: downscaling suppresses the small high-frequency structures that generate
spurious circles.

## 3. The catch, and it is the whole story

A faster configuration is only a speed-up if it gives the same answers. It does not.

`scripts/bench_accuracy.py` runs the full pipeline under each pose model and compares every
verdict and measurement that reaches the user:

| Pose model | Speed-up | Verdicts changed (of 22) | Largest measurement shift |
|---|---:|---:|---|
| heavy (shipped) | 1.0x | - | - |
| full | 1.6x | **4** | back angle 58.5 to 66.1 degrees (7.6 degrees) |
| lite | 1.4x | **9** | knee position +0.154 to -0.173 shin (sign flip) |

The lite model changes 41% of the verdicts. Depth flips from `cannot_assess` to
`does_not_meet_standard` on both repetitions under both lighter models.

**The uncomfortable implication.** Our depth tolerance is 0.03 shin-lengths. The disagreement
between pose models on that same measurement is 0.16 to 0.23 shin-lengths, five to seven times
larger. The tolerance was calibrated against landmark jitter *within* one model; it says nothing
about uncertainty *across* models. The borderline depth result that this application treats as its
most interesting finding sits entirely inside the model-selection noise floor.

That is not an argument for the heavy model being right. It is an argument that **we currently have
no way to know which is right**, because there is no ground truth in this project. Until there is,
switching pose models is not a performance decision, it is a silent change to the product's
answers.

## 4. Recommended sequence

**Do first, no accuracy risk: fix the bar detection cadence.**
Detect the plate every Nth frame and track between detections, or seed a CSRT tracker from the
first confident detection and re-detect periodically. Pose landmarks are untouched, so every
pose-derived verdict is bit-identical. Measured: **2.5x, 58.2s to 23.6s.** This is the only
speed-up that is free of judgment.

**Do second: build the ground truth that the rest depends on.**
Thirty to fifty clips with hand-labelled depth, back angle and bar position at the bottom frame.
Without it, every subsequent line in this document is guesswork dressed as engineering. It also
turns the tolerances from defensible guesses into measured values, which is the single biggest
weakness in the current build.

**Do third, once ground truth exists: re-run the model comparison against it.**
`bench_accuracy.py` already produces the comparison; it just has nothing to score against. If the
lighter model agrees with the labels as well as the heavy one does, take the 13x and ship
sub-realtime analysis. If it does not, the heavy model stays and the honest per-video time is
about 24 seconds, not 4.

**Do fourth: move the agent off the critical path.**
The 25-33s narration is a third of the wall time and produces no verdicts. Stream the
deterministic findings to the user immediately and fill in the prose as it arrives. This is a UX
change, not a model change, and it costs nothing in accuracy.

---

## 5. Would a VLM be faster?

No, and `scripts/cost_model.py` quantifies it.

| Approach | Per video | Notes |
|---|---:|---|
| **Shipped** (local CV + Haiku narration) | **$0.0255** | measured |
| VLM, 4 downscaled frames, Haiku 4.5 | $0.0198 | cheaper, and blind between frames |
| VLM, every 3rd frame, Haiku 4.5 | $0.2327 | |
| VLM, every frame, Haiku 4.5 | $0.6695 | 26x the shipped cost |
| VLM, every frame, Opus 5 | $3.35 | |

A 1080x1920 frame is about 2,765 input tokens at Anthropic's documented `width x height / 750`.
Sending all 236 frames is 654,540 input tokens.

Latency moves the same way: four images is one round trip, roughly the 25-33s the narration
already takes; 236 images is several minutes of prefill. **A VLM that sees enough of the clip to
track a barbell is slower and more expensive than the shipped design, and still returns estimates
rather than measurements.** A VLM that sees four frames is cheap and fast and cannot produce a bar
path, a per-landmark visibility score, or a number anyone can check against a frame.

## 6. Would edge hardware be faster?

This is the more interesting question, and for a gym-installed product the answer is probably yes,
for reasons beyond speed.

**Hardware.** The NVIDIA Jetson Orin Nano Super Developer Kit lists at **$249**, delivering **67
sparse TOPS**, 8 GB LPDDR5 at 102 GB/s, in a **7-25 W** envelope. NVIDIA raised the older Orin Nano
from 40 to 67 TOPS through a JetPack 6.1 software update, so existing units gained the headroom
without new hardware. *(Vendor figures, not measured by us.)*

**What it would run.** The 8 GB board is documented as suitable for vision-language models up to
roughly 4B parameters: Qwen2.5-VL-3B, VILA 1.5-3B, Gemma-3 4B. That is enough to run the narration
locally and drop the API cost to zero. MediaPipe pose would move from CPU to the GPU delegate.

**What it would cost.**

| | Cloud (today) | Jetson Orin Nano Super |
|---|---|---|
| Hardware | none | $249 one-off |
| Per video | $0.0255 | $0 marginal |
| Power | n/a | 7-25 W |
| Break-even | - | **~9,800 videos** |
| Upload latency | full clip upload | none, video never leaves the room |
| Privacy | footage of bodies leaves the premises | it does not |

At a gym doing 30 form checks a day, break-even is about eleven months on API cost alone. The
privacy argument arrives immediately and does not depend on volume.

**The honest caveat.** We have not benchmarked this pipeline on a Jetson. The CPU figures above do
not transfer: MediaPipe's GPU delegate on Orin would help pose, but HoughCircles is OpenCV on CPU
and would remain the bottleneck unless ported to CUDA. **Section 4's first recommendation matters
more than the hardware.** Buying a Jetson to accelerate a pipeline that spends 51% of its time in a
circle detector would be solving the wrong problem.

## 7. Would a better pose model help?

Meta's **Sapiens** is the obvious candidate on accuracy: human-centric foundation models at
0.3B-2B parameters, trained at 1K resolution, reporting state-of-the-art 2D pose. It would very
likely fix our worst weakness, which is occluded-joint accuracy.

It would also make everything slower, not faster. Sapiens runs at 1024x768 native against
MediaPipe's 256x256; the paper **publishes no inference throughput at all**, and the only
third-party figure we could find measures roughly **3.3 fps on a V100** for pose. MediaPipe heavy
manages 16.3 fps on this laptop's CPU.

So Sapiens is an accuracy upgrade bought with a large latency bill, and it belongs after ground
truth exists to prove the accuracy is actually better on this task. An earlier draft of
`BUILD_NOTES.md` suggested swapping to Sapiens for edge deployment; that was written before these
figures were checked and was wrong about the direction of the trade.

---

## 8. Other work this build did not reach

**Calibrated tolerances.** Every numeric threshold not stated by the reference document is an
engineering guess. Section 3 shows they are smaller than the model-selection noise. Ground truth
fixes this and nothing else does.

**A browser-level test.** Every verification script exercises the backend or the data; none opens
the page. That is how a render bug shipped past a green suite. One headless-browser smoke test
that uploads a clip and asserts the canvas paints would close it.

**Depth from the hip crease, not the joint centre.** The document defines depth by the crease
(Fig 2-1); pose gives a joint centre, which sits higher and biases every depth verdict toward
"not deep enough". A learned offset from labelled data would remove a known systematic bias.

**Multi-camera capture.** Three of the document's eight headline criteria (knees-out, stance, rack
height) are structurally invisible to a sagittal camera. A second phone at 45 degrees converts
three permanent `cannot_assess` results into real verdicts, and is the largest single increase in
product value available.

**Persistence and accounts.** Jobs live in memory and a restart loses them. Progress over time is
the obvious retention feature for a coaching product and is impossible without storage.

**Per-plate scale calibration.** Centimetre figures assume a 450 mm competition plate. Detecting
plate type, or asking the user once, would remove the assumption.

---

## Sources

Vendor and third-party figures used above. Everything else in this document was measured locally.

- [NVIDIA Jetson Orin Nano Developer Kit Gets a Super Boost](https://developer.nvidia.com/blog/nvidia-jetson-orin-nano-developer-kit-gets-a-super-boost/) - 67 sparse TOPS, 102 GB/s, JetPack 6.1 uplift
- [Buy the Latest Jetson Products](https://developer.nvidia.com/buy-jetson) - $249 list price
- [Getting Started with Edge AI on NVIDIA Jetson: LLMs, VLMs, and Foundation Models for Robotics](https://developer.nvidia.com/blog/getting-started-with-edge-ai-on-nvidia-jetson-llms-vlms-and-foundation-models-for-robotics/) - which VLMs fit an 8 GB Orin Nano
- [NVIDIA Jetson AI Lab benchmarks](https://www.jetson-ai-lab.com/archive/benchmarks.html) - published Jetson model benchmarks
- [MediaPipe pose landmark module](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/pose_landmark/README.md) - heavy/full/lite variants
- [Latency vs accuracy tradeoff, MediaPipe](https://theneuralbase.com/mediapipe/learn/advanced/latency-vs-accuracy-tradeoff/) - 142.59 / 55.28 / 35.37 ms on Xeon E5-2690 v4 at 640x480
- [Sapiens: Foundation for Human Vision Models](https://arxiv.org/abs/2408.12569) - model sizes and resolution; no inference throughput published
- [facebookresearch/sapiens](https://github.com/facebookresearch/sapiens) - reference implementation
- [Evaluation of Pose Estimation Systems for Sign Language Translation](https://arxiv.org/pdf/2604.24609) - third-party Sapiens throughput on V100
