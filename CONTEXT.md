# Ocurate

A webcam-based tool that tracks a learner's eye gaze while they read Braille displayed on screen, so their Braille-reading process can be evaluated. Built for sighted people training to become caregivers of blind people, to gauge their own Braille reading progress. See [architecture-design.md](./architecture-design.md) for the technical pipeline.

## Language

**Learner**:
The sighted person reading on-screen Braille whose gaze is tracked. Typically someone training to become a caregiver of a blind person; "caregiver" describes their real-world goal, not a separate tracked role in this system.
_Avoid_: Caregiver, Trainee, User

**Session**:
One run of calibrate → read → produce a result, for a single Learner. Currently ephemeral: nothing persists once the session ends, and no history is kept across sessions.
_Avoid_: Profile, History

**Calibration**:
A short exercise where the Learner looks at each of a 9-point on-screen grid in turn, producing samples used to personalize the generic gaze model to that individual.
_Avoid_: Enrollment, Training (training is the generic model's separate offline process)

**Gaze Point**:
A normalized (x, y) coordinate, predicted per frame, representing where on the screen the Learner is looking.

**Braille Cell**:
A discrete on-screen region corresponding to one Braille character's position. A Gaze Point falling inside a cell's bounds is assigned to that cell (e.g. "C3"), turning imprecise gaze coordinates into a specific character reference.
_Avoid_: Gaze Target

**Passage**:
A fixed, pre-loaded piece of Grade 1 (uncontracted) Braille text the Learner reads during a Session, with a known total character/word count and uniform line length. Ground truth for both Reading Speed and eye-movement analysis.
_Avoid_: Text, Content

**Reading Speed**:
The headline evaluation metric: characters or words the Learner reads per minute (CPM/WPM), computed from the Passage's known total character/word count divided by the elapsed time between reading start and end.
_Avoid_: Fluency, Accuracy

**Fixation**:
A period where the Learner's gaze stays within a small dispersion for at least a minimum duration, indicating a Braille Cell is being read rather than passed over. Reduces noisy per-frame Gaze Points into a discrete reading event located at a Braille Cell.

**Saccade**:
The rapid gaze movement between two consecutive Fixations, moving from one Braille Cell to another.

**Regression**:
A Saccade that moves to an earlier Braille Cell than the one most recently fixated, rather than progressing forward through the Passage.
_Avoid_: Backtrack

**Skipped Character**:
A Braille Cell that is never fixated between two Cells that are fixated in forward reading order.
_Avoid_: Missed Character

Fixation, Saccade, Regression, and Skipped Character form a secondary analysis layer alongside Reading Speed — they characterize *how* the Learner read, not just how fast.
