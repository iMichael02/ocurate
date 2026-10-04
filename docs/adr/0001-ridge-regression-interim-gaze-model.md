---
status: accepted
---

# Ridge regression as the interim gaze model, not the WebEyeTrack CNN

The original design called for a modified WebEyeTrack lightweight CNN ("BlazeGaze") personalized via few-shot/MAML-style adaptation. `gaze_model.py` instead implements this stage as an `sklearn` `Ridge` regression pipeline, fit directly on each learner's calibration samples.

We're keeping Ridge as the real interim approach rather than a placeholder to blindly replace: the calibration grid (originally 9 points, now 16, see ADR 0003) produces far too little data (one sample per point) to train or meaningfully personalize a CNN from scratch. Moving to the CNN would require a pretrained backbone that's fine-tuned on the calibration samples rather than trained from them directly — a materially bigger undertaking that hasn't been started. Ridge may end up being the shipped approach unless that pretrained-backbone work happens.
