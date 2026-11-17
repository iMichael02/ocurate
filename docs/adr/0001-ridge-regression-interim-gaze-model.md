---
status: accepted
---

# Ridge regression as the interim gaze model, not the WebEyeTrack CNN

The original design called for a modified WebEyeTrack lightweight CNN ("BlazeGaze") personalized via few-shot/MAML-style adaptation. `gaze_model.py` instead implements this stage as an `sklearn` `Ridge` regression pipeline, fit directly on each learner's calibration samples.

We're keeping Ridge as the real interim approach rather than a placeholder to blindly replace: the calibration grid (originally 9 points, now 16, see ADR 0003) produces far too little data (one sample per point) to train or meaningfully personalize a CNN from scratch. Moving to the CNN would require a pretrained backbone that's fine-tuned on the calibration samples rather than trained from them directly — a materially bigger undertaking that hasn't been started. Ridge may end up being the shipped approach unless that pretrained-backbone work happens.

## Evidence (2026-11-17)

The offline benchmark ([gaze-benchmark.md](../gaze-benchmark.md)) measured this model on one Learner over five sessions: about 19 % of fixation frames land on the correct Braille Cell (8.6 to 34.1 % between sessions) and the mean error is about 4 degrees, roughly the width of several Cells. The error is already 11 to 16 % of the screen on the calibration points the model was fitted on, and reading is no worse than an unseen calibration target, so drift is not the cause and the six eye features carry too little information. None of 16 variations (regularisation, polynomial and kernel terms, clipping, out-of-range handling, head pose, smoothing, fixation settings, eye-centre features) improved it reliably. The decision above stands for now: no model change is adopted. The pretrained-backbone path is the more likely fix, and it is a separate ticket that needs recordings from many people to judge. This is one Learner: it says nothing about how the model varies across people.
