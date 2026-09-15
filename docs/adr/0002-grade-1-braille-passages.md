---
status: accepted
---

# Grade 1 Braille for reading-speed Passages, Grade 2 deferred

Reading Speed is computed as a Passage's known character/word count divided by elapsed reading time, and the Braille-aware gaze mapping assumes one on-screen Cell = one character. Grade 2 (contracted) Braille breaks that assumption: a single cell can represent a whole word or letter group, so cell count no longer corresponds cleanly to character count or word count.

We're using Grade 1 (uncontracted) Braille for Passages so CPM/WPM stay unambiguous, and because it's the natural starting point for a caregiver-in-training learning to read Braille at all. Grade 2 support is deliberately deferred rather than ruled out — Passage-loading and character-counting code should avoid hardcoding the one-cell-one-character assumption so deeply that adding Grade 2 later requires a rewrite.
