# Eye centre (Timm & Barth): what the browser computes

Decision and trade-offs: [ADR 0004](./adr/0004-browser-computed-eye-centre.md). Reference implementation: [`eye_centre.py`](../eye_centre.py). Golden vectors: `tests/golden/eye_centre.json`. Protocol field: `frame.eye_centres` (version 2), see [websocket-protocol.md](./websocket-protocol.md).

Only the two numbers per eye and a confidence are sent. The crop never leaves the browser.

## Crop

Per eye, from the four corner landmarks already sent in `eye_corners` (left, right, top, bottom). Work in **camera-image pixels**, not normalized coordinates (normalized axes have different scales, which would skew a rotated crop).

1. `u` = unit vector from the left corner to the right corner. `v` = `(-u.y, u.x)`, which points down the face for an upright head.
2. Centre = midpoint of the left and right corners. Width `W` = 1.4 × the distance between them (20% margin each side). Height = `W / 2`.
3. Sample a 40 × 20 grayscale image (columns × rows) from the camera image over that rotated rectangle, bilinear. Pixel `(i, j)` has image position `centre + u·W·((i+0.5)/40 − 0.5) + v·(W/2)·((j+0.5)/20 − 0.5)`.
4. Grayscale: the luminance of the RGB frame, range 0–255 (not mirrored; if the video is shown mirrored, crop from the unmirrored source).

## Algorithm

As in `eye_centre.py`, which is authoritative: central-difference gradients, keep those stronger than mean + 0.3 × std of the magnitudes, score every pixel as a centre by how well its displacement vectors align with the gradients (negative alignment counts as 0, squared, averaged), weight by darkness (Gaussian-blurred, σ = 1 px), take the maximum.

Output is `(x, y, confidence)`: `x` and `y` in 0–1 of the crop, `confidence` in 0–1 (1 minus the best peak further than 5 px away, relative to the best; 0 for a crop without gradients).

## Mapping back

`x`, `y` → image position with the formula in step 3 (using `x` and `y` for `(i+0.5)/40` and `(j+0.5)/20`), then divide by the image width and height. Send that as `eye_centres[k].x` and `.y`, in the same normalized camera-image coordinates as the landmarks. Left eye first, then right, like `iris` and `eye_corners`.

## What the service does with it

`eye_features.extract_features(frame, use_eye_centres=True)` normalizes each centre against its eye's corners (like the iris) and appends the 4 values. A centre below `EYE_CENTRE_MIN_CONFIDENCE` (0.5), or outside the image, is replaced by the mean of that eye's iris landmarks. The browser should always send a centre if it has one and let the service judge it; send `eye_centres` only on a version 2 Session.
