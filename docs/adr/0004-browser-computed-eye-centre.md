---
status: accepted
---

# Eye centre located in the browser (Timm & Barth); pixels never leave it

We want to try the Timm & Barth gradient method ("Accurate Eye Centre Localisation by Means of Gradients") as a second estimate of where the iris sits in each eye, next to the mean of MediaPipe's four iris landmarks. The method needs pixels, and this service only receives landmarks.

The browser runs the method and sends this service two numbers per eye plus a confidence (`frame.eye_centres`, protocol version 2). Eye crops are not sent, in any form.

- **Pixels stay in the browser.** ADR 0003 rejected streaming video on privacy grounds, and a small eye crop is still biometric pixel data of a Learner's face. Sending crops "transiently" was rejected: the service would gain nothing the centre doesn't already give it, and the privacy rule would stop being simple to state.
- **The feature maths is no longer in one place.** ADR 0003 kept `extract_features` in Python so the feature definition has a single implementation. The method itself now runs in JavaScript. We accept that, and bound it: this repo holds a Python reference (`eye_centre.py`), the crop definition (docs/eye-centre.md) and golden crops (`tests/golden/eye_centre.json`) that the browser implementation must reproduce. Everything after the centre (normalising it against the eye corners, the confidence threshold, the fallback, the vector layout) stays in `eye_features.py`. WASM from one shared source was rejected as more build machinery than a roughly 30-line algorithm needs.
- **Added next to the landmark mean, not replacing it.** The version 2 feature vector is the version 1 vector plus 4 values (24 total). Both estimates are then available on the same Session, so the real question, whether Timm & Barth beats the landmarks at webcam resolution, can be answered from live data before dropping either. A low-confidence or missing centre falls back to the landmark mean inside the service, so the vector size is fixed per Session.
- **Protocol version 2.** Messages are `extra="forbid"`, so an optional field alone would break a new browser on an old service mid-Session. The handshake exists for this; the service supports versions 1 and 2.

The change is hard to undo because both browser and service now depend on the crop definition and the version 2 vector. Whether it pays off is open: MediaPipe's refined iris landmarks may already be as good, and 16 calibration samples may overfit 24 features (ADR 0001). If the comparison shows no gain, drop the version 2 vector rather than keep the cost.
